"""Standalone clip tester — no Telegram, no posting.

Run the cutting + editing pipeline on a YouTube URL or a local video file and
write the rendered clips to ./work/clips so you can inspect the look.

Examples
--------
Full auto (Whisper finds the moment, Claude picks the best, then render):
    python clip_cli.py "https://www.youtube.com/watch?v=XXXX"

Fast look-iteration on a known segment (skips Whisper + Claude entirely):
    python clip_cli.py "https://www.youtube.com/watch?v=XXXX" --start 12:30 --end 14:10 --hook "He said WHAT?"

From a local file you already downloaded:
    python clip_cli.py ./myvideo.mp4 --start 0:05 --end 1:30

Only one aspect ratio:
    python clip_cli.py ... --vertical-only
    python clip_cli.py ... --landscape-only
"""
import argparse
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from video import editor

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("clip_cli")


def parse_ts(value: str) -> int:
    """Accept SS, MM:SS, or HH:MM:SS -> total seconds."""
    parts = [int(p) for p in value.split(":")]
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


def resolve_source(src: str) -> Path:
    """Return a local file path: download if it's a URL, else use as-is."""
    if src.startswith("http://") or src.startswith("https://"):
        from video import sources
        log.info("Downloading source video…")
        # extract the id via yt-dlp's own resolution by downloading directly
        out = sources.DOWNLOADS
        out.mkdir(parents=True, exist_ok=True)
        import subprocess
        target = out / "cli_source.mp4"
        cmd = ["yt-dlp", *sources.cookie_args(), "-f",
               "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
               "--merge-output-format", "mp4", "-o", str(target), src]
        if subprocess.run(cmd).returncode != 0 or not target.exists():
            log.error("download failed")
            sys.exit(1)
        return target
    path = Path(src)
    if not path.exists():
        log.error("file not found: %s", src)
        sys.exit(1)
    return path


def auto_pick_from(segments: list) -> dict:
    """Let Claude choose the best moment from already-transcribed segments."""
    from video import transcribe
    from video.clipper import find_clips
    if not segments:
        log.error("no speech found")
        sys.exit(1)
    text = transcribe.to_transcript_text(segments)
    log.info("Asking Claude for the best moment…")
    clips = find_clips(text)
    if not clips:
        log.error("no clip candidates")
        sys.exit(1)
    best = clips[0]
    log.info("Picked %ss-%ss (score %s): %s",
             best["start"], best["end"], best.get("score"), best.get("reason"))
    return best


def main() -> None:
    ap = argparse.ArgumentParser(description="Test clip cutting + editing locally.")
    ap.add_argument("source", help="YouTube URL or local video file")
    ap.add_argument("--start", help="start timestamp (SS|MM:SS|HH:MM:SS)")
    ap.add_argument("--end", help="end timestamp (SS|MM:SS|HH:MM:SS)")
    ap.add_argument("--hook", default=None, help="on-screen banner text")
    ap.add_argument("--handle", default=None, help="watermark handle, e.g. @you")
    ap.add_argument("--captions", action="store_true",
                    help="burn word-by-word karaoke captions (needs Whisper)")
    ap.add_argument("--vertical-only", action="store_true")
    ap.add_argument("--landscape-only", action="store_true")
    args = ap.parse_args()

    path = resolve_source(args.source)

    words = None
    caption = None
    if args.start and args.end:
        start, end = parse_ts(args.start), parse_ts(args.end)
        hook = args.hook
        if args.captions:
            from video import transcribe
            log.info("Transcribing for captions…")
            segs = transcribe.transcribe(path)
            words = transcribe.words_in_range(segs, start, end)
    else:
        log.info("No --start/--end given → using auto (Whisper + Claude).")
        from video import transcribe
        from video.clipper import build_caption, build_ft
        segs = transcribe.transcribe(path)
        best = auto_pick_from(segs)
        start, end = best["start"], best["end"]
        hook = args.hook if args.hook is not None else best.get("hook")
        words = transcribe.words_in_range(segs, start, end)
        caption = build_caption(best)
        ft = build_ft(best)
        if ft:
            caption += f"\n\n{ft}"

    if caption:
        print("\n--- Post caption ---")
        print(caption)

    slug = f"cli_{int(time.time())}"
    log.info("Rendering %ss → %ss (%ss)…", start, end, end - start)
    files = editor.render(
        path, start, end, slug, hook=hook, words=words, handle=args.handle,
        make_vertical=not args.landscape_only,
        make_landscape=not args.vertical_only,
    )
    if not files:
        log.error("render failed")
        sys.exit(1)
    print("\nRendered:")
    for kind, p in files.items():
        print(f"  {kind:10s} {p}")


if __name__ == "__main__":
    main()
