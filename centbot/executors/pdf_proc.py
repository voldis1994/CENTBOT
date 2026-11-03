"""PDF processing module."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from centbot.executors.base import ExecutionResult, Executor


class PDFProcessor(Executor):
    category = "pdf"

    def execute(self, task: dict[str, Any], workdir: Path) -> ExecutionResult:
        workdir.mkdir(parents=True, exist_ok=True)
        src = workdir / "input.pdf"
        text = ""
        if src.exists():
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(src))
                text = "\n".join((page.extract_text() or "") for page in reader.pages)
            except Exception as exc:  # noqa: BLE001
                return ExecutionResult(ok=False, category=self.category, error=str(exc))
        else:
            text = "DEMO PDF TEXT\nVendor: Acme\nDate: 2026-01-01\nTotal: 42.00"
            (workdir / "input.pdf.txt").write_text(text, encoding="utf-8")
        out = workdir / "extracted.txt"
        out.write_text(text, encoding="utf-8")
        fields = {}
        for line in text.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fields[k.strip().lower()] = v.strip()
        return ExecutionResult(ok=True, category=self.category, output={"fields": fields, "chars": len(text)}, artifacts=[str(out)])
