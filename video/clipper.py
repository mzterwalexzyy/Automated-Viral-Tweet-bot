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

PICK_SYSTEM = """You are a viral short-form clip scout for X and TikTok, as sharp
as the editors behind the top-performing clip accounts in this space (accounts
that transcribe podcast moments as X posts and regularly hit 1-7M views).

You are given a timestamped transcript of a long podcast/talk video. Find the
BEST self-contained moments to clip (60-240s, target ~120s).

Score EVERY candidate on these 5 axes, each an integer 0 to its max:
- "hook" (0-25): Does it open on a line that stops the scroll — a shocking
  claim, direct address, or vivid image — within the first few seconds?
- "controversy" (0-25): A hot take, brutal honesty, a heated disagreement, an
  emotional confession, or a claim people will want to argue about in replies.
- "standalone" (0-20): Fully understandable with ZERO outside context — no
  dangling pronouns or callbacks to something not heard in this window.
- "recognizability" (0-15): A known person, show, or topic that carries
  built-in interest even for someone who's never seen this podcast.
- "quotability" (0-15): Contains a short, punchy line that works verbatim as
  an on-screen banner and as the tweet's opening hook line.

Calibration — the PATTERN of what wins (not literal content to copy):
- A caller reveals a specific, surprising financial detail and a host gives
  blunt, quotable advice back (scores high: controversy + quotability).
- A guest makes a provocative claim about a hot-button topic and the host
  pushes back with a sharp counter (scores high: controversy + hook).
- A recognizable guest reveals an ambitious, concrete plan or number in real
  time (scores high: recognizability + hook).
- A guest tells a short, self-contained funny/embarrassing story with a clean
  punchline (scores high: standalone + quotability, lower controversy is fine).

Only report moments that are ACTUALLY PRESENT in the transcript below — never
invent or assume content from general knowledge of who the speakers are.

Return STRICT JSON only, no prose:
{"clips": [{"start": <int>, "end": <int>,
"scores": {"hook": <int>, "controversy": <int>, "standalone": <int>,
"recognizability": <int>, "quotability": <int>},
"reason": "<one line: which axes it wins on and why>"}]}
Order clips best-first by total score. Return at most 4. start/end are seconds
and MUST fall within the transcript's timestamp range."""

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
   Wrap the ONE phrase that should pop in *asterisks* to render it red — a
   phrase can be multiple words if they're one unit (a movie/show title, a
   full name, a dollar figure), e.g. "He LOST *$2M* overnight" or
   "He brought *Reservoir Dogs* to impress him". Wrap the whole unit, not
   just one word of it.
5. "handles": array of @handles to tag, ONLY if a show/person is explicitly
   named in the excerpt. Empty array otherwise — never guess.

Return STRICT JSON only, no prose:
{"hook": "...", "intro": "...", "summary": "...",
"dialogue": [{"speaker": "...", "text": "..."}], "handles": ["@..."]}"""


# axis -> max points. Total score is always recomputed from these server-side
# (clamped to [0, max] each) rather than trusted from any model-provided sum,
# so a model arithmetic slip can't silently corrupt the min_score gate.
SCORE_AXES = {"hook": 25, "controversy": 25, "standalone": 20,
             "recognizability": 15, "quotability": 15}


def _score(clip: dict) -> int:
    axes = clip.get("scores") or {}
    total = 0
    for axis, max_pts in SCORE_AXES.items():
        try:
            v = int(axes.get(axis, 0))
        except (TypeError, ValueError):
            v = 0
        total += max(0, min(max_pts, v))
    return total


def pick_moments(transcript_text: str, max_clips: int = 4,
                 max_duration: float | None = None) -> list[dict]:
    """Step 1: pick candidate {start, end, scores, reason} windows only — no
    caption content yet, so there is nothing here for the model to fabricate
    beyond timestamps. max_duration is the real source length in seconds;
    LLMs can still hallucinate timestamps past the transcript's real range,
    so anything touching or exceeding it is dropped (would otherwise make
    ffmpeg seek past EOF and silently render an empty file)."""
    raw = llm.chat(PICK_SYSTEM, f"Transcript:\n{transcript_text}",
                   max_tokens=1500, temperature=0.5).strip()
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
            c["score"] = _score(c)
            good.append(c)
    good.sort(key=lambda c: c["score"], reverse=True)
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


DEFAULT_MIN_SCORE = 75


def find_clips(transcript_text: str, segments: list[dict],
               style_examples: list[str] | None = None, max_clips: int = 4,
               max_duration: float | None = None,
               min_score: int = DEFAULT_MIN_SCORE) -> list[dict]:
    """Orchestrates pick_moments -> caption_for (grounded in the real excerpt)
    for every candidate that clears the quality bar, returning a list of merged
    dicts: {start, end, score, reason, hook, intro, summary, dialogue, handles}.

    Quality-gated, not a fixed quota: a video with several strong, unrelated
    moments yields several clips; a video with only one worth cutting yields
    one. If NOTHING clears min_score, the single best candidate is still
    captioned so callers are never left completely empty-handed."""
    from . import transcribe  # local import: avoid a hard dependency cycle

    picks = pick_moments(transcript_text, max_clips=max_clips,
                        max_duration=max_duration)
    if not picks:
        return []

    keep = [p for p in picks if (p.get("score") or 0) >= min_score]
    if not keep:
        log.info("no candidate cleared min_score=%d; falling back to top pick "
                 "(score %s)", min_score, picks[0].get("score"))
        keep = picks[:1]

    results = []
    for pick in keep:
        excerpt = transcribe.excerpt_text(segments, pick["start"], pick["end"])
        if not excerpt.strip():
            log.error("no real transcript text found for %s-%s; skipping",
                      pick["start"], pick["end"])
            continue
        cap = caption_for(excerpt, style_examples=style_examples)
        if not cap:
            continue
        results.append({**pick, **cap})
    return results


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
