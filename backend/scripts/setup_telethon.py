"""
One-time setup: creates the Telethon session file for the operator account.

Run once on the VPS:
    cd ~/telegram-lead-bot/backend
    source ~/telegram-lead-bot/venv/bin/activate
    python scripts/setup_telethon.py

You will be prompted for the operator's phone number and the OTP Telegram sends.
The session is saved to operator.session — never commit this file.
"""

import asyncio
import os
import sys
from pathlib import Path

# Allow running from the backend/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from telethon import TelegramClient

API_ID = int(os.getenv("TELEGRAM_API_ID", "0") or "0")
API_HASH = os.getenv("TELEGRAM_API_HASH", "").strip()
SESSION_FILE = str(Path(__file__).parent.parent / "operator.session")


async def main() -> None:
    if not API_ID or not API_HASH:
        print("ERROR: TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env")
        sys.exit(1)

    print(f"Creating session at: {SESSION_FILE}")
    print("You will receive a login code on the operator's Telegram account.\n")

    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.start()

    me = await client.get_me()
    print(f"\nSuccess! Logged in as: {me.first_name} (@{me.username})")
    print(f"Phone: +{me.phone}")
    print(f"Session saved to: {SESSION_FILE}")
    print("\nRestart the bot service to activate Telethon:")
    print("  systemctl restart telegrambot")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
