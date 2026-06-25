#!/usr/bin/env bash
# One-shot setup for Ubuntu 22.04 ARM (Oracle Cloud Always Free Ampere A1).
# Installs system deps, Python venv, and a systemd service for the bot.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo ">> App dir: $APP_DIR"

echo ">> Installing system packages (ffmpeg, python venv)…"
sudo apt-get update -y
sudo apt-get install -y ffmpeg python3-venv python3-pip fonts-dejavu-core

echo ">> Creating virtualenv…"
python3 -m venv "$APP_DIR/.venv"
# shellcheck disable=SC1091
source "$APP_DIR/.venv/bin/activate"
pip install --upgrade pip
pip install -r "$APP_DIR/requirements.txt"

if [ ! -f "$APP_DIR/.env" ]; then
  echo ">> No .env found — copying template. EDIT IT with your keys:"
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "   nano $APP_DIR/.env"
fi

echo ">> Installing systemd service…"
SERVICE=/etc/systemd/system/xbot.service
sudo tee "$SERVICE" >/dev/null <<EOF
[Unit]
Description=X/TikTok viral clip bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/bot.py
Restart=always
RestartSec=10
User=$USER

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable xbot
echo ">> Done. After editing .env, start with:  sudo systemctl start xbot"
echo ">> Logs:  journalctl -u xbot -f"
