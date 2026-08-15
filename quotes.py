"""Generate quote-tweet commentary for controversial/engaging posts.

A quote tweet is different from a reply: it's YOUR OWN post, shown to your
followers, with the original embedded below it. So the copy needs to work as
a standalone hook/stance for people who haven't seen the original yet, not a
conversational reply to the original poster.
"""
import llm

SYSTEM = """You write X (Twitter) quote-tweet commentary designed to trigger
engagement (replies, quote-tweets, debate) — especially on controversial posts.

Rules:
- Take a REAL, clear stance: agree hard, disagree hard, or reframe the issue
  sharply. Never be wishy-washy or sit on the fence, that gets no engagement.
- Write for people who HAVEN'T seen the original yet — it must work as a
  standalone hook, not a reply that only makes sense next to the source.
- A sharp question the reader has to answer works well too (e.g. "So which
  is it?" after pointing out a contradiction).
- Max 200 characters. No hashtags. At most 1 emoji, and only if it fits
  naturally. No em dashes, use commas or periods instead.
- Sharp and opinionated is good. Never hateful, harassing, or targeting
  someone's identity — attack the ARGUMENT, not the person.
- Only worth quoting if it's genuinely controversial, surprising, or
  debate-worthy. If the post is bland/uncontroversial, reply with exactly: SKIP"""


def _no_em_dash(text: str) -> str:
    return text.replace("—", ", ").replace("–", "-")


def generate_quote(post_text: str, style_examples: list[str] | None = None) -> str | None:
    style = ""
    if style_examples:
        joined = "\n".join(f"- {s}" for s in style_examples[:6])
        style = f"\n\nMatch this voice/tone (style only):\n{joined}"
    text = llm.chat(
        SYSTEM, f"Post to quote-tweet:\n{post_text}{style}",
        max_tokens=150, temperature=0.85,
    ).strip().strip('"')
    if text.upper() == "SKIP" or not text:
        return None
    return _no_em_dash(text)[:280]
