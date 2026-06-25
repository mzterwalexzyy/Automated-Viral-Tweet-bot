"""Telegram-managed X auto-posting bot.

Run:  python bot.py
Telegram commands:
  /draft [topic]   - generate a draft now (approve/reject via buttons)
  /post <text>     - post exact text immediately
  /topics a, b, c  - set topic list
  /mode auto|approve
  /pause /resume   - pause or resume scheduled drafts
  /status          - show current settings
"""
import asyncio
import json
import logging
import os
import random
import time
from datetime import time as dtime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes)

from generator import generate_tweet
from watchlist import fetch_watched_accounts, trending_context
from x_client import post_tweet, post_video
from video.pipeline import make_clip, DEFAULT_CHANNELS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("xbot")

STATE_FILE = Path(__file__).parent / "state.json"
CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])


DEFAULT_STATE = {
    "mode": os.getenv("MODE", "approve"),
    "paused": False,
    "drafts": {},          # draft_id -> text
    "recent": [],          # last posted tweets (dedup context)
    "next_id": 1,
    "watch": [],           # X handles to learn trends from
    "watch_cache": {},     # cached tweets per handle (refreshed daily)
    "inspo": [],           # manually pasted tweets (trend/style fuel, no API reads)
    "styles": [],          # example tweets whose voice to emulate
    "templates": [],       # structural templates; one is picked at random if any
    "channels": list(DEFAULT_CHANNELS),  # YouTube sources for clipping
    "clips": {},           # clip_id -> clip job dict (pending review)
}


