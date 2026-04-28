"""
Test the per-workspace signal handler factory.

Run from backend/:
    python -m scripts.test_signal_handler
"""

import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import asyncio

from app.services.telethon_client import _make_signal_handler

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label, condition):
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


async def run():
    print("Test 1: handler closure captures workspace_id")
    handler = _make_signal_handler(workspace_id=42)
    check("returns a coroutine function", asyncio.iscoroutinefunction(handler))

    print("\nTest 2: handler calls copy_signal_for_org with workspace_id and event ids")
    fake_event = MagicMock()
    fake_event.chat_id = -1009999
    fake_event.message.id = 777

    captured = {}
    def fake_copy(workspace_id, source_chat_id, message_id, db):
        captured["ws"] = workspace_id
        captured["src"] = source_chat_id
        captured["msg"] = message_id

    with patch("app.services.telethon_client.copy_signal_for_org", side_effect=fake_copy), \
         patch("app.services.telethon_client.SessionLocal") as mock_sl:
        mock_sl.return_value = MagicMock()
        mock_sl.return_value.close = MagicMock()
        await handler(fake_event)

    check("workspace_id passed through", captured.get("ws") == 42)
    check("source_chat_id passed through", captured.get("src") == "-1009999")
    check("message_id passed through", captured.get("msg") == 777)


if __name__ == "__main__":
    print("Signal handler tests")
    asyncio.run(run())
    print("\nDone.")
