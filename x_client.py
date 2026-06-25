"""Posting to X via tweepy (API v2, OAuth 1.0a user context)."""
import os
import time

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


def _v1_api() -> tweepy.API:
    """OAuth1 v1.1 API — needed for chunked media (video) upload."""
    auth = tweepy.OAuth1UserHandler(
        os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
        os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    return tweepy.API(auth)


def tweet_url(tweet_id: str) -> str:
    return f"https://x.com/i/web/status/{tweet_id}"


def post_video(text: str, video_path: str) -> str:
    """Upload a video and post it with the given caption. Returns the tweet id."""
    api = _v1_api()
    media = api.media_upload(
        filename=video_path, media_category="tweet_video", chunked=True,
    )
    # media processing is async on X's side; wait until it finishes
    media = api.get_media_upload_status(media.media_id)
    info = getattr(media, "processing_info", None)
    while info and info.get("state") in ("pending", "in_progress"):
        time.sleep(info.get("check_after_secs", 5))
        media = api.get_media_upload_status(media.media_id)
        info = getattr(media, "processing_info", None)
    if info and info.get("state") == "failed":
        raise RuntimeError(f"X video processing failed: {info.get('error')}")

    resp = get_client().create_tweet(text=text, media_ids=[media.media_id])
    return resp.data["id"]


def post_reply(text: str, reply_to_id: str) -> str:
    """Reply to a tweet. Returns the new tweet id."""
    resp = get_client().create_tweet(text=text, in_reply_to_tweet_id=reply_to_id)
    return resp.data["id"]
