"""TaskMarket live API — https://api.taskmarket.dev"""

from __future__ import annotations

from typing import Any, Callable

from centbot.platforms.auth_ethereum import (
    EthWallet,
    taskmarket_claim_message,
    taskmarket_read_message,
    taskmarket_submit_message,
    wallet_from_env,
    wallet_from_store,
)
from centbot.platforms.base import PlatformConnector, PlatformTask
from centbot.platforms.http import HttpClient, PlatformHTTPError


def _atomic_to_float(value: Any) -> float:
    try:
        return float(value) / 1_000_000.0
    except (TypeError, ValueError):
        return 0.0


def _sig_hex(sig: str) -> str:
    return sig if sig.startswith("0x") else "0x" + sig


def _hire_blocks_worker(task: dict[str, Any], worker_address: str | None) -> bool:
    """True when a hire reservation exists for a different wallet."""
    hire = task.get("hire")
    if not isinstance(hire, dict) or not hire:
        return False
    reserved = str(hire.get("worker") or "").strip()
    if not reserved:
        return False
    if not worker_address:
        return True
    return reserved.lower() != worker_address.lower()


def _skip_reason(task: dict[str, Any], worker_address: str | None) -> str | None:
    """Why a TaskMarket row must not be auto-accepted (None = workable)."""
    status = str(task.get("status") or "open").lower()
    if status and status != "open":
        return "unavailable"
    if task.get("claimedBy"):
        return "already_claimed"
    mode = str(task.get("mode") or "").lower()
    if mode in {"pitch", "auction"}:
        return "not_claim_mode"
    if mode == "claim":
        if bool(task.get("stakeRequired")):
            return "stake_payment_required"
        if _hire_blocks_worker(task, worker_address):
            return "hire_reserved"
        return None
    # bounty / benchmark: no /claim step — local accept then submit
    if mode in {"bounty", "benchmark", ""}:
        return None
    return "not_claim_mode"


def _is_auto_claimable(task: dict[str, Any], worker_address: str | None) -> bool:
    """True when CENTBOT can auto-accept (claim or bounty direct-submit)."""
    return _skip_reason(task, worker_address) is None


