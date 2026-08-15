"""Generate genuine, content-specific replies to other accounts' posts.

Used for account warm-up: replying thoughtfully to accounts in your niche
before you start posting original content, to build presence/credibility.
Deliberately grounded in the actual tweet text so replies read as real
engagement, not templated filler — generic replies ("great post!") are
exactly the pattern X's spam detection watches for on new accounts.
"""
import llm

SYSTEM = """You write X (Twitter) replies for account warm-up: genuine, specific
engagement with a post, not generic filler.

Rules:
- Reference something SPECIFIC from the post — a detail, number, or claim —
  never a generic compliment like "great post!" or "so true!".
- Add a real opinion, a sharp follow-up question, a related fact, or a short
  personal take. Sound like a real person who actually read it.
- Max 200 characters. No hashtags. At most 1 emoji, and only if it fits
  naturally.
- No em dashes. Use commas, periods, or "and"/"but" instead.
- Never be sycophantic or salesy. Never mention you're a bot or an account.
- If the post has nothing worth engaging with, reply with exactly: SKIP"""


def _no_em_dash(text: str) -> str:
    """Hard safety net: strip em/en dashes regardless of prompt compliance."""
    return text.replace("—", ", ").replace("–", "-")


def generate_reply(post_text: str, style_examples: list[str] | None = None) -> str | None:
    style = ""
    if style_examples:
        joined = "\n".join(f"- {s}" for s in style_examples[:6])
        style = f"\n\nMatch this voice/tone (style only):\n{joined}"
    text = llm.chat(
        SYSTEM, f"Post to reply to:\n{post_text}{style}",
        max_tokens=150, temperature=0.8,
    ).strip().strip('"')
    if text.upper() == "SKIP" or not text:
        return None
    return _no_em_dash(text)[:280]
