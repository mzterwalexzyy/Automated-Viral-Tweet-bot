"""Build word-by-word ("karaoke") burned captions as an ASS subtitle file.

Words are grouped into short phrases (max ~4 words / ~2.5s). Within a phrase,
each word sweeps from white to a highlight colour using ASS \\k karaoke timing,
which is the look used by most viral clip channels.
"""
import re
from pathlib import Path

# Aspect-specific play resolution and font sizing.
LAYOUTS = {
    "vertical": {"w": 1080, "h": 1920, "fontsize": 64, "margin_v": 420},
    "landscape": {"w": 1920, "h": 1080, "fontsize": 56, "margin_v": 240},
}

MAX_WORDS = 4
MAX_PHRASE_S = 2.5


def _ass_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _group(words: list[dict]) -> list[list[dict]]:
    phrases, cur = [], []
    for w in words:
        if cur and (len(cur) >= MAX_WORDS
                    or w["end"] - cur[0]["start"] > MAX_PHRASE_S):
            phrases.append(cur)
            cur = []
        cur.append(w)
    if cur:
        phrases.append(cur)
    return phrases


_ASTERISK_SPAN = re.compile(r"\*([^*]+)\*")
_STOPWORDS = {"the", "a", "an", "to", "of", "and", "in", "on", "for", "is",
             "was", "his", "her", "he", "she", "it", "him", "with", "that"}


def _fallback_emphasis(hook: str) -> str:
    """Wrap an emphasis phrase in *asterisks* when the LLM didn't provide one.

    Prefers a multi-word proper-noun-looking run (e.g. a movie title: "Reservoir
    Dogs") over a single word, since titles/names read as one visual unit.
    """
    words = hook.split()
    # find runs of consecutive Capitalized words (skip index 0: sentence-start
    # capitalization isn't necessarily meaningful on its own)
    best_run: list[int] = []
    run: list[int] = []
    for i, w in enumerate(words):
        bare = w.strip(".,!?")
        is_cap = bare[:1].isupper() and bare.lower() not in _STOPWORDS
        if is_cap and i > 0:
            run.append(i)
        else:
            if len(run) > len(best_run):
                best_run = run
            run = []
    if len(run) > len(best_run):
        best_run = run

    if len(best_run) >= 2:
        idxs = best_run
    else:
        candidates = [i for i, w in enumerate(words)
                     if w.lower().strip(".,!?") not in _STOPWORDS]
        pool = candidates or list(range(len(words)))
        idxs = [max(pool, key=lambda i: len(words[i]))]

    words[idxs[0]] = "*" + words[idxs[0]]
    words[idxs[-1]] = words[idxs[-1]] + "*"
    return " ".join(words)


def build_banner_ass(hook: str, kind: str, out_path: Path,
                     position: str = "top", duration: float = 9999.0) -> Path | None:
    """Banner overlay: thick bold text on a solid white box.

    Colour via markup: text wrapped in *asterisks* renders RED (can span
    multiple words, e.g. a title: '*Reservoir Dogs*'), everything else BLACK.
    """
    if not hook or not hook.strip():
        return None
    lay = LAYOUTS[kind]
    fontsize = 84 if kind == "vertical" else 72
    # an=8 top-center for 9:16, an=2 bottom-center for 16:9
    align = 8 if position == "top" else 2
    margin_v = 130 if position == "top" else 70

    BLACK = r"{\c&H000000&}"
    RED = r"{\c&H0000FF&}"          # ASS is &HBBGGRR -> red

    # The LLM is asked to wrap the emphasis phrase in *asterisks*, but doesn't
    # always comply - guarantee the style anyway.
    if not _ASTERISK_SPAN.search(hook):
        hook = _fallback_emphasis(hook)

    parts = []
    pos = 0
    for m in _ASTERISK_SPAN.finditer(hook):
        before = hook[pos:m.start()]
        if before.strip():
            parts.append(BLACK + before.strip().replace("{", "(").replace("}", ")"))
        span = m.group(1).replace("{", "(").replace("}", ")")
        parts.append(RED + span)
        pos = m.end()
    tail = hook[pos:]
    if tail.strip():
        parts.append(BLACK + tail.strip().replace("{", "(").replace("}", ")"))
    text = " ".join(parts)

    # BorderStyle=3 + white OutlineColour => solid white box behind the text.
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {lay['w']}
PlayResY: {lay['h']}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Banner,Arial Black,{fontsize},&H000000&,&H000000&,&H00FFFFFF&,&H00FFFFFF&,-1,0,0,0,100,100,1,0,3,16,0,{align},40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, Effect, Text
Dialogue: 0,0:00:00.00,{_ass_time(duration)},Banner,,0,0,0,,{text}
"""
    out_path.write_text(header, encoding="utf-8")
    return out_path


def build_ass(words: list[dict], kind: str, out_path: Path) -> Path | None:
    """Write an ASS file for the given clip-relative words. Returns path or None."""
    words = [w for w in words if w["word"]]
    if not words:
        return None
    lay = LAYOUTS[kind]

    # PrimaryColour = highlighted (sweeps in), SecondaryColour = pre-highlight.
    # ASS colours are &HAABBGGRR. Yellow highlight, white base, black outline.
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {lay['w']}
PlayResY: {lay['h']}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,Arial Black,{lay['fontsize']},&H0000F0FF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,2,2,60,60,{lay['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, Effect, Text
"""

    lines = []
    for phrase in _group(words):
        p_start = phrase[0]["start"]
        p_end = phrase[-1]["end"]
        chunks = []
        for w in phrase:
            dur_cs = max(1, int(round((w["end"] - w["start"]) * 100)))
            text = w["word"].replace("{", "(").replace("}", ")")
            chunks.append(f"{{\\k{dur_cs}}}{text} ")
        text = "".join(chunks).strip()
        lines.append(
            f"Dialogue: 0,{_ass_time(p_start)},{_ass_time(p_end)},Karaoke,,0,0,0,,{text}")

    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return out_path