class TaskMarketConnector(PlatformConnector):
    name = "taskmarket"

    def __init__(
        self,
        config: dict[str, Any],
        api_key: str = "",
        wallet: EthWallet | None = None,
        credential_getter: Callable[[str], Any] | None = None,
    ):
        super().__init__(config, api_key)
        base = (config.get("base_url") or "https://api.taskmarket.dev").rstrip("/")
        self.client = HttpClient(base, timeout=float(config.get("timeout", 30)))
        self.wallet = wallet or wallet_from_env(config.get("wallet_env", "CENTBOT_ETH_PRIVATE_KEY"))
        if self.wallet is None and credential_getter:
            self.wallet = wallet_from_store(credential_getter("eth_wallet"))
        self.min_reward = float(config.get("min_reward", 0) or 0)
        self.limit = int(config.get("limit", 50))
        # None/empty = all open modes (bounty + claim). Stake/hire still soft-skipped.
        self.mode = config.get("mode") or None
        self.allow_stake_claims = bool(config.get("allow_stake_claims", False))

    def _caller_headers(self) -> dict[str, str]:
        if not self.wallet:
            return {}
        msg = taskmarket_read_message(self.wallet.address)
        sig = _sig_hex(self.wallet.sign_message(msg))
        return {
            "X-Taskmarket-Caller-Address": self.wallet.address,
            "X-Taskmarket-Caller-Signature": sig,
        }

    def list_tasks(self) -> list[PlatformTask]:
        if not self.enabled:
            return []
        params: dict[str, Any] = {"limit": self.limit, "status": "open"}
        if self.mode:
            params["mode"] = self.mode
        data = self.client.get_json("/api/tasks", params=params, headers=self._caller_headers() or None)
        tasks = (data or {}).get("tasks") or []
        worker = self.wallet.address if self.wallet else None
        out: list[PlatformTask] = []
        for t in tasks:
            amount = _atomic_to_float(t.get("netReward") or t.get("reward"))
            if self.min_reward and amount < self.min_reward:
                continue
            tags = t.get("tags") or []
            escrow = t.get("escrowTxHash")
            funded = bool(escrow) or amount > 0
            skip = _skip_reason(t, worker)
            claimable = skip is None
            raw_meta: dict[str, Any] = {"source": "taskmarket", "task": t}
            if skip:
                raw_meta["skip_reason"] = skip
            out.append(
                PlatformTask(
                    platform=self.name,
                    external_id=str(t.get("id")),
                    title=_title_from_description(t.get("description")),
                    description=str(t.get("description") or ""),
                    reward_amount=amount,
                    reward_currency="USDC",
                    url=f"https://taskmarket.dev/tasks/{t.get('id')}",
                    category_hint=_hint_from_tags(tags),
                    payer_id=str(t.get("requester") or ""),
                    payer_rating=0.8 if t.get("requesterAgentId") else 0.7,
                    funded=funded,
                    available=str(t.get("status")) == "open",
                    claimable=claimable,
                    automation_allowed=True,
                    payment_state="escrowed" if escrow else "promised",
                    raw=raw_meta,
                )
            )
        return out

    def register_account(self, payload: dict[str, Any]) -> dict[str, Any]:
        """TaskMarket identity = Ethereum wallet. Confirm wallet can authenticate against API."""
        if not self.wallet:
            return {
                "ok": False,
                "error": "wallet_required",
                "platform": self.name,
                "status": "error",
                "user_action": "set_CENTBOT_ETH_PRIVATE_KEY_or_store_eth_wallet_credential",
            }
        try:
            headers = self._caller_headers()
            # Probe authenticated read — wallet presence is the account
            self.client.get_json("/api/tasks", params={"limit": 1}, headers=headers)
            return {
                "ok": True,
                "status": "registered",
                "platform": self.name,
                "worker_address": self.wallet.address,
                "note": "TaskMarket uses wallet signatures; no separate signup API",
            }
        except PlatformHTTPError as exc:
            return {
                "ok": False,
                "error": str(exc),
                "status": exc.status,
                "platform": self.name,
                "worker_address": self.wallet.address,
                "body": exc.body,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "platform": self.name, "status": "error"}

    def accept_task(self, task: PlatformTask) -> dict[str, Any]:
        if not self.wallet:
            return {
                "ok": False,
                "error": "wallet_required",
                "hint": "Set CENTBOT_ETH_PRIVATE_KEY or credentials eth_wallet",
                "user_action": "SET_ETH_KEY.bat",
            }
        raw_task = (task.raw or {}).get("task") if isinstance(task.raw, dict) else None
        if not isinstance(raw_task, dict):
            raw_task = {}

        mode = str(raw_task.get("mode") or "").lower()
        # Bounty/benchmark: no /claim — book locally and submit artifacts later.
        if mode in {"bounty", "benchmark"}:
            return {
                "ok": True,
                "mode": "direct_submit",
                "external_id": task.external_id,
                "note": "bounty/benchmark — claim nav vajadzīgs, iesniegšana caur /submissions",
            }
        if mode in {"pitch", "auction"}:
            return {
                "ok": False,
                "error": "not_claim_mode",
                "reason": "not_claim_mode",
                "status": 400,
                "hint": "Pitch/auction nav auto-claim — vajag citu TaskMarket plūsmu.",
                "external_id": task.external_id,
            }
        skip = _skip_reason(raw_task, self.wallet.address)
        if skip == "stake_payment_required" and not self.allow_stake_claims:
            return {
                "ok": False,
                "error": "stake_payment_required",
                "reason": "stake_payment_required",
                "status": 402,
                "hint": "Šim claim vajag x402 stake (~1 USDC Base) — izlaists, kamēr stake nav ieslēgts.",
                "external_id": task.external_id,
            }
        if skip == "hire_reserved":
            hire = raw_task.get("hire") if isinstance(raw_task.get("hire"), dict) else {}
            return {
                "ok": False,
                "error": "hire_reserved",
                "reason": "hire_reserved",
                "status": 403,
                "hint": f"Hire rezervēts citam worker: {hire.get('worker')}",
                "external_id": task.external_id,
            }
        if skip and skip not in {"stake_payment_required"}:
            return {
                "ok": False,
                "error": skip,
                "reason": skip,
                "external_id": task.external_id,
            }

        msg = taskmarket_claim_message(task.external_id)
        sig = _sig_hex(self.wallet.sign_message(msg))
        # OpenAPI requires workerAddress+signature; taskId in body is accepted and documented elsewhere.
        body = {
            "taskId": task.external_id,
            "workerAddress": self.wallet.address,
            "signature": sig,
        }
        try:
            result = self.client.post_json(
                f"/api/tasks/{task.external_id}/claim",
                body,
                headers=self._caller_headers(),
            )
            from centbot.platforms.response import interpret_platform_result

            interpreted = interpret_platform_result(result, action="claim")
            return {**interpreted, "external_id": task.external_id, "signed_message": msg}
        except PlatformHTTPError as exc:
            return _claim_http_error(exc, task.external_id)

    def submit_result(self, task: PlatformTask, payload: dict[str, Any]) -> dict[str, Any]:
        """Submit per OpenAPI: workerAddress + artifacts[{fileName,mimeType,file}] + signature."""
        if not self.wallet:
            return {"ok": False, "error": "wallet_required"}
        artifacts = _build_taskmarket_artifacts(payload, task=task)
        if not artifacts:
            kinds = sorted(_required_media_kinds(task, payload))
            return {
                "ok": False,
                "error": "artifacts_required",
                "required_media": kinds,
                "hint": (
                    "TaskMarket API requires real deliverable files — "
                    + (
                        f"media kinds {kinds} missing from evidence/artifacts."
                        if kinds
                        else "no files found under evidence/artifacts/workdir."
                    )
                ),
            }
        msg = taskmarket_submit_message(task.external_id)
        sig = _sig_hex(self.wallet.sign_message(msg))
        body = {
            "workerAddress": self.wallet.address,
            "signature": sig,
            "artifacts": artifacts,
        }
        try:
            result = self.client.post_json(
                f"/api/tasks/{task.external_id}/submissions",
                body,
                headers=self._caller_headers(),
            )
            from centbot.platforms.response import interpret_platform_result

            interpreted = interpret_platform_result(result, action="submit")
            if interpreted.get("ok"):
                interpreted["status"] = "submitted"
            return interpreted
        except PlatformHTTPError as exc:
            return {"ok": False, "error": str(exc), "status": exc.status, "body": exc.body}

    def check_submission_status(self, submission_id: str) -> dict[str, Any]:
        try:
            data = self.client.get_json(f"/api/tasks/{submission_id}", headers=self._caller_headers() or None)
            task = data if isinstance(data, dict) else {}
            return {"submission_id": submission_id, "status": task.get("status") or "unknown", "task": task}
        except PlatformHTTPError as exc:
            return {"submission_id": submission_id, "status": "error", "error": str(exc)}

    def check_automation_rules(self) -> dict[str, Any]:
        return {
            "platform": self.name,
            "automation_allowed": True,
            "notes": "Official REST API. Wallet EIP-191 signatures required for claim/submit.",
            "requires_human_review": False,
            "wallet_loaded": bool(self.wallet),
        }

    def health(self) -> dict[str, Any]:
        try:
            data = self.client.get_json("/api/tasks", params={"limit": 1, "status": "open"})
            return {
                "platform": self.name,
                "enabled": self.enabled,
                "configured": True,
                "base_url": self.client.base_url,
                "live": True,
                "wallet_loaded": bool(self.wallet),
                "sample_count": len((data or {}).get("tasks") or []),
            }
        except PlatformHTTPError as exc:
            return {
                "platform": self.name,
                "enabled": self.enabled,
                "configured": True,
                "base_url": self.client.base_url,
                "live": False,
                "error": str(exc),
            }


