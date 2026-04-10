"""
Telethon listener layer tests — in-memory SQLite, no real Telegram connection.

Tests:
  1. Inbound DM from new user → contact created at stage 1 / new_lead
  2. Inbound DM from existing contact → last_seen updated, message saved
  3. /start with source param → source stored on contact
  4. handle_outbound with keyword → stage advances
  5. handle_outbound without keyword → stage unchanged, message still saved
  6. handle_outbound for unknown contact → graceful no-op
  7. Dedup: same outbound text within 30s is skipped (no double transition)
  8. Inbound message cancels follow-ups (follow_up_queue cleared)

Run from backend/:
    python -m scripts.test_listener
"""

import sys, os, asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from telethon.tl.types import User as TLUser

from app.database.models import Base, Contact, Message, StageHistory, FollowUpQueue
from app.handlers.outbound import handle_outbound

# ---------------------------------------------------------------------------
# In-memory DB
# ---------------------------------------------------------------------------

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=engine)
Session = sessionmaker(bind=engine)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


def clean_db(db, contact_id: int):
    db.query(StageHistory).filter(StageHistory.contact_id == contact_id).delete()
    db.query(Message).filter(Message.user_id == contact_id).delete()
    db.query(FollowUpQueue).filter(FollowUpQueue.contact_id == contact_id).delete()
    db.query(Contact).filter(Contact.id == contact_id).delete()
    db.commit()


def make_tl_user(user_id: int, username="test", first="Test", last="User") -> TLUser:
    """Create a minimal Telethon User object for mocking."""
    u = MagicMock(spec=TLUser)
    u.id = user_id
    u.username = username
    u.first_name = first
    u.last_name = last
    u.bot = False
    return u


def make_inbound_event(user_id: int, text: str):
    """Mock a Telethon inbound NewMessage event."""
    event = AsyncMock()
    event.is_private = True
    event.message.text = text
    tl_user = make_tl_user(user_id)
    event.get_sender = AsyncMock(return_value=tl_user)
    return event


def make_outbound_event(user_id: int, text: str):
    """Mock a Telethon outbound NewMessage event."""
    event = AsyncMock()
    event.is_private = True
    event.message.text = text
    tl_user = make_tl_user(user_id)
    event.get_chat = AsyncMock(return_value=tl_user)
    return event


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_inbound_new_contact():
    print("\n=== Test 1: Inbound DM from new user → contact created ===")
    from app.services import telethon_client

    db = Session()
    clean_db(db, 1001)
    db.close()

    event = make_inbound_event(1001, "hello i want to join")

    with patch("app.services.telethon_client.SessionLocal", return_value=Session()), \
         patch("app.services.telethon_client.cancel_follow_ups"), \
         patch("app.services.scheduler.schedule_follow_ups"):
        run(telethon_client._on_new_message(event))

    db = Session()
    contact = db.query(Contact).filter(Contact.id == 1001).first()
    msg = db.query(Message).filter(Message.user_id == 1001).first()

    ok1 = check("Contact created in DB", contact is not None)
    ok2 = check(f"Stage = 1 (got {contact.current_stage if contact else '?'})", contact and contact.current_stage == 1)
    ok3 = check(f"Classification = new_lead (got {contact.classification if contact else '?'})", contact and contact.classification == "new_lead")
    ok4 = check("Inbound message saved", msg is not None)
    ok5 = check(f"Message direction = inbound (got {msg.direction if msg else '?'})", msg and msg.direction == "inbound")
    db.close()
    return all([ok1, ok2, ok3, ok4, ok5])


def test_inbound_existing_contact():
    print("\n=== Test 2: Inbound DM from existing contact → last_seen updated ===")
    from app.services import telethon_client

    db = Session()
    clean_db(db, 1002)
    old_time = datetime(2024, 1, 1)
    db.add(Contact(
        id=1002, username="existing", first_name="Existing", last_name="Lead",
        current_stage=3, classification="warm_lead",
        deposit_confirmed=False, is_affiliate=False, escalated=False,
        last_seen=old_time,
    ))
    db.commit()
    db.close()

    event = make_inbound_event(1002, "still thinking about it")

    with patch("app.services.telethon_client.SessionLocal", return_value=Session()), \
         patch("app.services.telethon_client.cancel_follow_ups"):
        run(telethon_client._on_new_message(event))

    db = Session()
    contact = db.query(Contact).filter(Contact.id == 1002).first()
    msg_count = db.query(Message).filter(Message.user_id == 1002).count()

    ok1 = check("Contact still exists", contact is not None)
    ok2 = check("last_seen updated past 2024", contact and contact.last_seen > old_time)
    ok3 = check(f"Stage unchanged at 3 (got {contact.current_stage if contact else '?'})", contact and contact.current_stage == 3)
    ok4 = check(f"Message saved (got {msg_count})", msg_count == 1)
    db.close()
    return all([ok1, ok2, ok3, ok4])


def test_inbound_start_source():
    print("\n=== Test 3: /start with source param → source stored ===")
    from app.services import telethon_client

    db = Session()
    clean_db(db, 1003)
    db.close()

    event = make_inbound_event(1003, "/start meta_jan_2025")

    with patch("app.services.telethon_client.SessionLocal", return_value=Session()), \
         patch("app.services.telethon_client.cancel_follow_ups"), \
         patch("app.services.scheduler.schedule_follow_ups"):
        run(telethon_client._on_new_message(event))

    db = Session()
    contact = db.query(Contact).filter(Contact.id == 1003).first()
    ok = check(f"Source = 'meta_jan_2025' (got '{contact.source if contact else '?'}')", contact and contact.source == "meta_jan_2025")
    db.close()
    return ok


