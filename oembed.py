"""Fetch a public tweet's text from just its URL, with no X API read access.

Uses X's own public oEmbed endpoint (publish.twitter.com) - the same
mechanism sites use to embed tweets. Unauthenticated, free, and sanctioned by
X (it's their own public API for exactly this purpose), unlike scraping.
"""
import html
import logging
import re

import requests

log = logging.getLogger("xbot.oembed")

TWEET_URL_RE = re.compile(r"(?:x\.com|twitter\.com)/(\w+)/status(?:es)?/(\d+)")
_TAG_RE = re.compile(r"<[^>]+>")


def find_tweet_url(text: str) -> str | None:
    """Return the first x.com/twitter.com status URL found in free text, if any."""
    m = TWEET_URL_RE.search(text)
    return m.group(0) if m else None


def fetch_tweet(url: str) -> dict | None:
    """Return {"id": str, "handle": str, "text": str} for a tweet URL, or None
    if it can't be resolved (private/deleted/invalid/network error)."""
    m = TWEET_URL_RE.search(url)
    if not m:
        return None
    tweet_id = m.group(2)
    try:
        resp = requests.get(
            "https://publish.twitter.com/oembed",
            params={"url": f"https://twitter.com/i/status/{tweet_id}", "omit_script": "true"},
            timeout=20,
        )
        if resp.status_code != 200:
            log.warning("oembed failed for %s: HTTP %s", tweet_id, resp.status_code)
            return None
        data = resp.json()
    except Exception as e:
        log.warning("oembed request failed for %s: %s", tweet_id, e)
        return None

    author_url = data.get("author_url", "")
    handle_m = re.search(r"(?:x|twitter)\.com/(\w+)", author_url)
    handle = handle_m.group(1) if handle_m else data.get("author_name", "")

    # The embed HTML has a <p>...</p> with the tweet text; strip tags/entities.
    raw_html = data.get("html", "")
    p_m = re.search(r"<p[^>]*>(.*?)</p>", raw_html, re.DOTALL)
    text = _TAG_RE.sub("", p_m.group(1)) if p_m else ""
    text = html.unescape(text).replace("&mdash;", "").strip()
    if not text:
        return None
    return {"id": tweet_id, "handle": handle, "text": text}
