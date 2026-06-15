"""Fetch recent tweets from watched accounts to learn what's trending.

Read requests on the X free tier are scarce (~100/month), so this fetches
each watched account at most once per day and caches results in state.
"""
import logging
import time

import tweepy

from x_client import get_client

log = logging.getLogger("xbot.watchlist")

FETCH_INTERVAL_S = 24 * 3600  # one fetch per account per day
TWEETS_PER_ACCOUNT = 10


def fetch_watched_accounts(state: dict) -> tuple[int, list[str]]:
    """Refresh cached tweets for accounts whose cache is older than a day.

    Returns (accounts_refreshed, errors). Mutates state["watch_cache"]:
      handle -> {"user_id": str, "fetched_at": float, "tweets": [str, ...]}
    """
    client = get_client()
    cache = state.setdefault("watch_cache", {})
    now = time.time()
    refreshed, errors = 0, []

    for handle in state.get("watch", []):
        entry = cache.get(handle, {})
        if now - entry.get("fetched_at", 0) < FETCH_INTERVAL_S:
            continue
        try:
            user_id = entry.get("user_id")
            if not user_id:
                user = client.get_user(username=handle)
                user_id = str(user.data.id)
            resp = client.get_users_tweets(
                user_id, max_results=TWEETS_PER_ACCOUNT,
                exclude=["retweets", "replies"],
            )
            tweets = [t.text for t in (resp.data or [])]
            cache[handle] = {"user_id": user_id, "fetched_at": now, "tweets": tweets}
            refreshed += 1
        except tweepy.TooManyRequests:
            errors.append(f"@{handle}: rate limited — try again later")
            break
        except Exception as e:
            errors.append(f"@{handle}: {e}")
    return refreshed, errors


def trending_context(state: dict) -> list[str]:
    """All cached tweets from watched accounts plus manually added inspiration."""
    tweets = []
    for entry in state.get("watch_cache", {}).values():
        tweets.extend(entry.get("tweets", []))
    tweets.extend(state.get("inspo", []))
    return tweets
