"""Image processing — requires real input image file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from centbot.executors.base import ExecutionResult, Executor


class ImageProcessor(Executor):
    category = "image"

    def execute(self, task: dict[str, Any], workdir: Path) -> ExecutionResult:
        workdir.mkdir(parents=True, exist_ok=True)
        try:
            from PIL import Image, ImageStat
        except ImportError as exc:
            return ExecutionResult(ok=False, category=self.category, error=f"Pillow missing: {exc}")

        src = None
        for name in ("input.png", "input.jpg", "input.jpeg"):
            candidate = workdir / name
            if candidate.exists():
                src = candidate
                break
        if src is None:
            return ExecutionResult(ok=False, category=self.category, error="missing_input:input.png|input.jpg")
        image = Image.open(src)
        gray = image.convert("L")
        stats = ImageStat.Stat(gray)
        thumb = workdir / "thumb.png"
        preview = image.copy()
        preview.thumbnail((128, 128))
        preview.save(thumb)
        meta = {"size": image.size, "mode": image.mode, "mean_luminance": stats.mean[0]}
        meta_path = workdir / "image_meta.json"
        import json

        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        return ExecutionResult(ok=True, category=self.category, output=meta, artifacts=[str(thumb), str(meta_path)])
