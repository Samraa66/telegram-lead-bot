#!/bin/bash
# Run on the VPS to install the systemd service and restart the bot.
# Usage: bash scripts/deploy_service.sh

set -e

SERVICE_FILE=/etc/systemd/system/telegrambot.service

cat > "$SERVICE_FILE" << SERVICE
[Unit]
Description=Telegram CRM Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/telegram-lead-bot/backend
EnvironmentFile=/root/telegram-lead-bot/backend/.env
ExecStart=/root/telegram-lead-bot/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

echo "Service file written."

systemctl daemon-reload
systemctl restart telegrambot
sleep 3

echo "Health check:"
curl -s http://localhost:8000/health
echo ""
echo "Done. Check status with: systemctl status telegrambot"
