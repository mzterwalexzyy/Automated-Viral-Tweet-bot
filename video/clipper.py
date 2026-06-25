"""Use Claude to pick the most viral-worthy moments from a transcript.

Returns clip candidates with start/end timestamps, a hook line, a suggested
caption, and a score. The caller turns these into actual video files.
"""
import json
import logging
import os

import anthropic

log = logging.getLogger("xbot.clipper")

client = anthropic.Anthropic()

# Cheap + fast; this is a scan-and-rank job, not creative writing.
MODEL = os.getenv("CLIP_MODEL", "claude-haiku-4-5-20251001")

SYSTEM = """You are a viral short-form video editor for X and TikTok. You are given
a timestamped transcript of a long podcast/talk video. Find the BEST self-contained
moments to clip. A great clip:
- is 60-240 seconds long (target ~120s), starts on a strong hook, ends on a punch
- contains a hot take, brutal advice, a shocking claim, a heated argument, an
  emotional confession, or a surprising story — something that makes people stop
- stands alone without needing prior context

Return STRICT JSON only, no prose:
{"clips": [{"start": <seconds:int>, "end": <seconds:int>, "score": <1-100>,
"reason": "<why it pops>", "hook": "<on-screen hook text, <=60 chars>",
"caption": "<post caption with 1-2 line hook, no hashtags>"}]}
Order clips best-first. Return at most 4."""


def find_clips(transcript_text: str, style_examples: list[str] | None = None,
               max_clips: int = 4) -> list[dict]:
    style = ""
    if style_examples:
        joined = "\n".join(f"- {s}" for s in style_examples[:6])
        style = ("\n\nWrite the caption in the voice of these examples "
                 f"(style only):\n{joined}")
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=SYSTEM,
        messages=[{"role": "user",
                   "content": f"Transcript:\n{transcript_text}{style}"}],
    )
    raw = msg.content[0].text.strip()
    raw = raw[raw.find("{"): raw.rfind("}") + 1]
    try:
        clips = json.loads(raw)["clips"][:max_clips]
    except (json.JSONDecodeError, KeyError) as e:
        log.error("clip JSON parse failed: %s\n%s", e, raw[:500])
        return []
    # sanity-clamp durations
    good = []
    for c in clips:
        if not isinstance(c.get("start"), int) or not isinstance(c.get("end"), int):
            continue
        if 20 <= (c["end"] - c["start"]) <= 300:
            good.append(c)
    return good
