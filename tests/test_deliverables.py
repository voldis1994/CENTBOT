"""Named deliverable creation + AI-on defaults for LIVE create tasks."""

from __future__ import annotations

from pathlib import Path

from centbot.ai.analyzer import AITaskAnalyzer
from centbot.executors.image_proc import ImageProcessor
from centbot.executors.text_proc import TextProcessor
from centbot.quality.automatable import assess_automatable, issues_indicate_non_automatable
from centbot.quality.deliverables import (
    ensure_named_deliverables,
    named_deliverables,
    needs_photorealistic_media,
)
from centbot.quality.requirements import verify_against_requirements
from centbot.windows.wizard import build_local_yaml


class _FakeOllama:
    def generate(self, prompt: str):
        return {"ok": False, "error": "ollama_unavailable"}

    def available(self):
        return False


def test_named_deliverables_extracts_faq_and_render():
    task = {
        "title": "Docs",
        "description": "Create faq.md and also ship render.py for the preview.",
    }
    names = named_deliverables(task)
    assert "faq.md" in names
    assert "render.py" in names


def test_ensure_creates_faq_md(tmp_path: Path):
    task = {
        "title": "Product FAQ",
        "description": (
            "Create one markdown file named faq.md containing exactly 5 "
            "question-and-answer pairs about the product."
        ),
        "category": "text",
    }
    out = ensure_named_deliverables(task, tmp_path, {"ok": True, "artifacts": []})
    assert out["ok"] is True
    assert "faq.md" in out["created"]
    text = (tmp_path / "faq.md").read_text(encoding="utf-8")
    assert text.count("## ") >= 5
    report = verify_against_requirements(
        task,
        {"ok": True, "artifacts": [str(tmp_path / "faq.md")], "output": {}},
        tmp_path,
    )
    assert not any(i.startswith("required_file_missing:faq.md") for i in report["issues"])
    assert not any(i.startswith("must_include_unsatisfied") for i in report["issues"] if "faq.md" in i)


def test_ensure_creates_render_py(tmp_path: Path):
    task = {
        "title": "Renderer",
        "description": "Write a python file named render.py that exposes a render() helper.",
        "category": "programming",
    }
    out = ensure_named_deliverables(task, tmp_path, {"ok": False, "artifacts": [], "error": "codegen_failed"})
    assert "render.py" in out["created"]
    src = (tmp_path / "render.py").read_text(encoding="utf-8")
    assert "def render" in src


def test_text_processor_writes_faq(tmp_path: Path):
    ex = TextProcessor()
    result = ex.execute(
        {
            "title": "Help center",
            "description": "Please create faq.md with exactly 5 Q&A pairs for onboarding.",
            "category": "text",
        },
        tmp_path,
    )
    assert result.ok
    assert (tmp_path / "faq.md").exists()
    assert any(Path(a).name == "faq.md" for a in result.artifacts)


def test_photobooth_soft_skipped():
    task = {
        "title": "Create a vintage photobooth photo strip",
        "description": (
            "Deliver photobooth-strip.png with exactly 4 photos in a single vertical strip, "
            "at least 600 pixels wide and 2400 pixels tall, showing one person or character."
        ),
        "category": "image",
    }
    assert needs_photorealistic_media(task) is True
    assess = assess_automatable(task)
    assert assess["automatable"] is False
    assert assess["primary_reason"] == "requires_photorealistic_media"
    assert issues_indicate_non_automatable("generic_cannot_produce:photorealistic_media")


def test_image_processor_refuses_photobooth(tmp_path: Path):
    ex = ImageProcessor()
    result = ex.execute(
        {
            "title": "Photobooth",
            "description": "Create photobooth-strip.png with exactly 4 photos of one person.",
            "category": "image",
        },
        tmp_path,
    )
    assert result.ok is False
    assert "photorealistic" in (result.error or "")


def test_analyzer_enabled_falls_back_to_heuristic():
    az = AITaskAnalyzer(_FakeOllama(), enabled=True)
    out = az.analyze({"title": "Build FAQ", "description": "Create faq.md", "funded": True})
    assert out["ok"] is True
    assert out["mode"] == "heuristic"
    assert out.get("ai_error") == "ollama_unavailable"


def test_wizard_enables_ai_by_default():
    data = build_local_yaml(
        {
            "mode": "live",
            "full_name": "A B",
            "iban": "LV97HABA0012345678910",
            "crypto_wallet": "0x" + "cd" * 20,
        }
    )
    assert data["ai"]["enabled"] is True
