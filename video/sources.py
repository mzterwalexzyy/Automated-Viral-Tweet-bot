"""Download newest videos from watched YouTube channels via yt-dlp.

Keeps a record of already-processed video IDs so we never re-download the same
source twice. Source files land in WORKDIR/downloads and are cleaned up by the
caller once clips are produced.
"""
import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger("xbot.sources")

WORKDIR = Path(__file__).resolve().parent.parent / "work"
DOWNLOADS = WORKDIR / "downloads"
SEEN_FILE = WORKDIR / "seen_videos.json"


def _load_seen() -> set[str]:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    return set()


def _save_seen(seen: set[str]) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(seen)), encoding="utf-8")


def list_recent_video_ids(channel_url: str, limit: int = 5) -> list[str]:
    """Return the newest `limit` video IDs for a channel/playlist URL."""
    cmd = [
        "yt-dlp", "--flat-playlist", "--playlist-end", str(limit),
        "--print", "%(id)s", channel_url,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        log.warning("yt-dlp list failed for %s: %s", channel_url, out.stderr.strip())
        return []
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def download_video(video_id: str) -> Path | None:
    """Download a single video by ID at <=1080p mp4. Returns the file path."""
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(DOWNLOADS / "%(id)s.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
        "--merge-output-format", "mp4",
        "-o", out_tmpl,
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if out.returncode != 0:
        log.warning("download failed for %s: %s", video_id, out.stderr.strip()[-500:])
        return None
    path = DOWNLOADS / f"{video_id}.mp4"
    return path if path.exists() else None


def next_unprocessed(channels: list[str], per_channel: int = 3) -> tuple[str, Path] | None:
    """Find the next un-seen video across channels, download it, mark it seen.

    Returns (video_id, path) or None if nothing new is available.
    """
    seen = _load_seen()
    for channel in channels:
        for vid in list_recent_video_ids(channel, per_channel):
            if vid in seen:
                continue
            seen.add(vid)
            _save_seen(seen)
            path = download_video(vid)
            if path:
                return vid, path
    return None
