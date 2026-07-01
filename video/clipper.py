"""Pick the most viral-worthy moments from a transcript via an LLM, then write
the post caption FROM THE REAL TRANSCRIPT TEXT of that exact window.

This is a deliberate two-step design to prevent hallucination. A single-shot
"pick a moment and write dialogue" prompt was found (2026-07-01) to invent
plausible-sounding but entirely fabricated dialogue: the model picked a valid,
in-bounds timestamp range whose real content was two people discussing
Reservoir Dogs and Denzel Washington movies, but wrote a caption about a
different topic (an album launch / an NFL team stake) pulled from its general
knowledge of the guest rather than anything actually said in the clip.
Grounding the caption step in the literal transcript excerpt makes that
failure mode structurally much harder: the model has nothing else to draw on.

Uses the OpenAI-compatible multi-provider client (llm.chat), so it runs on
free providers (NVIDIA NIM, OpenRouter, etc.) with automatic fallback.
"""
import json
import logging

import llm

log = logging.getLogger("xbot.clipper")

PICK_SYSTEM = """You are a viral short-form clip scout for X and TikTok. You are
given a timestamped transcript of a long podcast/talk video. Find the BEST
self-contained moments to clip. A great clip:
- is 60-240 seconds long (target ~120s), starts on a strong hook, ends on a punch
- contains a hot take, brutal advice, a shocking claim, a heated argument, an
  emotional confession, or a surprising story — something that makes people stop
- features a RECOGNIZABLE person or a high-controversy topic
- stands alone without needing prior context

Only report moments that are ACTUALLY PRESENT in the transcript below — never
invent or assume content from general knowledge of who the speakers are.

Return STRICT JSON only, no prose:
{"clips": [{"start": <int>, "end": <int>, "score": <1-100>, "reason": "<why it pops>"}]}
Order clips best-first. Return at most 4. start/end are seconds and MUST fall
within the transcript's timestamp range."""

CAPTION_SYSTEM = """You are writing a viral X/TikTok post caption for a clip, in
the exact format used by top clip accounts. You are given ONLY the literal
transcript excerpt for this clip — you must use NOTHING else. Do not use any
outside knowledge about the speakers, their careers, or unrelated facts. If the
excerpt doesn't mention something, it does not exist for this caption.

Write:
1. "intro": ONE news-anchor framing line in third person, factual but provocative,
   stating what someone says/claims IN THE EXCERPT. Examples:
   "Stephen A. Smith says Carmelo Anthony did NOT get a jury of his peers."
   It must create a curiosity gap or hint at conflict. No hashtags, no emojis.
2. "dialogue": the key exchange as an array of turns, QUOTING the excerpt
   near-verbatim (light cleanup of filler words only — do not add content).
   Each turn is {"speaker": "<NAME>", "text": "<quote>"}. Use real names/roles
   IF inferable from the excerpt (e.g. "Dave Ramsey" / "Caller"); otherwise use
   "Speaker 1" / "Speaker 2". 2-6 turns.
3. "summary": ONE punchy payoff line recapping the stakes/outcome, using only
   facts stated in the excerpt.
4. "hook": a SHORT on-screen banner text (<=45 chars) drawn from the excerpt.
   Wrap the ONE word that should pop in *asterisks* to render it red, e.g.
   "He LOST *$2M* overnight".
5. "handles": array of @handles to tag, ONLY if a show/person is explicitly
   named in the excerpt. Empty array otherwise — never guess.

Return STRICT JSON only, no prose:
{"hook": "...", "intro": "...", "summary": "...",
"dialogue": [{"speaker": "...", "text": "..."}], "handles": ["@..."]}"""


def pick_moments(transcript_text: str, max_clips: int = 4,
                 max_duration: float | None = None) -> list[dict]:
    """Step 1: pick candidate {start, end, score, reason} windows only — no
    caption content yet, so there is nothing here for the model to fabricate
    beyond timestamps. max_duration is the real source length in seconds;
    LLMs can still hallucinate timestamps past the transcript's real range,
    so anything touching or exceeding it is dropped (would otherwise make
    ffmpeg seek past EOF and silently render an empty file)."""
    raw = llm.chat(PICK_SYSTEM, f"Transcript:\n{transcript_text}",
                   max_tokens=1200, temperature=0.5).strip()
    raw = raw[raw.find("{"): raw.rfind("}") + 1]
    try:
        clips = json.loads(raw)["clips"][:max_clips]
    except (json.JSONDecodeError, KeyError) as e:
        log.error("pick JSON parse failed: %s\n%s", e, raw[:500])
        return []
    good = []
    for c in clips:
        if not isinstance(c.get("start"), int) or not isinstance(c.get("end"), int):
            continue
        if c["start"] < 0 or c["end"] <= c["start"]:
            continue
        if max_duration is not None and c["end"] > max_duration:
            log.warning("dropping out-of-bounds pick %s-%s (source is %.0fs)",
                       c["start"], c["end"], max_duration)
            continue
        if 20 <= (c["end"] - c["start"]) <= 300:
            good.append(c)
    return good


def caption_for(excerpt_text: str, style_examples: list[str] | None = None) -> dict:
    """Step 2: write the caption strictly from the real excerpt text."""
    style = ""
    if style_examples:
        joined = "\n".join(f"- {s}" for s in style_examples[:6])
        style = ("\n\nWrite in the voice/tone of these examples (style only, "
                 f"do not borrow their content):\n{joined}")
    raw = llm.chat(CAPTION_SYSTEM, f"Transcript excerpt:\n{excerpt_text}{style}",
                   max_tokens=1200, temperature=0.5).strip()
    raw = raw[raw.find("{"): raw.rfind("}") + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log.error("caption JSON parse failed: %s\n%s", e, raw[:500])
        return {}


def find_clips(transcript_text: str, segments: list[dict],
               style_examples: list[str] | None = None, max_clips: int = 4,
               max_duration: float | None = None) -> list[dict]:
    """Orchestrates pick_moments -> caption_for (grounded in the real excerpt)
    for the top candidate, returning the same merged shape callers expect:
    {start, end, score, reason, hook, intro, summary, dialogue, handles}.
    Only the top pick gets a caption generated (2nd LLM call) to keep this to
    one extra call per clip; callers only ever use clips[0] today."""
    from . import transcribe  # local import: avoid a hard dependency cycle

    picks = pick_moments(transcript_text, max_clips=max_clips,
                        max_duration=max_duration)
    if not picks:
        return []
    best = picks[0]
    excerpt = transcribe.excerpt_text(segments, best["start"], best["end"])
    if not excerpt.strip():
        log.error("no real transcript text found for %s-%s; refusing to caption",
                  best["start"], best["end"])
        return []
    cap = caption_for(excerpt, style_examples=style_examples)
    if not cap:
        return []
    best = {**best, **cap}
    return [best]


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