def test_outbound_keyword_advances_stage():
    print("\n=== Test 4: Outbound keyword message → stage advances ===")
    db = Session()
    clean_db(db, 1004)
    db.add(Contact(
        id=1004, username="lead", first_name="Lead", last_name="Four",
        current_stage=1, classification="new_lead",
        deposit_confirmed=False, is_affiliate=False, escalated=False,
    ))
    db.commit()

    new_stage = handle_outbound(db, 1004, "Do you have any experience trading?")

    db.refresh(db.query(Contact).filter(Contact.id == 1004).first())
    contact = db.query(Contact).filter(Contact.id == 1004).first()
    history = db.query(StageHistory).filter(StageHistory.contact_id == 1004).all()

    ok1 = check(f"handle_outbound returned stage 2 (got {new_stage})", new_stage == 2)
    ok2 = check(f"Contact now at stage 2 (got {contact.current_stage})", contact.current_stage == 2)
    ok3 = check(f"Classification = warm_lead (got {contact.classification})", contact.classification == "warm_lead")
    ok4 = check(f"Stage history row recorded (got {len(history)})", len(history) == 1)
    db.close()
    return all([ok1, ok2, ok3, ok4])


def test_outbound_no_keyword():
    print("\n=== Test 5: Outbound without keyword → stage unchanged, message saved ===")
    db = Session()
    clean_db(db, 1005)
    db.add(Contact(
        id=1005, username="lead5", first_name="Lead", last_name="Five",
        current_stage=2, classification="warm_lead",
        deposit_confirmed=False, is_affiliate=False, escalated=False,
    ))
    db.commit()

    result = handle_outbound(db, 1005, "Hey, just checking in!")

    contact = db.query(Contact).filter(Contact.id == 1005).first()
    msg = db.query(Message).filter(Message.user_id == 1005).first()

    ok1 = check(f"Returns None (got {result})", result is None)
    ok2 = check(f"Stage unchanged at 2 (got {contact.current_stage})", contact.current_stage == 2)
    ok3 = check("Message saved anyway", msg is not None)
    db.close()
    return all([ok1, ok2, ok3])


def test_outbound_unknown_contact():
    print("\n=== Test 6: Outbound to unknown contact → graceful no-op ===")
    db = Session()
    clean_db(db, 9999)

    result = handle_outbound(db, 9999, "any experience trading")

    ok = check(f"Returns None for unknown contact (got {result})", result is None)
    db.close()
    return ok


def test_outbound_dedup():
    print("\n=== Test 7: Dedup — same outbound text within 30s is skipped ===")
    from app.services import telethon_client

    db = Session()
    clean_db(db, 1006)
    db.add(Contact(
        id=1006, username="lead6", first_name="Lead", last_name="Six",
        current_stage=1, classification="new_lead",
        deposit_confirmed=False, is_affiliate=False, escalated=False,
    ))
    # Pre-save the same message as if /send-message already handled it
    db.add(Message(
        user_id=1006,
        message_text="any experience trading",
        content="any experience trading",
        direction="outbound",
        sender="operator",
        timestamp=datetime.utcnow(),
    ))
    db.commit()
    db.close()

    event = make_outbound_event(1006, "any experience trading")

    with patch("app.services.telethon_client.SessionLocal", return_value=Session()):
        run(telethon_client._on_outgoing_message(event))

    db = Session()
    contact = db.query(Contact).filter(Contact.id == 1006).first()
    history = db.query(StageHistory).filter(StageHistory.contact_id == 1006).all()

    ok1 = check(f"Stage still 1 — dedup blocked transition (got {contact.current_stage})", contact.current_stage == 1)
    ok2 = check(f"No stage history rows (got {len(history)})", len(history) == 0)
    db.close()
    return ok1 and ok2


def test_inbound_cancels_followups():
    print("\n=== Test 8: Inbound message cancels pending follow-ups ===")
    from app.services import telethon_client

    db = Session()
    clean_db(db, 1007)
    db.add(Contact(
        id=1007, username="lead7", first_name="Lead", last_name="Seven",
        current_stage=2, classification="warm_lead",
        deposit_confirmed=False, is_affiliate=False, escalated=False,
        last_seen=datetime.utcnow(),
    ))
    db.add(FollowUpQueue(
        contact_id=1007,
        stage=2,
        sequence_num=1,
        scheduled_at=datetime.utcnow() + timedelta(hours=1),
        status="pending",
    ))
    db.commit()
    db.close()

    event = make_inbound_event(1007, "im interested")

    with patch("app.services.telethon_client.SessionLocal", return_value=Session()), \
         patch("app.services.telethon_client.cancel_follow_ups") as mock_cancel:
        run(telethon_client._on_new_message(event))

    ok = check("cancel_follow_ups called for contact", mock_cancel.called and mock_cancel.call_args[0][0] == 1007)
    return ok


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def main():
    results = [
        test_inbound_new_contact(),
        test_inbound_existing_contact(),
        test_inbound_start_source(),
        test_outbound_keyword_advances_stage(),
        test_outbound_no_keyword(),
        test_outbound_unknown_contact(),
        test_outbound_dedup(),
        test_inbound_cancels_followups(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*45}")
    print(f"Results: {passed}/{total} test groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
