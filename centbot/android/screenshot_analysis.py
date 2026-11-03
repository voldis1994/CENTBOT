"""Android screenshot analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def analyze_screenshot(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {"ok": False, "error": "missing_file"}
    try:
        from PIL import Image, ImageStat

        img = Image.open(path)
        gray = img.convert("L")
        stats = ImageStat.Stat(gray)
        # Simple heuristics: brightness and edge-ish variance
        return {
            "ok": True,
            "size": img.size,
            "mean_luminance": stats.mean[0],
            "variance": stats.var[0],
            "likely_blank": stats.var[0] < 50,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
