"""AI analysis/planning, auth sessions, TaskMarket artifacts, auto_accept, intent."""

from __future__ import annotations

import base64
from pathlib import Path

from centbot.ai.analyzer import AITaskAnalyzer
from centbot.ai.planner import AIWorkPlanner
from centbot.analysis.pipeline import categorize
from centbot.core.consistency import audit_config
from centbot.core.config import Config
from centbot.executors.generic import GenericExecutor
from centbot.executors.image_proc import ImageProcessor
from centbot.executors.json_xml_proc import JsonXmlProcessor
from centbot.platforms.session_manager import PlatformSessionManager
from centbot.platforms.taskmarket import _build_taskmarket_artifacts
from centbot.quality.task_intent import is_create_output_task, missing_input_error


class _FakeOllama:
    def generate(self, prompt: str):
        return {"ok": False, "error": "disabled"}


def test_analyzer_extracts_goal_and_files():
    az = AITaskAnalyzer(_FakeOllama(), enabled=False)
    out = az.analyze(
        {
            "title": "Build report",
            "description": "Create output.json from sales.\nAcceptance: valid JSON file delivered.",
            "funded": True,
            "category": "json_xml",
        }
    )
    assert out["goal"]
    assert out["create_vs_transform"] in {"create", "transform"}
    assert out["steps"]


def test_planner_structured_steps_for_executors():
    planner = AIWorkPlanner(AITaskAnalyzer(_FakeOllama(), enabled=False))
    plan = planner.plan({"id": "1", "title": "x", "description": "implement a function", "category": "programming"})
    assert plan["steps"]
    assert all("action" in s for s in plan["steps"])
    assert any(s["name"] == "submit" for s in plan["steps"])


def test_categorize_by_content_not_only_keywords():
    assert categorize("Help", "Please implement a function with unit tests\n```python\ndef f():\n  pass\n```") == "programming"
    assert categorize("Media", "Create an animated gif banner for the launch") == "image"
    assert categorize("Mobile", "Install the apk and run espresso checks on android emulator") == "android"
    assert categorize("Sheet", "Clean the attached customers.csv file") == "csv"


def test_generic_refuses_media_summary_as_done(tmp_path: Path):
    ex = GenericExecutor()
    result = ex.execute(
        {"title": "Logo", "description": "Create a PNG logo for the brand", "category": "other"},
        tmp_path,
    )
    assert result.ok is False
    assert "generic_cannot_produce" in (result.error or "")


def test_image_generate_when_create_task(tmp_path: Path):
    ex = ImageProcessor()
    result = ex.execute(
        {"title": "Banner", "description": "Create a PNG banner for the campaign", "category": "image"},
        tmp_path,
    )
    assert result.ok is True
    assert any(Path(a).suffix == ".png" for a in result.artifacts)


def test_json_create_vs_missing_input(tmp_path: Path):
    ex = JsonXmlProcessor()
    miss = ex.execute({"title": "Transform", "description": "Convert the attached input.json"}, tmp_path)
    assert miss.ok is False
    assert miss.error and miss.error.startswith("missing_input:")
    create = ex.execute({"title": "Schema", "description": "Create a JSON config file for the bot"}, tmp_path)
    assert create.ok is True


def test_task_intent_helpers():
    assert is_create_output_task({"title": "Create logo", "description": "Generate a PNG"})
    assert not is_create_output_task({"title": "Clean", "description": "Process the attached input.png"})
    assert missing_input_error(["input.png"]).startswith("missing_input:")


def test_taskmarket_artifacts_base64(tmp_path: Path):
    f = tmp_path / "result.txt"
    f.write_text("hello deliverable", encoding="utf-8")
    arts = _build_taskmarket_artifacts({"artifacts": [str(f)]})
    assert len(arts) == 1
    assert arts[0]["fileName"] == "result.txt"
    assert arts[0]["mimeType"]
    assert base64.b64decode(arts[0]["file"]) == b"hello deliverable"


def test_taskmarket_artifacts_fallback_content():
    arts = _build_taskmarket_artifacts({"output": {"summary": "done"}})
    assert arts and arts[0]["fileName"] in {"result.json", "result.txt"}


def test_taskmarket_refuses_text_fallback_for_media_tasks():
    from centbot.platforms.base import PlatformTask

    task = PlatformTask(
        platform="taskmarket",
        external_id="tm-1",
        title="Create logo",
        description="Generate a PNG banner and animated GIF for the launch",
        reward_amount=5.0,
        reward_currency="USDC",
    )
    # Summary-only payload must not become result.json
    arts = _build_taskmarket_artifacts(
        {"output": {"short_summary": "nice logo"}, "summary": "CENTBOT completed Create logo"},
        task=task,
    )
    assert arts == []
    # Real PNG is accepted
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        png = Path(td) / "output.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        gif = Path(td) / "output.gif"
        gif.write_bytes(b"GIF89a" + b"\x00" * 16)
        arts2 = _build_taskmarket_artifacts({"artifacts": [str(png), str(gif)]}, task=task)
        assert len(arts2) == 2
        assert {a["fileName"] for a in arts2} == {"output.png", "output.gif"}


