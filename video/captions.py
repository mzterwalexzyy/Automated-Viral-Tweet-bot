"""Build word-by-word ("karaoke") burned captions as an ASS subtitle file.

Words are grouped into short phrases (max ~4 words / ~2.5s). Within a phrase,
each word sweeps from white to a highlight colour using ASS \\k karaoke timing,
which is the look used by most viral clip channels.
"""
from pathlib import Path

# Aspect-specific play resolution and font sizing.
LAYOUTS = {
    "vertical": {"w": 1080, "h": 1920, "fontsize": 64, "margin_v": 420},
    "landscape": {"w": 1920, "h": 1080, "fontsize": 56, "margin_v": 150},
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
