#!/usr/bin/env bash
# Download a section of the newest video from a given channel and render a clip.
# Usage: run_test_clip.sh <channel_url> <start HH:MM:SS> <end HH:MM:SS> "<hook>"
set -euo pipefail
cd "$(dirname "$0")/.."

CHANNEL="${1:?channel url}"
START="${2:?start}"
END="${3:?end}"
HOOK="${4:-}"

YT=".venv/bin/yt-dlp"
PY=".venv/bin/python"

COOKIES=""
[ -f work/yt_cookies.txt ] && COOKIES="--cookies work/yt_cookies.txt"

echo ">> Newest video on $CHANNEL"
ID="$($YT $COOKIES --flat-playlist --playlist-end 1 --print '%(id)s' "$CHANNEL" 2>/dev/null | head -1)"
echo ">> video id: $ID"

mkdir -p work
echo ">> Downloading section $START-$END (not the whole episode)…"
$YT $COOKIES --quiet --no-warnings \
    --download-sections "*${START}-${END}" \
    -f 'bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b' \
    --merge-output-format mp4 \
    -o work/section.mp4 \
    "https://www.youtube.com/watch?v=${ID}"

ls -lh work/section.mp4

# the downloaded file IS just the section, so clip from 0 to its full length
DUR="$($PY - <<'EOF'
import subprocess, json
out = subprocess.run([".venv/bin/ffprobe","-v","error","-show_entries",
    "format=duration","-of","json","work/section.mp4"],
    capture_output=True, text=True)
print(int(float(json.loads(out.stdout)["format"]["duration"])))
EOF
)"
echo ">> section duration: ${DUR}s"

echo ">> Rendering 9:16 + 16:9…"
$PY clip_cli.py work/section.mp4 --start 0 --end "$DUR" ${HOOK:+--hook "$HOOK"}

echo ">> Outputs:"
ls -lh work/clips/