def load_state() -> dict:
    state = dict(DEFAULT_STATE)
    state["topics"] = [t.strip() for t in os.getenv("TOPICS", "tech,AI").split(",") if t.strip()]
    if STATE_FILE.exists():
        state.update(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    return state


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


STATE = load_state()


def authorized(update: Update) -> bool:
    return update.effective_chat and update.effective_chat.id == CHAT_ID


async def send_draft(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Send a draft to Telegram with approve/reject/regenerate buttons."""
    draft_id = str(STATE["next_id"])
    STATE["next_id"] += 1
    STATE["drafts"][draft_id] = text
    save_state(STATE)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Post", callback_data=f"post:{draft_id}"),
        InlineKeyboardButton("🔄 Redo", callback_data=f"redo:{draft_id}"),
        InlineKeyboardButton("❌ Skip", callback_data=f"skip:{draft_id}"),
    ]])
    await context.bot.send_message(CHAT_ID, f"📝 Draft:\n\n{text}", reply_markup=kb)


def make_tweet(topic: str, extra_avoid: list[str] | None = None) -> str:
    """Generate a tweet using all configured context (trends, style, template)."""
    return generate_tweet(
        topic,
        recent_tweets=STATE["recent"] + (extra_avoid or []),
        style_examples=STATE["styles"],
        trending=trending_context(STATE),
        template=random.choice(STATE["templates"]) if STATE["templates"] else None,
    )


async def refresh_watchlist(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not STATE["watch"]:
        return
    refreshed, errors = await asyncio.to_thread(fetch_watched_accounts, STATE)
    save_state(STATE)
    if errors:
        await context.bot.send_message(CHAT_ID, "⚠️ Watchlist:\n" + "\n".join(errors))
    if refreshed:
        log.info("Refreshed %d watched accounts", refreshed)


async def scheduled_draft(context: ContextTypes.DEFAULT_TYPE) -> None:
    if STATE["paused"]:
        return
    topic = random.choice(STATE["topics"])
    try:
        text = await asyncio.to_thread(make_tweet, topic)
    except Exception as e:
        log.exception("generation failed")
        await context.bot.send_message(CHAT_ID, f"⚠️ Draft generation failed: {e}")
        return
    if STATE["mode"] == "auto":
        await do_post(context, text)
    else:
        await send_draft(context, text)


async def do_post(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    try:
        url = post_tweet(text)
        STATE["recent"] = (STATE["recent"] + [text])[-20:]
        save_state(STATE)
        await context.bot.send_message(CHAT_ID, f"🚀 Posted: {url}")
    except Exception as e:
        log.exception("post failed")
        await context.bot.send_message(CHAT_ID, f"⚠️ Post failed: {e}")


# ---------- video clip flow ----------

async def send_clip(context: ContextTypes.DEFAULT_TYPE, job: dict) -> None:
    """Send a rendered clip to Telegram with platform action buttons."""
    clip_id = str(STATE["next_id"])
    STATE["next_id"] += 1
    STATE["clips"][clip_id] = job
    save_state(STATE)

    dur = job["end"] - job["start"]
    caption = (
        f"🎬 Clip ({dur}s, score {job.get('score', '?')})\n"
        f"From: {job['video_id']}\n"
        f"Why: {job.get('reason', '')}\n\n"
        f"📝 Caption:\n{job.get('caption', '')}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Post to X", callback_data=f"clipx:{clip_id}"),
         InlineKeyboardButton("📤 TikTok file", callback_data=f"cliptt:{clip_id}")],
        [InlineKeyboardButton("❌ Skip", callback_data=f"clipskip:{clip_id}")],
    ])
    # send the vertical preview if present, else landscape
    files = job["files"]
    preview = files.get("vertical") or files.get("landscape")
    try:
        with open(preview, "rb") as fh:
            await context.bot.send_video(CHAT_ID, fh, caption=caption, reply_markup=kb)
    except Exception:
        log.exception("send_video failed; sending text only")
        await context.bot.send_message(CHAT_ID, caption, reply_markup=kb)


async def cmd_clip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Source + render one fresh clip now and send it for review."""
    if not authorized(update):
        return
    await update.message.reply_text(
        "🎬 Sourcing a video, transcribing and finding the best moment… "
        "(this can take a few minutes)")
    try:
        job = await asyncio.to_thread(make_clip, STATE["channels"], STATE["styles"])
    except Exception as e:
        log.exception("clip pipeline failed")
        await update.message.reply_text(f"⚠️ Clip failed: {e}")
        return
    if not job:
        await update.message.reply_text(
            "No new clip found (no fresh source videos or no strong moment).")
        return
    await send_clip(context, job)


async def cmd_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show or set YouTube source channels. /channels url1 url2 ..."""
    if not authorized(update):
        return
    if context.args:
        STATE["channels"] = list(context.args)
        save_state(STATE)
    listing = "\n".join(f"- {c}" for c in STATE["channels"])
    await update.message.reply_text(f"Source channels:\n{listing}")


# ---------- command handlers ----------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    await update.message.reply_text(
        "X bot online. Commands:\n"
        "/draft [topic] – generate a draft now\n"
        "/post <text> – post text directly\n"
        "/topics a, b, c – set topics\n"
        "/mode auto|approve\n"
        "/watch handle1 handle2 – accounts to learn trends from\n"
        "/trends – show cached trend data\n"
        "/inspo <tweet> – paste a tweet you like (trend fuel, no API reads)\n"
        "/style <tweet> – add a voice example to emulate\n"
        "/template <structure> – add a tweet template\n"
        "/clip – source+cut a video clip now (review, post to X / TikTok)\n"
        "/channels <urls> – set YouTube source channels\n"
        "/pause /resume /status"
    )


async def cmd_draft(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    topic = " ".join(context.args) if context.args else random.choice(STATE["topics"])
    await update.message.reply_text(f"Generating draft about “{topic}”…")
    try:
        text = await asyncio.to_thread(make_tweet, topic)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Generation failed: {e}")
        return
    await send_draft(context, text)


async def cmd_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    text = update.message.text.partition(" ")[2].strip()
    if not text:
        await update.message.reply_text("Usage: /post your tweet text")
        return
    await do_post(context, text)


async def cmd_topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    raw = update.message.text.partition(" ")[2]
    if raw.strip():
        STATE["topics"] = [t.strip() for t in raw.split(",") if t.strip()]
        save_state(STATE)
    await update.message.reply_text("Topics: " + ", ".join(STATE["topics"]))


async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    if context.args and context.args[0] in ("auto", "approve"):
        STATE["mode"] = context.args[0]
        save_state(STATE)
    await update.message.reply_text(f"Mode: {STATE['mode']}")


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    STATE["paused"] = True
    save_state(STATE)
    await update.message.reply_text("⏸ Paused scheduled drafts.")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    STATE["paused"] = False
    save_state(STATE)
    await update.message.reply_text("▶️ Resumed.")


async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set accounts to learn trends from: /watch naval levelsio  (no args = show)."""
    if not authorized(update):
        return
    if context.args:
        STATE["watch"] = [h.lstrip("@").strip(",") for h in context.args][:5]
        save_state(STATE)
        await update.message.reply_text(
            "Watching: " + ", ".join("@" + h for h in STATE["watch"]) +
            "\nFetching their recent posts…")
        await refresh_watchlist(context)
        n = len(trending_context(STATE))
        await update.message.reply_text(f"Done — {n} posts cached as trend context.")
    else:
        await update.message.reply_text(
            "Watching: " + (", ".join("@" + h for h in STATE["watch"]) or "(none)") +
            "\nUsage: /watch handle1 handle2 (max 5, refreshed daily)")


async def cmd_trends(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show cached trend posts and when each account was last fetched."""
    if not authorized(update):
        return
    lines = []
    for h, entry in STATE["watch_cache"].items():
        age_h = (time.time() - entry.get("fetched_at", 0)) / 3600
        lines.append(f"@{h}: {len(entry.get('tweets', []))} posts ({age_h:.0f}h ago)")
    lines.append(f"Manual inspo: {len(STATE['inspo'])} posts")
    await update.message.reply_text("\n".join(lines))


async def cmd_inspo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Paste a tweet you like: /inspo <text>. Used as trend context (no API reads)."""
    if not authorized(update):
        return
    text = update.message.text.partition(" ")[2].strip()
    if text == "clear":
        STATE["inspo"] = []
        save_state(STATE)
        await update.message.reply_text("Inspo cleared.")
        return
    if not text:
        await update.message.reply_text(
            f"{len(STATE['inspo'])} inspo posts saved. Usage: /inspo <pasted tweet> "
            "or /inspo clear")
        return
    STATE["inspo"] = (STATE["inspo"] + [text])[-30:]
    save_state(STATE)
    await update.message.reply_text(f"Saved ({len(STATE['inspo'])} inspo posts).")


async def cmd_style(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add an example tweet whose voice to emulate: /style <text>."""
    if not authorized(update):
        return
    text = update.message.text.partition(" ")[2].strip()
    if text == "clear":
        STATE["styles"] = []
    elif text:
        STATE["styles"] = (STATE["styles"] + [text])[-10:]
    save_state(STATE)
    await update.message.reply_text(
        f"{len(STATE['styles'])} style examples saved. "
        "Usage: /style <example tweet> or /style clear")


async def cmd_template(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a structural template: /template <text>. One is picked at random per draft."""
    if not authorized(update):
        return
    text = update.message.text.partition(" ")[2].strip()
    if text == "clear":
        STATE["templates"] = []
    elif text:
        STATE["templates"].append(text)
    save_state(STATE)
    if STATE["templates"]:
        listing = "\n\n".join(f"{i+1}. {t}" for i, t in enumerate(STATE["templates"]))
        await update.message.reply_text(f"Templates:\n\n{listing}")
    else:
        await update.message.reply_text(
            "No templates. Usage: /template <structure>, e.g.\n"
            "/template Hook question. Then 3 short lines of advice. End with a punchy one-liner.")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    await update.message.reply_text(
        f"Mode: {STATE['mode']}\n"
        f"Paused: {STATE['paused']}\n"
        f"Topics: {', '.join(STATE['topics'])}\n"
        f"Watching: {', '.join('@' + h for h in STATE['watch']) or '(none)'}\n"
        f"Trend posts cached: {len(trending_context(STATE))}\n"
        f"Style examples: {len(STATE['styles'])} | Templates: {len(STATE['templates'])}\n"
        f"Pending drafts: {len(STATE['drafts'])}\n"
        f"Posted (recent): {len(STATE['recent'])}"
    )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    q = update.callback_query
    await q.answer()
    action, _, ident = q.data.partition(":")

    # ----- clip actions -----
    if action.startswith("clip"):
        job = STATE["clips"].get(ident)
        if job is None:
            await q.edit_message_caption("(clip expired)")
            return
        if action == "clipx":
            vid = job["files"].get("landscape") or job["files"].get("vertical")
            await q.edit_message_caption("Uploading to X…")
            try:
                url = await asyncio.to_thread(post_video, job.get("caption", ""), vid)
                await context.bot.send_message(CHAT_ID, f"🚀 Posted to X: {url}")
                STATE["clips"].pop(ident, None)
                save_state(STATE)
            except Exception as e:
                log.exception("X video post failed")
                await context.bot.send_message(CHAT_ID, f"⚠️ X post failed: {e}")
        elif action == "cliptt":
            # TikTok: deliver the 9:16 file + caption for one-tap upload in the app
            vfile = job["files"].get("vertical")
            cap = job.get("caption", "")
            try:
                with open(vfile, "rb") as fh:
                    await context.bot.send_document(
                        CHAT_ID, fh, filename=f"{job['video_id']}_tiktok.mp4",
                        caption=f"TikTok caption:\n{cap}")
            except Exception as e:
                await context.bot.send_message(CHAT_ID, f"⚠️ Couldn't send file: {e}")
        else:  # clipskip
            STATE["clips"].pop(ident, None)
            save_state(STATE)
            await q.edit_message_caption("❌ Clip skipped.")
        return

    # ----- text draft actions -----
    draft_id = ident
    text = STATE["drafts"].pop(draft_id, None)
    save_state(STATE)
    if text is None:
        await q.edit_message_text("(draft expired)")
        return
    if action == "post":
        await q.edit_message_text(f"Posting…\n\n{text}")
        await do_post(context, text)
    elif action == "redo":
        await q.edit_message_text("Regenerating…")
        try:
            new_text = await asyncio.to_thread(
                make_tweet, random.choice(STATE["topics"]), [text])
        except Exception as e:
            await context.bot.send_message(CHAT_ID, f"⚠️ Generation failed: {e}")
            return
        await send_draft(context, new_text)
    else:  # skip
        await q.edit_message_text(f"❌ Skipped:\n\n{text}")


def main() -> None:
    app = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("draft", cmd_draft))
    app.add_handler(CommandHandler("post", cmd_post))
    app.add_handler(CommandHandler("topics", cmd_topics))
    app.add_handler(CommandHandler("mode", cmd_mode))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("trends", cmd_trends))
    app.add_handler(CommandHandler("inspo", cmd_inspo))
    app.add_handler(CommandHandler("style", cmd_style))
    app.add_handler(CommandHandler("template", cmd_template))
    app.add_handler(CommandHandler("clip", cmd_clip))
    app.add_handler(CommandHandler("channels", cmd_channels))
    app.add_handler(CallbackQueryHandler(on_button))

    # Refresh trend data shortly before the first draft of the day
    app.job_queue.run_daily(refresh_watchlist, time=dtime(8, 30))

    # Spread N drafts/day across 9:00–21:00
    n = max(1, int(os.getenv("DRAFTS_PER_DAY", "4")))
    span_minutes = 12 * 60
    for i in range(n):
        minutes = int(9 * 60 + i * span_minutes / n)
        app.job_queue.run_daily(scheduled_draft, time=dtime(minutes // 60, minutes % 60))

    log.info("Bot starting; %d scheduled drafts/day", n)
    app.run_polling()


if __name__ == "__main__":
    main()
