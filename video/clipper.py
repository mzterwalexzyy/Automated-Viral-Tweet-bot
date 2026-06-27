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

SYSTEM = """You are a viral short-form clip editor for X and TikTok. You are given a
timestamped transcript of a long podcast/talk video. Find the BEST self-contained
moments to clip. A great clip:
- is 60-240 seconds long (target ~120s), starts on a strong hook, ends on a punch
- contains a hot take, brutal advice, a shocking claim, a heated argument, an
  emotional confession, or a surprising story — something that makes people stop
- features a RECOGNIZABLE person or a high-controversy topic
- stands alone without needing prior context

For each clip write a CAPTION in this exact viral format (used by top clip accounts):
1. "intro": ONE news-anchor framing line in third person, factual but provocative,
   stating what someone says/claims. Examples:
   "Stephen A. Smith says Carmelo Anthony did NOT get a jury of his peers."
   "A wife claimed women are more free in Islam than any other religion."
   It must create a curiosity gap or hint at conflict. No hashtags, no emojis.
2. "dialogue": the key exchange as an array of turns. Each turn is
   {"speaker": "<NAME>", "text": "<verbatim-ish quote, tightened>"}.
   Use the speakers' REAL names/roles, exactly as a clip account would label them:
   the host by name if recognizable (e.g. "Dave Ramsey", "Caleb", "Stephen A. Smith")
   and the other person by role ("Caller", "Guest", "Caller"). 2-6 turns.
3. "summary": ONE punchy payoff line recapping the stakes/outcome in plain words,
   e.g. "$600K net worth at 26. Fiancee in PA school with debt. Dave says skip the prenup."
4. "hook": a SHORT on-screen banner text (<=45 chars), punchy. Wrap the ONE word
   that should pop in *asterisks* to render it red, e.g. "He LOST *$2M* overnight".
5. "handles": array of @handles to tag (the show + notable people if known),
   e.g. ["@stephenasmith"]. Empty array if unknown.

Return STRICT JSON only, no prose:
{"clips": [{"start": <int>, "end": <int>, "score": <1-100>, "reason": "<why it pops>",
"hook": "<banner text>", "intro": "<news-anchor line>", "summary": "<payoff line>",
"dialogue": [{"speaker": "<name>", "text": "..."}, {"speaker": "<name>", "text": "..."}],
"handles": ["@..."]}]}
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


def build_caption(clip: dict, names: dict | None = None) -> str:
    """Assemble the final post caption in the winning clip-account format:

        <news-anchor intro line>

        <Speaker>: "quote"
        <Speaker>: "quote"

        <summary payoff line>

    `names` optionally remaps speaker labels the model produced (e.g. fixing a
    misheard host name); by default the model's own labels are used as-is.
    """
    names = names or {}
    parts = [clip.get("intro", "").strip()]
    dialogue = clip.get("dialogue") or []
    if dialogue:
        parts.append("")  # blank line
        for turn in dialogue:
            who = str(turn.get("speaker", "Speaker"))
            who = names.get(who, who)
            text = turn.get("text", "").strip().strip('"')
            parts.append(f'{who}: "{text}"')
    summary = clip.get("summary", "").strip()
    if summary:
        parts.append("")
        parts.append(summary)
    return "\n".join(p for p in parts if p is not None).strip()


def build_ft(clip: dict) -> str:
    """The follow-up reply tweet that tags sources, e.g. 'Ft. @a | @b'."""
    handles = [h.strip() for h in (clip.get("handles") or []) if h.strip()]
    handles = [h if h.startswith("@") else "@" + h for h in handles]
    return "Ft. " + " | ".join(handles) if handles else ""
