"""Posting to X via tweepy (API v2, OAuth 1.0a user context)."""
import os

import tweepy


def get_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def post_tweet(text: str) -> str:
    """Post a tweet and return its URL."""
    resp = get_client().create_tweet(text=text)
    tweet_id = resp.data["id"]
    return f"https://x.com/i/web/status/{tweet_id}"
