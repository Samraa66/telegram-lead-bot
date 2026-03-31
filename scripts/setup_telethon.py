"""
One-time interactive script to authenticate the Telethon operator session.
Run this manually on the VPS — it will prompt for phone number and OTP.
The session is saved to backend/operator.session and picked up automatically
by the server on next restart.

Usage:
    cd /root/telegram-lead-bot
    source venv/bin/activate
    python scripts/setup_telethon.py
"""

import asyncio
import os
import sys

# Allow imports from backend/app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))

from telethon import TelegramClient

API_ID = int(os.getenv("TELEGRAM_API_ID", "0") or "0")
API_HASH = os.getenv("TELEGRAM_API_HASH", "").strip()
SESSION_FILE = os.path.join(
    os.path.dirname(__file__), "..", "backend", "operator.session"
)


async def main():
    if not API_ID or not API_HASH:
        print("ERROR: TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in backend/.env")
        sys.exit(1)

    print(f"Session will be saved to: {os.path.abspath(SESSION_FILE)}")
    print("You will be prompted for your phone number and the OTP sent to your Telegram app.\n")

    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.start()

    me = await client.get_me()
    print(f"\nSuccess! Logged in as: {me.first_name} (@{me.username})")
    print("Session saved. Restart the service to activate the Telethon listener:")
    print("  sudo systemctl restart telegrambot")

    await client.disconnect()


asyncio.run(main())