def _claim_http_error(exc: PlatformHTTPError, external_id: str) -> dict[str, Any]:
    body = exc.body
    msg = ""
    code = ""
    if isinstance(body, dict):
        msg = str(body.get("error") or body.get("message") or "")
        code = str(body.get("code") or "")
    lower = msg.lower()
    if exc.status == 402 or "payment required" in lower or "claim stake" in lower:
        return {
            "ok": False,
            "error": "stake_payment_required",
            "reason": "stake_payment_required",
            "status": 402,
            "body": body,
            "hint": "TaskMarket pieprasa x402 claim stake (Base USDC) — izlaid, līdz stake ir apmaksāts.",
            "external_id": external_id,
        }
    if exc.status == 401 or "signature does not match" in lower:
        return {
            "ok": False,
            "error": "signature_mismatch",
            "reason": "signature_mismatch",
            "status": 401,
            "body": body,
            "hint": "Paraksts nesakrīt ar workerAddress — pārbaudi ETH private key un claim message formātu.",
            "external_id": external_id,
        }
    if "not a claim task" in lower:
        return {
            "ok": False,
            "error": "not_claim_mode",
            "reason": "not_claim_mode",
            "status": exc.status or 400,
            "body": body,
            "hint": "Nav Claim task — bounty/pitch nevar claimot ar /claim.",
            "external_id": external_id,
        }
    if "hire offered to another" in lower or (exc.status == 403 and "hire" in lower):
        return {
            "ok": False,
            "error": "hire_reserved",
            "reason": "hire_reserved",
            "status": 403,
            "body": body,
            "hint": "Hire rezervēts citam worker.",
            "external_id": external_id,
        }
    return {
        "ok": False,
        "error": msg or str(exc),
        "status": exc.status,
        "body": body,
        "code": code or None,
        "external_id": external_id,
    }


