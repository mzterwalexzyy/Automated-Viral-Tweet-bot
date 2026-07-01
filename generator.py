"""Tweet generation via the OpenAI-compatible LLM client, with style emulation
and trend awareness. Runs on whatever providers are configured in .env."""
import random

import llm

SYSTEM = """You are a social media ghostwriter who writes high-engagement tweets.
Rules:
- Max 270 characters. Plain text only, no hashtags unless they truly add value (max 1).
- Strong hook in the first line. Be specific, opinionated, or surprising — never generic.
- No emojis unless they fit naturally (max 1).
- Never use cliches like "game-changer", "unlock", "in today's world".
- Output ONLY the tweet text, nothing else."""

STYLES = [
    "a contrarian hot take",
    "a useful tip people will bookmark",
    "a short personal-sounding observation",
    "a bold prediction",
    "a question that sparks replies",
    "a 'most people don't realize' insight",
]


def _block(title: str, items: list[str], limit: int) -> str:
    if not items:
        return ""
    joined = "\n".join(f"- {t}" for t in items[-limit:])
    return f"\n\n{title}\n{joined}"


def generate_tweet(
    topic: str,
    recent_tweets: list[str] | None = None,
    style_examples: list[str] | None = None,
    trending: list[str] | None = None,
    template: str | None = None,
) -> str:
    parts = []

    if trending:
        sample = random.sample(trending, min(len(trending), 15))
        parts.append(_block(
            "Recent posts from accounts in this niche (spot the themes people are "
            "talking about RIGHT NOW and write something that rides one of those "
            "themes — do not copy any post):", sample, 15))

    if style_examples:
        parts.append(_block(
            "Emulate the voice, rhythm, formatting and length of these example "
            "tweets (style only — not their content):", style_examples, 8))

    if template:
        parts.append(f"\n\nFollow this template structure exactly:\n{template}")
    else:
        parts.append(f"\n\nWrite {random.choice(STYLES)}.")

    parts.append(_block("Do NOT repeat ideas from these recent tweets:",
                        recent_tweets or [], 10))

    prompt = f"Write one tweet about: {topic}." + "".join(parts)

    text = llm.chat(SYSTEM, prompt, max_tokens=300, temperature=0.9).strip().strip('"')
    return text[:280]
