"""Detect tasks that require human identity, purchases, or off-platform proof CENTBOT cannot satisfy."""

from __future__ import annotations

import re
from typing import Any


# Patterns that mean "do not auto-accept / do not burn cycles repairing"
_NON_AUTO_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "requires_own_public_page",
        re.compile(
            r"your own (public )?(audit )?page|own (blog|account|website)|post on your own",
            re.I,
        ),
    ),
    (
        "requires_token_payout_scheme",
        re.compile(
            r"\bFLAPJAX\b|\bper accepted first-time\b|first-timer slots|sybil filter|one payout per operator",
            re.I,
        ),
    ),
    (
        "requires_nft_purchase",
        re.compile(
            r"\bbuy(able)?\b.*\bnft\b|\bnft\b.*\b(buy|purchase|mint)\b|itemsLength\(\)|USDC for every NFT you sell",
            re.I,
        ),
    ),
    (
        "requires_onchain_buy",
        re.compile(
            r"BNB Smart Chain|chainid\s*56|call\s+\w+\(\).*confirm|0x[a-fA-F0-9]{40}.*(buy|mint|purchase)",
            re.I,
        ),
    ),
    (
        "requires_referral_spam",
        re.compile(
            r"per referral|help agents discover|earn \d+(\.\d+)?\s*USDC per referral",
            re.I,
        ),
    ),
    (
        "requires_human_social_proof",
        re.compile(
            r"twitter\.com|x\.com/|linkedin\.com|instagram\.com|tiktok\.com|"
            r"screenshot of your (profile|account)|verify your identity on",
            re.I,
        ),
    ),
]


def assess_automatable(task: dict[str, Any]) -> dict[str, Any]:
    """Return whether CENTBOT can honestly auto-complete this brief."""
    parts = [
        str(task.get("title") or ""),
        str(task.get("description") or ""),
    ]
    raw = task.get("raw_json") or task.get("raw") or {}
    if isinstance(raw, str):
        parts.append(raw[:8000])
    elif isinstance(raw, dict):
        nested = raw.get("task") or raw.get("job") or {}
        if isinstance(nested, dict):
            parts.append(str(nested.get("description") or ""))
            parts.append(str(nested.get("title") or ""))
        parts.append(str(raw.get("skip_reason") or ""))
    blob = "\n".join(parts)
    hits: list[str] = []
    for code, pat in _NON_AUTO_PATTERNS:
        if pat.search(blob):
            hits.append(code)
    return {
        "automatable": not hits,
        "reasons": hits,
        "primary_reason": hits[0] if hits else None,
    }


def issues_indicate_non_automatable(issues: list[Any] | str | None) -> bool:
    """True when requirement-check failures are the non-automatable class (not fixable by repair)."""
    if issues is None:
        return False
    if isinstance(issues, str):
        text = issues
    else:
        text = " ".join(str(x) for x in issues)
    text_l = text.lower()
    markers = (
        "must_include_unsatisfied:your own public",
        "unverified_requirement:flapjax",
        "unverified_requirement:usdc for every nft",
        "unverified_requirement:contract: 0x",
        "unverified_requirement:call itemslength",
        "unverified_requirement:first-timer",
        "unverified_requirement:one payout per operator",
        "requires_own_public_page",
        "requires_nft_purchase",
        "requires_token_payout",
        # Binary/file inputs that were never downloaded — retry won't create them
        "missing_input:input.png",
        "missing_input:input.jpg",
        "missing_input:input.jpeg",
        "missing_input:input.csv",
        "missing_input:input.xlsx",
        "missing_input:input.pdf",
        "missing_input:input.json",
        "missing_input:input.xml",
        "missing_input:browser_steps",
        "missing_input_not_repairable",
        "generic_cannot_produce:",
    )
    return any(m in text_l for m in markers)
