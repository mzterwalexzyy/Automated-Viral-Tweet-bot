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
    segments, _info = _model().transcribe(str(path), vad_filter=True)
    out = []
    for s in segments:
        out.append({"start": round(s.start, 2), "end": round(s.end, 2),
                    "text": s.text.strip()})
    log.info("transcribed %s into %d segments", path.name, len(out))
    return out


def to_transcript_text(segments: list[dict]) -> str:
    """Flatten segments into '[mm:ss] text' lines for the LLM to scan."""
    lines = []
    for s in segments:
        m, sec = divmod(int(s["start"]), 60)
        lines.append(f"[{m:02d}:{sec:02d}] {s['text']}")
    return "\n".join(lines)
