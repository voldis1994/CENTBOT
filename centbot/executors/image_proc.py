"""Image / GIF / short-video processing and generation with available tools (Pillow)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from centbot.executors.base import ExecutionResult, Executor
from centbot.quality.task_intent import is_create_output_task, missing_input_error


class ImageProcessor(Executor):
    category = "image"

    def execute(self, task: dict[str, Any], workdir: Path) -> ExecutionResult:
        workdir.mkdir(parents=True, exist_ok=True)
        try:
            from PIL import Image, ImageDraw, ImageFont, ImageStat
        except ImportError as exc:
            return ExecutionResult(ok=False, category=self.category, error=f"Pillow missing: {exc}")

        from centbot.quality.deliverables import named_deliverables, needs_photorealistic_media

        title = str(task.get("title") or "")
        description = str(task.get("description") or "")
        blob = f"{title}\n{description}"
        wants_gif = bool(re.search(r"\bgif\b|\.gif\b|animated", blob, re.I))
        wants_video = bool(re.search(r"\bvideo\b|\.mp4\b|\.webm\b|short clip", blob, re.I))
        create = is_create_output_task(task, extensions=(".png", ".jpg", ".jpeg", ".gif", ".mp4", ".webm"))

        if needs_photorealistic_media(task):
            return ExecutionResult(
                ok=False,
                category=self.category,
                error="generic_cannot_produce:photorealistic_media",
                output={"reason": "requires_photorealistic_media"},
            )

        src = None
        for name in ("input.png", "input.jpg", "input.jpeg", "input.gif"):
            candidate = workdir / name
            if candidate.exists():
                src = candidate
                break

        if src is None and not create:
            return ExecutionResult(
                ok=False,
                category=self.category,
                error=missing_input_error(["input.png", "input.jpg"], create_allowed=False),
            )

        artifacts: list[str] = []
        meta: dict[str, Any] = {"mode": "transform" if src else "generate"}
        preferred_names = [
            n for n in named_deliverables(task) if Path(n).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        ]

        if src is not None:
            image = Image.open(src)
            gray = image.convert("L")
            stats = ImageStat.Stat(gray)
            thumb = workdir / "thumb.png"
            preview = image.copy()
            preview.thumbnail((128, 128))
            preview.save(thumb)
            artifacts.append(str(thumb))
            meta.update({"size": image.size, "mode_img": image.mode, "mean_luminance": stats.mean[0], "source": src.name})
            base = image.convert("RGBA")
        else:
            base = _generate_canvas(title or "CENTBOT", description, Image, ImageDraw, ImageFont)
            out_name = preferred_names[0] if preferred_names else "output.png"
            out_png = workdir / out_name
            if out_png.suffix.lower() in {".jpg", ".jpeg"}:
                base.convert("RGB").save(out_png, quality=90)
            else:
                base.convert("RGB").save(out_png)
            artifacts.append(str(out_png))
            # Also keep canonical output.png for downstream tooling
            if out_png.name.lower() != "output.png":
                canon = workdir / "output.png"
                base.convert("RGB").save(canon)
                artifacts.append(str(canon))
            meta.update({"size": base.size, "generated": True, "primary": out_png.name})

        if wants_gif or (create and "gif" in blob.lower()):
            gif_path = workdir / "output.gif"
            frames = _gif_frames(base, Image, ImageDraw)
            frames[0].save(
                gif_path,
                save_all=True,
                append_images=frames[1:],
                duration=120,
                loop=0,
                format="GIF",
            )
            artifacts.append(str(gif_path))
            meta["gif"] = gif_path.name

        if wants_video:
            # Without ffmpeg, emit an animated GIF as the short-video stand-in and a note
            vid_note = workdir / "video_note.txt"
            fallback = workdir / "output_clip.gif"
            if "gif" not in meta:
                frames = _gif_frames(base, Image, ImageDraw)
                frames[0].save(
                    fallback,
                    save_all=True,
                    append_images=frames[1:],
                    duration=80,
                    loop=0,
                    format="GIF",
                )
                artifacts.append(str(fallback))
            vid_note.write_text(
                "Short video requested. Host has no ffmpeg guarantee — delivered animated GIF frames as preview. "
                "Install ffmpeg on Windows for true MP4 export.",
                encoding="utf-8",
            )
            artifacts.append(str(vid_note))
            meta["video_fallback"] = "gif"

        meta_path = workdir / "image_meta.json"
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        artifacts.append(str(meta_path))
        return ExecutionResult(ok=True, category=self.category, output=meta, artifacts=artifacts)


def _generate_canvas(title: str, description: str, Image, ImageDraw, ImageFont):
    img = Image.new("RGBA", (768, 512), (18, 28, 40, 255))
    draw = ImageDraw.Draw(img)
    # Atmosphere: soft gradient bars (no flat single fill)
    for y in range(512):
        tone = 18 + int(40 * (y / 512))
        draw.line([(0, y), (768, y)], fill=(tone, tone + 8, tone + 18, 255))
    try:
        font = ImageFont.load_default()
    except Exception:  # noqa: BLE001
        font = None
    draw.rectangle([(32, 32), (736, 480)], outline=(120, 180, 210, 220), width=2)
    draw.text((48, 60), (title or "CENTBOT")[:48], fill=(232, 241, 248, 255), font=font)
    draw.text((48, 120), (description or "")[:180], fill=(180, 200, 214, 255), font=font)
    draw.text((48, 440), "CENTBOT", fill=(93, 206, 164, 255), font=font)
    return img


def _gif_frames(base, Image, ImageDraw):
    frames = []
    for i in range(8):
        frame = base.copy().convert("RGBA")
        overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        x = 40 + i * 40
        d.ellipse([(x, 200), (x + 60, 260)], fill=(93, 206, 164, 180))
        frames.append(Image.alpha_composite(frame, overlay).convert("P", palette=Image.ADAPTIVE))
    return frames
