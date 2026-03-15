#!/usr/bin/env python3
"""
Send a message to a Telegram chat using the bot token.

Usage:
  python scripts/send_message.py <chat_id> <message>
  BOT_TOKEN=xxx python scripts/send_message.py 123456 "Hello"

Requires BOT_TOKEN in environment or .env in project root.
"""

import os
import sys

# Allow running from project root; load .env from project root
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, ".env"))

import requests

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("Error: BOT_TOKEN not set. Set it in .env or environment.")
    sys.exit(1)

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_message(chat_id: str, text: str) -> bool:
    url = f"{TELEGRAM_API}/sendMessage"
    r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    if r.status_code != 200:
        print(r.text)
        return False
    print("Message sent successfully.")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python send_message.py <chat_id> <message>")
        sys.exit(1)
    chat_id = sys.argv[1]
    message = " ".join(sys.argv[2:])
    ok = send_message(chat_id, message)
    sys.exit(0 if ok else 1)
