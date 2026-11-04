"""Non-automatable task detection — FLAPJAX / NFT buy / own audit page."""

from __future__ import annotations

from centbot.analysis.pipeline import AnalysisPipeline
from centbot.core.logger import ActionJournal
from centbot.quality.automatable import assess_automatable, issues_indicate_non_automatable
from pathlib import Path
import tempfile


def test_flapjax_and_audit_page_not_automatable():
    task = {
        "title": "Earn FLAPJAX",
        "description": (
            "- your own public audit page (a post on your own account, your blog, or your own brand)\n"
            "- FLAPJAX only: 100,000 FLAPJAX on BSC per accepted first-time answer\n"
            "- first-timer slots (agents FlapJax has never paid) first\n"
            "- One payout per operator. We use the same sybil filter\n"
        ),
    }
    a = assess_automatable(task)
    assert a["automatable"] is False
    assert "requires_own_public_page" in a["reasons"] or "requires_token_payout_scheme" in a["reasons"]


def test_nft_buy_not_automatable():
    task = {
        "title": "Sell NFTs",
        "description": (
            "USDC for every NFT you sell. 49 NFTs are live at 1 USDC each.\n"
            "Contract: 0x027d39b6a2EA780b4ae399d96dc35958490E1041 (BNB Smart Chain, chainId 56)\n"
            "Call itemsLength() for the count, and buyable(itemId) to confirm an item is actually buyable.\n"
        ),
    }
    a = assess_automatable(task)
    assert a["automatable"] is False


def test_simple_text_task_is_automatable():
    task = {
        "title": "Summarise three notes",
        "description": "Write one sentence that summarises the delivery delay email notes into plain English.",
    }
    assert assess_automatable(task)["automatable"] is True


def test_analysis_skips_non_automatable():
    td = tempfile.mkdtemp()
    pipe = AnalysisPipeline(
        {
            "min_expected_profit": 0.01,
            "min_reward_probability": 0.01,
            "max_estimated_hours": 8,
            "reject_unfunded": False,
            "reject_untrusted_payer_below": 0.0,
        },
        ActionJournal(Path(td)),
    )
    row = pipe.analyze(
        {
            "id": "1",
            "title": "FLAPJAX bounty",
            "description": "Must include: your own public audit page on your blog. FLAPJAX only payouts.",
            "reward_amount": 5,
            "funded": 1,
            "available": 1,
            "payer_trust": 0.9,
            "claimable": 1,
        }
    )
    assert row["status"] == "skipped"
    assert row.get("reject_reason")


def test_issues_indicate_non_automatable():
    issues = [
        "must_include_unsatisfied:your own public audit page (a post on your own account",
        "no_structural_constraints_extracted",
        "unverified_requirement:FLAPJAX only: 100,000 FLAPJAX on BSC",
    ]
    assert issues_indicate_non_automatable(issues) is True
    assert issues_indicate_non_automatable(["exact_lines_expected_3_got_2"]) is False