def _guess_mime(path: str) -> str:
    import mimetypes

    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


def _required_media_kinds(task: Any | None, payload: dict[str, Any]) -> set[str]:
    """Detect when the brief demands producing a concrete non-text deliverable.

    Keep this strict: bare words like ``render.py`` / ``docker image`` must NOT
    block submitting real code/markdown artifacts.
    """
    import re

    parts = [
        str(getattr(task, "title", "") or ""),
        str(getattr(task, "description", "") or ""),
        str(getattr(task, "category_hint", "") or ""),
        str(payload.get("title") or ""),
        str(payload.get("description") or ""),
        str(payload.get("category") or ""),
    ]
    raw = getattr(task, "raw", None) if task is not None else None
    if isinstance(raw, dict):
        parts.append(str(raw.get("task") or raw)[:2000])
    blob = " ".join(parts).lower()
    # Produce-oriented verbs — exclude bare "render.py" / "submit result" alone
    create = bool(
        re.search(
            r"\b(create|generate|make|build|produce|draw|compose|design|izveido|ģenerē)\b",
            blob,
        )
    )
    if not create:
        return set()
    kinds: set[str] = set()
    # Require explicit media file / produce-image phrasing (not "docker/system/disk image")
    blob_media = re.sub(
        r"\b(docker|system|disk|container|vm|ami|oci)\s+images?\b",
        " ",
        blob,
    )
    if re.search(
        r"(\.png\b|\.jpe?g\b|\.webp\b|"
        r"\bpng\b|\bjpg\b|\bjpeg\b|"
        r"\b(logo|banner|thumbnail|photobooth|photo[- ]?strip|attēl)\b|"
        r"\b(create|generate|make|draw|design)\b.{0,40}\b(image|picture|photo)\b|"
        r"\b(image|picture|photo)\b.{0,40}\b(create|generate|make|draw|design)\b)",
        blob_media,
    ):
        kinds.add("image")
    if re.search(r"\.gif\b|\banimated gif\b|\bcreate (a )?gif\b", blob):
        kinds.add("gif")
    if re.search(r"\.mp4\b|\.webm\b|\bshort (video|clip)\b|\bcreate (a )?video\b", blob):
        kinds.add("video")
    if re.search(r"\.pdf\b|\bcreate (a )?pdf\b|\bpdf (file|document|report)\b", blob):
        kinds.add("pdf")
    if re.search(r"\.apk\b|\bandroid (apk|package)\b", blob):
        kinds.add("apk")
    if re.search(r"\.xlsx?\b|\.csv\b|\bcreate (a )?(csv|excel|spreadsheet)\b", blob):
        kinds.add("tabular")
    return kinds


_MEDIA_SUFFIX = {
    "image": {".png", ".jpg", ".jpeg", ".webp"},
    "gif": {".gif"},
    "video": {".mp4", ".webm", ".mov"},
    "pdf": {".pdf"},
    "apk": {".apk", ".aab"},
    "tabular": {".csv", ".xlsx", ".xls"},
}


def _artifacts_satisfy_media(artifacts: list[dict[str, str]], kinds: set[str]) -> bool:
    if not kinds:
        return True
    names = " ".join(a.get("fileName", "").lower() for a in artifacts)
    mimes = " ".join(a.get("mimeType", "").lower() for a in artifacts)
    for kind in kinds:
        suffixes = _MEDIA_SUFFIX.get(kind) or set()
        if any(names.endswith(suf) or suf.lstrip(".") in names for suf in suffixes):
            continue
        if kind == "image" and any(m.startswith("image/") and "gif" not in m for m in mimes.split()):
            continue
        if kind == "gif" and ("image/gif" in mimes or names.endswith(".gif")):
            continue
        if kind == "video" and any(m.startswith("video/") for m in mimes.split()):
            continue
        if kind == "pdf" and "application/pdf" in mimes:
            continue
        return False
    return True


_PLACEHOLDER_NAMES = frozenset(
    {"result.json", "result.txt", "summary.txt", "summary.json", "unsupported_category.txt", "meta.json", "image_meta.json"}
)
_NAMED_CODE_DOC = frozenset({".py", ".md", ".csv", ".xml", ".html", ".js", ".ts", ".java", ".kt"})


