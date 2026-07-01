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


def make_clips(channels: list[str] | None = None,
               style_examples: list[str] | None = None,
               handle: str | None = None) -> list[dict]:
    """Produce clip jobs for a fresh source video. Quality-gated, not a fixed
    count: a video with several strong moments yields several rendered clips,
    one with only one worth cutting yields one. Empty list if nothing new /
    no candidate clears the bar."""
    channels = channels or DEFAULT_CHANNELS
    picked = sources.next_unprocessed(channels)
    if not picked:
        log.info("no new source videos")
        return []
    video_id, src_path = picked
    try:
        segments = transcribe.transcribe(src_path)
        if not segments:
            return []
        transcript = transcribe.to_transcript_text(segments)
        max_duration = max((s["end"] for s in segments), default=None)
        clips = find_clips(transcript, segments, style_examples=style_examples,
                           max_duration=max_duration)
        if not clips:
            log.info("no clip candidates in %s", video_id)
            return []
        jobs = []
        for i, clip in enumerate(clips):
            slug = f"{video_id}_{int(time.time())}_{i}"
            words = transcribe.words_in_range(segments, clip["start"], clip["end"])
            files = editor.render(
                src_path, clip["start"], clip["end"], slug,
                hook=clip.get("hook"), words=words, handle=handle)
            if not files:
                continue
            jobs.append({
                "video_id": video_id,
                "score": clip.get("score"),
                "hook": clip.get("hook", ""),
                "intro": clip.get("intro", ""),
                "summary": clip.get("summary", ""),
                "dialogue": clip.get("dialogue", []),
                "handles": clip.get("handles", []),
                "reason": clip.get("reason", ""),
                "start": clip["start"],
                "end": clip["end"],
                "files": {k: str(v) for k, v in files.items()},
            })
        return jobs
    finally:
        # source file is large; drop it once clips are rendered
        try:
            Path(src_path).unlink(missing_ok=True)
        except OSError:
            pass
