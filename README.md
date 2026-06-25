# X Viral Tweet Bot (managed from Telegram)

Generates tweets with Claude, posts them to your X account, and lets you manage everything from Telegram: approve/reject drafts with buttons, post on demand, change topics, pause, or go full-auto.

## Setup

### 1. Get your keys
- **Claude API key**: https://console.anthropic.com → API Keys
- **X API keys**: https://developer.x.com → create a project + app (Free tier works for posting).
  In the app's *User authentication settings*, enable **Read and Write**, then generate:
  API Key, API Secret, Access Token, Access Token Secret.
- **Telegram bot**: message **@BotFather** → `/newbot` → copy the token.
  Then message **@userinfobot** to get your numeric chat ID.

### 2. Configure
```powershell
copy .env.example .env
# edit .env and fill in all the keys
```

### 3. Install & run
```powershell
py -m pip install -r requirements.txt
py bot.py
```

Then open your Telegram bot and send `/start`.

## Telegram commands
| Command | What it does |
|---|---|
| `/draft [topic]` | Generate a draft now (approve/redo/skip buttons) |
| `/post <text>` | Post exact text immediately |
| `/topics ai, startups` | Set the topic list |
| `/mode auto` / `/mode approve` | Auto-post vs. approval flow |
| `/watch handle1 handle2` | Accounts (max 5) whose recent posts feed trend detection — refreshed once daily |
| `/trends` | Show what's cached from watched accounts |
| `/inspo <pasted tweet>` | Manually add a tweet you like as trend/idea fuel (free, no API reads) |
| `/style <example tweet>` | Add a voice example the bot will emulate (up to 10) |
| `/template <structure>` | Add a structural template; one is picked at random per draft |
| `/clip` | Source a fresh YouTube video, transcribe, find the best 1–4 min moment, render it 16:9 (X) + 9:16 (TikTok/X), send for review |
| `/channels <urls>` | Show/set the YouTube source channels |
| `/pause` / `/resume` | Stop/start scheduled drafts |
| `/status` | Show settings and pending drafts |

## Video clip pipeline
`/clip` runs: **yt-dlp** (download newest unseen video) → **faster-whisper** (local transcription, CPU) → **Claude Haiku** (scores transcript, picks the spiciest 1–4 min moment + writes the caption) → **ffmpeg** (cuts it, renders a 9:16 blurred-fill vertical and a 16:9 landscape, burns the hook caption). The clip arrives in Telegram with buttons:

- **✅ Post to X** — uploads the 16:9 natively and posts with the caption.
- **📤 TikTok file** — sends you the 9:16 file + caption; tap to upload in the TikTok app (auto-publish needs TikTok app-audit approval; drafts/manual is the safe default).
- **❌ Skip**

> Note: a new/unverified X account caps native video at 2:20 — X Premium lifts this and is required for monetization eligibility anyway. Transcription runs on CPU (no GPU on Oracle free tier): ~30–90s per clip with the `base` model.

## Deploy on Oracle Cloud (Ubuntu 22.04 ARM, Always Free)
```bash
git clone https://github.com/mzterwalexzyy/Automated-Viral-Tweet-bot.git
cd Automated-Viral-Tweet-bot
bash deploy/setup.sh        # installs ffmpeg + deps + systemd service
nano .env                   # paste your keys
sudo systemctl start xbot   # start it
journalctl -u xbot -f       # watch logs
```
The bot runs 24/7 via systemd (auto-restart on crash/reboot). To avoid Oracle reclaiming an idle Always-Free VM, switch the account to Pay-As-You-Go (still $0 within free limits).

## How trend + style generation works
Each draft prompt combines: recent posts from your watched accounts and `/inspo` posts (to ride current themes), your `/style` examples (voice to emulate), and optionally one of your `/template` structures. Watched accounts are fetched **once per day** because X's free tier only allows ~100 read requests/month — keep the watchlist to ~3 accounts on the free tier, or use `/inspo` freely (it costs nothing). The Basic tier ($200/mo) lifts read limits if you ever need more.

By default the bot generates `DRAFTS_PER_DAY` drafts spread between 9:00 and 21:00 (local time) and sends each to Telegram for approval.

## Notes
- **Keep `mode=approve` at first** — review what gets posted until you trust the output.
- X's automation rules allow API posting to your own account; avoid spammy volume (a few posts/day is safe).
- X Free tier currently allows ~500 posts/month, plenty for this.
- To run it 24/7, deploy on any small VPS or keep your PC on; it's a single long-running process.