def test_taskmarket_packs_render_py_from_evidence(tmp_path: Path):
    """Live bug: deliverables-created then artifacts_required — evidence must ship."""
    from centbot.platforms.base import PlatformTask

    ev = tmp_path / "evidence"
    ev.mkdir()
    py = ev / "render.py"
    py.write_text("def render():\n    return {'ok': True}\n", encoding="utf-8")
    (ev / "meta.json").write_text("{}", encoding="utf-8")
    task = PlatformTask(
        platform="taskmarket",
        external_id="tm-render",
        title="Renderer",
        description="Write a python file named render.py that exposes render().",
        reward_amount=1.0,
        reward_currency="USDC",
    )
    arts = _build_taskmarket_artifacts(
        {"evidence": str(ev), "summary": "CENTBOT completed Renderer", "output": {"ok": True}},
        task=task,
    )
    assert arts
    assert any(a["fileName"] == "render.py" for a in arts)
    assert "role" not in arts[0]


def test_taskmarket_docker_image_word_does_not_block_code(tmp_path: Path):
    from centbot.platforms.base import PlatformTask

    f = tmp_path / "solution.py"
    f.write_text("def add(a,b): return a+b\n", encoding="utf-8")
    task = PlatformTask(
        platform="taskmarket",
        external_id="tm-code",
        title="Build helper",
        description="Create solution.py. Mentions docker image only as environment note.",
        reward_amount=1.0,
        reward_currency="USDC",
    )
    arts = _build_taskmarket_artifacts({"artifacts": [str(f)]}, task=task)
    assert len(arts) == 1
    assert arts[0]["fileName"] == "solution.py"


def test_collect_submit_artifacts_prefers_evidence(tmp_path: Path):
    from centbot.core.engine import _collect_submit_artifacts

    wd = tmp_path / "work"
    ev = tmp_path / "ev"
    wd.mkdir()
    ev.mkdir()
    (wd / "faq.md").write_text("# FAQ\n", encoding="utf-8")
    (ev / "faq.md").write_text("# FAQ evidence\n", encoding="utf-8")
    (ev / "meta.json").write_text("{}", encoding="utf-8")
    paths = _collect_submit_artifacts({"artifacts": [str(wd / "faq.md")]}, wd, ev)
    assert any(Path(p).name == "faq.md" and Path(p).parent == ev for p in paths)
    assert not any(Path(p).name == "meta.json" for p in paths)


def test_auto_accept_false_not_forced_in_consistency(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CENTBOT_ROOT", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config" / "default.yaml").write_text(
        "system: {mode: live}\nanalysis: {auto_accept: false}\nandroid: {enabled: false, max_emulators: 0}\n"
        "finance: {simulate_rewards_in_dry_run: false, crypto_wallet_public: '0x' + '11'*20}\n".replace(
            "'0x' + '11'*20", "0x" + "11" * 20
        ),
        encoding="utf-8",
    )
    cfg = Config(path=tmp_path / "config" / "default.yaml")
    report = audit_config(cfg)
    assert report["flags"]["auto_accept"] is False
    assert any("auto_accept_false" in w for w in report["warnings"])
    assert not any("force_true" in w for w in report["warnings"])


def test_session_manager_dns_backoff():
    class Conn:
        def health(self):
            return {"live": False, "error": "Failed to resolve 'api.bountybook.ai' ([Errno 11001])"}

    mgr = PlatformSessionManager({"bountybook": Conn()})
    out = mgr.ensure_session("bountybook", Conn())
    assert out.get("error") == "platform_offline_dns"
    assert mgr.is_in_backoff("bountybook")


def test_session_manager_taskmarket_wallet_only():
    class Wallet:
        address = "0xabc"

    class Conn:
        wallet = Wallet()

        def register_account(self, payload):
            return {"ok": True, "status": "registered"}

        def health(self):
            return {"live": True}

    mgr = PlatformSessionManager({"taskmarket": Conn()})
    out = mgr.ensure_session("taskmarket", Conn())
    assert out.get("ok") is True
    assert out.get("auth") == "eip191_wallet"


def test_start_with_emulators_wins_over_skip(monkeypatch):
    import sys

    from centbot.windows import start as start_mod

    captured = {}

    def fake_full_start(*, skip_emulators=False):
        captured["skip"] = skip_emulators
        return {"ok": True, "engine": {"ok": True}}

    monkeypatch.setattr(start_mod, "full_start", fake_full_start)
    monkeypatch.setattr(start_mod, "setup_incomplete", lambda: False)
    monkeypatch.setenv("CENTBOT_START_EMULATORS", "1")
    monkeypatch.setattr(sys, "argv", ["centbot.windows.start", "--skip-emulators"])
    assert start_mod.main() == 0
    assert captured["skip"] is False
