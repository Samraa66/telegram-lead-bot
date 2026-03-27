#!/usr/bin/env python3
"""
Set or remove the Telegram webhook (for local testing with ngrok or production).

Usage:
  # Set webhook (e.g. after starting ngrok: ngrok http 8000)
  python scripts/set_webhook.py https://your-ngrok-url.ngrok.io

  # Remove webhook
  python scripts/set_webhook.py --delete

Requires BOT_TOKEN in .env. Optional: WEBHOOK_SECRET for secret_token.
"""

import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, ".env"))

import requests

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def set_webhook(base_url: str) -> bool:
    """Set webhook to base_url/webhook. base_url should not end with /."""
    url = base_url.rstrip("/") + "/webhook"
    params = {"url": url}
    if WEBHOOK_SECRET:
        params["secret_token"] = WEBHOOK_SECRET
    r = requests.get(f"{BASE}/setWebhook", params=params, timeout=10)
    data = r.json()
    if data.get("ok"):
        print(f"Webhook set to {url}")
        return True
    print("Error:", data)
    return False


def delete_webhook() -> bool:
    r = requests.get(f"{BASE}/deleteWebhook", timeout=10)
    data = r.json()
    if data.get("ok"):
        print("Webhook removed.")
        return True
    print("Error:", data)
    return False


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN not set in .env")
        sys.exit(1)
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if sys.argv[1] in ("--delete", "-d"):
        ok = delete_webhook()
    else:
        ok = set_webhook(sys.argv[1])
    sys.exit(0 if ok else 1)
