"""
Tests for process_deposit_event(). Run from backend/:
    python -m scripts.test_deposit_event
"""

import os, sys, hashlib, hmac, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("APP_ENV", "development")  # prevents SECRET_KEY hard-fail in config

from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models import (
    Base, Organization, Workspace, Contact, DepositEvent, StageHistory,
)
from app.services.pipeline_seed import seed_default_pipeline
from app.services.deposit import process_deposit_event, find_contact_for_deposit

PASS = "\033[92mPASS\033[0m"; FAIL = "\033[91mFAIL\033[0m"
def check(label, cond):
    print(f"  [{PASS if cond else FAIL}] {label}")
    return cond


def setup():
    """Create a fresh in-memory SQLite engine per test to ensure isolation."""
    _engine = create_engine("sqlite:///:memory:",
                            connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=_engine)
    _Session = sessionmaker(bind=_engine)
    db = _Session()
    db.add(Organization(id=1, name="T")); db.commit()
    db.add(Workspace(id=1, name="T", org_id=1, root_workspace_id=1, workspace_role="owner"))
    db.commit()
    seed_default_pipeline(1, db)
    db.add(Contact(id=42, workspace_id=1, current_stage=1, deposit_status="none",
                   first_seen=datetime.utcnow(), last_seen=datetime.utcnow()))
    db.commit()
    return db


def test_first_deposit_promotes():
    print("\n=== First-time deposit promotes contact to deposited stage ===")
    db = setup()
    contact = db.query(Contact).filter(Contact.id == 42).first()
    result = process_deposit_event(
        db, workspace_id=1, contact=contact,
        provider="manual", source="manual",
        idempotency_key="test-1", amount=500.0, currency="USD",
    )
    db.refresh(contact)
    ws = db.query(Workspace).filter(Workspace.id == 1).first()
    ok1 = check("not deduped", not result.dedup)
    ok2 = check("contact.deposit_status='deposited'", contact.deposit_status == "deposited")
    ok3 = check("contact moved to deposit stage", contact.current_stage_id == ws.deposited_stage_id)
    ok4 = check("amount/currency saved", float(contact.deposit_amount) == 500.0 and contact.deposit_currency == "USD")
    ok5 = check("StageHistory row written with moved_by='deposit_event'",
                db.query(StageHistory).filter(StageHistory.contact_id == 42,
                StageHistory.moved_by == "deposit_event").count() == 1)
    db.close()
    return all([ok1, ok2, ok3, ok4, ok5])


def test_idempotent():
    print("\n=== Same idempotency_key dedupes ===")
    db = setup()
    contact = db.query(Contact).filter(Contact.id == 42).first()
    process_deposit_event(db, workspace_id=1, contact=contact,
        provider="puprime", source="email_parser", idempotency_key="dup-1", amount=100)
    result2 = process_deposit_event(db, workspace_id=1, contact=contact,
        provider="puprime", source="email_parser", idempotency_key="dup-1", amount=100)
    rows = db.query(DepositEvent).filter(DepositEvent.contact_id == 42).count()
    ok1 = check("only 1 DepositEvent stored", rows == 1)
    ok2 = check("second call returned dedup=True", result2.dedup is True)
    db.close()
    return ok1 and ok2


def test_find_by_puprime_id():
    print("\n=== find_contact_for_deposit by puprime_client_id ===")
    db = setup()
    contact = db.query(Contact).filter(Contact.id == 42).first()
    contact.puprime_client_id = "PU-9999"
    db.commit()
    found = find_contact_for_deposit(db, 1, puprime_client_id="PU-9999")
    ok = check("matched by puprime id", found is not None and found.id == 42)
    db.close()
    return ok


def test_signature_helper():
    print("\n=== HMAC signature helper sanity ===")
    from app.main import _verify_deposit_signature
    body = b'{"a":1}'
    secret = "topsecret"
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    ok1 = check("valid sig accepted", _verify_deposit_signature(secret, body, sig))
    ok2 = check("tampered sig rejected", not _verify_deposit_signature(secret, body, sig[:-1] + "0"))
    return ok1 and ok2


def main():
    results = [test_first_deposit_promotes(), test_idempotent(),
               test_find_by_puprime_id(), test_signature_helper()]
    print(f"\n{'='*45}\nResults: {sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
