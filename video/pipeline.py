"""End-to-end: pick a fresh source video, transcribe, find the best clip,
render it for X (16:9) and TikTok/X (9:16). Returns a clip job dict.

Designed to be called from a background thread (it's all blocking work).
"""
import logging
import time
from pathlib import Path

from . import editor, sources, transcribe
from .clipper import find_clips

log = logging.getLogger("xbot.pipeline")

# Channel handles/URLs to source from. Plain handles resolve to /videos.
DEFAULT_CHANNELS = [
    "https://www.youtube.com/@TheRamseyShow/videos",
    "https://www.youtube.com/@PBDPodcast/videos",
    "https://www.youtube.com/@CalebHammer/videos",
    "https://www.youtube.com/@TheDiaryOfACEO/videos",
    "https://www.youtube.com/@joerogan/videos",
    "https://www.youtube.com/@kevinolearytv/videos",
    "https://www.youtube.com/@stephenasmith/videos",
]


def make_clip(channels: list[str] | None = None,
              style_examples: list[str] | None = None) -> dict | None:
    """Produce one clip job. Returns:
       {"video_id", "score", "hook", "caption", "reason",
        "start", "end", "files": {"vertical": path, "landscape": path}}
    or None if nothing new / no good moment was found.
    """
    channels = channels or DEFAULT_CHANNELS
    picked = sources.next_unprocessed(channels)
    if not picked:
        log.info("no new source videos")
        return None
    video_id, src_path = picked
    try:
        segments = transcribe.transcribe(src_path)
        if not segments:
            return None
        transcript = transcribe.to_transcript_text(segments)
        clips = find_clips(transcript, style_examples=style_examples)
        if not clips:
            log.info("no clip candidates in %s", video_id)
            return None
        best = clips[0]
        slug = f"{video_id}_{int(time.time())}"
        files = editor.render(
            src_path, best["start"], best["end"], slug,
            hook=best.get("hook"))
        if not files:
            return None
        return {
            "video_id": video_id,
            "score": best.get("score"),
            "hook": best.get("hook", ""),
            "caption": best.get("caption", ""),
            "reason": best.get("reason", ""),
            "start": best["start"],
            "end": best["end"],
            "files": {k: str(v) for k, v in files.items()},
        }
    finally:
        # source file is large; drop it once clips are rendered
        try:
            Path(src_path).unlink(missing_ok=True)
        except OSError:
            pass