def _build_taskmarket_artifacts(payload: dict[str, Any], task: Any | None = None) -> list[dict[str, str]]:
    """Build OpenAPI artifacts from real files. Never invent result.json for media tasks."""
    import base64
    from pathlib import Path

    required_kinds = _required_media_kinds(task, payload)
    artifacts: list[dict[str, str]] = []
    paths: list[str] = []
    for key in ("artifacts", "files", "evidence_files"):
        val = payload.get(key)
        if isinstance(val, list):
            paths.extend(str(x) for x in val if x)
        elif isinstance(val, str) and val:
            paths.append(val)
    # workdir fallback (engine may pass sandbox path when evidence remap lags)
    workdir = payload.get("workdir")
    if workdir:
        wp = Path(str(workdir))
        if wp.is_dir():
            for child in sorted(wp.iterdir()):
                if child.is_file() and child.stat().st_size > 0 and child.name.lower() not in {"meta.json"}:
                    paths.append(str(child))
    evidence = payload.get("evidence")
    if evidence:
        # evidence dir or file — collect concrete files, skip bare directories
        ep = Path(str(evidence))
        if ep.is_file():
            paths.append(str(ep))
        elif ep.is_dir():
            for child in sorted(ep.rglob("*")):
                if child.is_file() and child.stat().st_size > 0 and child.name.lower() != "meta.json":
                    paths.append(str(child))
    seen: set[str] = set()
    for raw in paths:
        p = Path(raw)
        if not p.is_file():
            # Remap basename into evidence/workdir when absolute path went stale
            name = p.name
            for root_key in ("evidence", "workdir"):
                root = payload.get(root_key)
                if not root:
                    continue
                cand = Path(str(root)) / name
                if cand.is_file():
                    p = cand
                    break
            if not p.is_file():
                continue
        # Skip prose-only placeholders when media is required
        if required_kinds and p.name.lower() in _PLACEHOLDER_NAMES:
            continue
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key in seen:
            continue
        seen.add(key)
        data = p.read_bytes()
        if not data or len(data) > 2_000_000:
            continue
        # OpenAPI: fileName + mimeType + file (base64). Keep payload minimal.
        artifacts.append(
            {
                "fileName": p.name[:255],
                "mimeType": _guess_mime(str(p))[:120],
                "file": base64.b64encode(data).decode("ascii"),
            }
        )
        if len(artifacts) >= 20:
            break

    if artifacts:
        if required_kinds and not _artifacts_satisfy_media(artifacts, required_kinds):
            # Hard media ask with only prose → refuse. Named code/docs still ship when
            # the brief also asked for them (e.g. render.py) and media was a false positive.
            named = [
                a
                for a in artifacts
                if a["fileName"].lower() not in _PLACEHOLDER_NAMES
                and Path(a["fileName"]).suffix.lower() in _NAMED_CODE_DOC
            ]
            hard_media = bool(required_kinds & {"image", "gif", "video", "pdf", "apk"})
            if hard_media and not _artifacts_satisfy_media(artifacts, required_kinds & {"image", "gif", "video", "pdf", "apk"}):
                return []
            if named:
                return named
            return []
        return artifacts

    # No real files. Text fallback ONLY for pure text tasks — never for image/gif/video/etc.
    if required_kinds:
        return []

    import json

    content = payload.get("content")
    if content is None:
        content = payload.get("output")
    if content is None:
        content = {"summary": payload.get("summary"), "evidence": payload.get("evidence")}
    if not isinstance(content, (str, bytes)):
        content = json.dumps(content, ensure_ascii=False, indent=2)
    if isinstance(content, str):
        raw_bytes = content.encode("utf-8")
        mime = "application/json" if content.lstrip().startswith(("{", "[")) else "text/plain"
        name = "result.json" if mime == "application/json" else "result.txt"
    else:
        raw_bytes = content
        mime = "application/octet-stream"
        name = "result.bin"
    if not raw_bytes:
        return []
    return [
        {
            "fileName": name,
            "mimeType": mime,
            "role": "final",
            "file": base64.b64encode(raw_bytes).decode("ascii"),
        }
    ]


def _title_from_description(desc: Any) -> str:
    text = str(desc or "").strip().splitlines()
    if not text:
        return "TaskMarket task"
    title = text[0].strip()
    return title[:120] if title else "TaskMarket task"


def _hint_from_tags(tags: list[Any]) -> str:
    joined = " ".join(str(t).lower() for t in tags)
    if any(x in joined for x in ("code", "python", "dev")):
        return "programming"
    if "writ" in joined or "content" in joined:
        return "text"
    if "data" in joined:
        return "json_xml"
    if any(x in joined for x in ("web", "browser", "scrape", "autom")):
        return "browser"
    # Prefer text over dead "other" so PC worker can deliver
    return "text"
