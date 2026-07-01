"""Local speech-to-text with faster-whisper (CPU, ARM-friendly).

Produces a list of timestamped segments: [{"start": float, "end": float,
"text": str}, ...]. The model is loaded once and cached.
"""
import logging
import os
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("xbot.transcribe")

# base is a good speed/quality tradeoff on free-tier CPU; override via env.
MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")


@lru_cache(maxsize=1)
def _model():
    from faster_whisper import WhisperModel
    log.info("loading whisper model %s", MODEL_SIZE)
    return WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")


def transcribe(path: Path) -> list[dict]:
    """Transcribe with word-level timestamps.

    Returns segments: [{"start", "end", "text",
                        "words": [{"start", "end", "word"}, ...]}, ...]
    """
    # vad_filter=True is known to drift segment timestamps out of sync with
    # the real file timeline on some faster-whisper versions (silence removal
    # shifts the reported clock). Since we cut the source file using these
    # exact timestamps, drift = wrong footage gets clipped. Keep it off.
    segments, _info = _model().transcribe(
        str(path), vad_filter=False, word_timestamps=True)
    out = []
    for s in segments:
        words = [{"start": round(w.start, 2), "end": round(w.end, 2),
                  "word": w.word} for w in (s.words or [])]
        out.append({"start": round(s.start, 2), "end": round(s.end, 2),
                    "text": s.text.strip(), "words": words})
    log.info("transcribed %s into %d segments", path.name, len(out))
    return out


def words_in_range(segments: list[dict], start: float, end: float) -> list[dict]:
    """Return word dicts within [start, end], with times rebased to the clip
    (i.e. clip-relative seconds)."""
    out = []
    for s in segments:
        for w in s.get("words", []):
            if w["end"] <= start or w["start"] >= end:
                continue
            out.append({
                "start": max(0.0, round(w["start"] - start, 2)),
                "end": round(min(w["end"], end) - start, 2),
                "word": w["word"].strip(),
            })
    return out


def to_transcript_text(segments: list[dict]) -> str:
    """Flatten segments into '[mm:ss] text' lines for the LLM to scan."""
    lines = []
    for s in segments:
        m, sec = divmod(int(s["start"]), 60)
        lines.append(f"[{m:02d}:{sec:02d}] {s['text']}")
    return "\n".join(lines)
