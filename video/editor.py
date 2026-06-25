"""Cut a segment from a source video and render share-ready outputs with ffmpeg.

Produces up to two files per clip:
  - 9:16 (1080x1920) for TikTok / X vertical, with a blurred-fill background
  - 16:9 (1920x1080) for X landscape
An optional hook caption is burned across the top.
"""
import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger("xbot.editor")

OUTDIR = Path(__file__).resolve().parent.parent / "work" / "clips"

# drawtext needs an explicit font file (no fontconfig on Windows; Linux needs
# the font installed). Override with FONT_FILE env if needed.
_FONT_CANDIDATES = [
    os.getenv("FONT_FILE", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",      # Ubuntu (fonts-dejavu)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arialbd.ttf",                              # Windows
    "C:/Windows/Fonts/arial.ttf",
]


def _font_file() -> str | None:
    for c in _FONT_CANDIDATES:
        if c and Path(c).exists():
            return c
    return None


def _esc(text: str) -> str:
    """Escape text for ffmpeg drawtext."""
    return (text.replace("\\", "\\\\").replace(":", "\\:")
                .replace("'", "’").replace("%", "\\%"))


def _font_arg() -> str:
    font = _font_file()
    if not font:
        log.warning("no font file found; hook captions disabled")
        return ""
    # escape the Windows drive colon for ffmpeg's filter parser
    return "fontfile='" + font.replace("\\", "/").replace(":", "\\:") + "':"


def _drawtext(hook: str | None, width: int) -> str:
    if not hook:
        return ""
    fontarg = _font_arg()
    if not fontarg:
        return ""
    fontsize = max(28, width // 24)
    return (
        f",drawtext={fontarg}text='{_esc(hook)}':fontcolor=white:fontsize={fontsize}:"
        f"box=1:boxcolor=black@0.55:boxborderw=18:x=(w-text_w)/2:y=h*0.06:"
        f"line_spacing=8"
    )


def _run(cmd: list[str]) -> bool:
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if out.returncode != 0:
        log.error("ffmpeg failed: %s", out.stderr.strip()[-600:])
        return False
    return True


def render(src: Path, start: int, end: int, slug: str, hook: str | None = None,
           make_vertical: bool = True, make_landscape: bool = True) -> dict:
    """Render requested aspect ratios. Returns {"vertical": Path, "landscape": Path}."""
    OUTDIR.mkdir(parents=True, exist_ok=True)
    dur = max(1, end - start)
    results: dict[str, Path] = {}

    if make_vertical:
        out = OUTDIR / f"{slug}_9x16.mp4"
        vf = (
            "split[a][b];"
            "[a]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=40[bg];"
            "[b]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2"
        ) + _drawtext(hook, 1080)
        cmd = ["ffmpeg", "-y", "-ss", str(start), "-t", str(dur), "-i", str(src),
               "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
               "-c:a", "aac", "-b:a", "128k", str(out)]
        if _run(cmd):
            results["vertical"] = out

    if make_landscape:
        out = OUTDIR / f"{slug}_16x9.mp4"
        vf = ("scale=1920:1080:force_original_aspect_ratio=decrease,"
              "pad=1920:1080:(ow-iw)/2:(oh-ih)/2") + _drawtext(hook, 1920)
        cmd = ["ffmpeg", "-y", "-ss", str(start), "-t", str(dur), "-i", str(src),
               "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
               "-c:a", "aac", "-b:a", "128k", str(out)]
        if _run(cmd):
            results["landscape"] = out

    return results
