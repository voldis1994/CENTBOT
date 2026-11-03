"""Image processing module."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from centbot.executors.base import ExecutionResult, Executor


class ImageProcessor(Executor):
    category = "image"

    def execute(self, task: dict[str, Any], workdir: Path) -> ExecutionResult:
        workdir.mkdir(parents=True, exist_ok=True)
        try:
            from PIL import Image, ImageDraw, ImageStat
        except ImportError as exc:
            return ExecutionResult(ok=False, category=self.category, error=f"Pillow missing: {exc}")

        src = workdir / "input.png"
        if not src.exists():
            img = Image.new("RGB", (320, 200), color=(30, 60, 90))
            draw = ImageDraw.Draw(img)
            draw.rectangle((40, 40, 280, 160), outline=(220, 220, 220), width=3)
            draw.text((90, 90), "CENTBOT", fill=(255, 255, 255))
            img.save(src)
        image = Image.open(src)
        gray = image.convert("L")
        stats = ImageStat.Stat(gray)
        thumb = workdir / "thumb.png"
        image.copy().thumbnail((128, 128))
        image.save(thumb)
        meta = {"size": image.size, "mode": image.mode, "mean_luminance": stats.mean[0]}
        (workdir / "image_meta.json").write_text(__import__("json").dumps(meta), encoding="utf-8")
        return ExecutionResult(ok=True, category=self.category, output=meta, artifacts=[str(thumb), str(workdir / "image_meta.json")])
