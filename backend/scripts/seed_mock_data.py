"""
Seed mock contacts, messages, and stage history for local testing.
Run from the backend/ directory: python scripts/seed_mock_data.py

Creates 8 contacts — one per stage — with realistic message threads
and stage history so the full UI can be exercised.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from app.database import SessionLocal, init_db
from app.database.models import Contact, Message, StageHistory

init_db()
db = SessionLocal()

# Wipe existing mock data (ids 1000–1099 range so real data is safe)
MOCK_IDS = list(range(1001, 1009))
db.query(StageHistory).filter(StageHistory.contact_id.in_(MOCK_IDS)).delete(synchronize_session=False)
db.query(Message).filter(Message.user_id.in_(MOCK_IDS)).delete(synchronize_session=False)
db.query(Contact).filter(Contact.id.in_(MOCK_IDS)).delete(synchronize_session=False)
db.commit()

NOW = datetime.utcnow()

def ago(hours=0, days=0):
    return NOW - timedelta(hours=hours, days=days)

# ── contacts ────────────────────────────────────────────────────────────────
contacts_data = [
    dict(id=1001, username="ahmed_fx",      source="instagram_bio", classification="new_lead",  current_stage=1, stage_entered_at=ago(hours=30), first_seen=ago(hours=31)),
    dict(id=1002, username="sara_trades",   source="tiktok_link",   classification="warm_lead", current_stage=2, stage_entered_at=ago(hours=20), first_seen=ago(days=3)),
    dict(id=1003, username="mike_profits",  source="instagram_bio", classification="warm_lead", current_stage=3, stage_entered_at=ago(days=4),   first_seen=ago(days=6)),
    dict(id=1004, username="lina_uae",      source="tiktok_link",   classification="warm_lead", current_stage=4, stage_entered_at=ago(hours=10), first_seen=ago(days=5)),
    dict(id=1005, username="omar_invest",   source="instagram_bio", classification="warm_lead", current_stage=5, stage_entered_at=ago(hours=18), first_seen=ago(days=7)),
    dict(id=1006, username="nour_trading",  source="tiktok_link",   classification="warm_lead", current_stage=6, stage_entered_at=ago(hours=5),  first_seen=ago(days=8)),
    dict(id=1007, username="khalid_vip",    source="instagram_bio", classification="vip",       current_stage=7, stage_entered_at=ago(hours=2),  first_seen=ago(days=10), deposit_confirmed=True),
    dict(id=1008, username="fatima_elite",  source="tiktok_link",   classification="vip",       current_stage=8, stage_entered_at=ago(hours=50), first_seen=ago(days=14), deposit_confirmed=True),
]

for d in contacts_data:
    db.add(Contact(
        id=d["id"],
        username=d["username"],
        source=d.get("source"),
        classification=d["classification"],
        current_stage=d["current_stage"],
        stage_entered_at=d["stage_entered_at"],
        first_seen=d.get("first_seen", NOW),
        last_seen=NOW,
        deposit_confirmed=d.get("deposit_confirmed", False),
        notes=d.get("notes", ""),
    ))

db.commit()
print(f"✓ {len(contacts_data)} contacts created")

# ── messages ────────────────────────────────────────────────────────────────
def msg(user_id, text, direction, sender, when):
    return Message(
        user_id=user_id,
        message_text=text,
        content=text,
        direction=direction,
        sender=sender,
        timestamp=when,
    )

messages = [
    # Ahmed — Stage 1 (new, just joined)
    msg(1001, "/start instagram_bio",                                       "inbound",  "system",   ago(hours=31)),
    msg(1001, "Hi! Send your message to Walid to join the VIP.",            "outbound", "operator", ago(hours=31)),
    msg(1001, "Hey, I saw your post about trading. Tell me more",           "inbound",  "system",   ago(hours=30)),
    msg(1001, "Thanks, your request was sent.",                             "outbound", "operator", ago(hours=30)),

    # Sara — Stage 2 (qualified)
    msg(1002, "/start tiktok_link",                                         "inbound",  "system",   ago(days=3)),
    msg(1002, "Hi! Send your message to Walid to join the VIP.",            "outbound", "operator", ago(days=3)),
    msg(1002, "I'm interested in learning more",                            "inbound",  "system",   ago(days=3, hours=1)),
    msg(1002, "Do you have any experience trading?",                        "outbound", "operator", ago(days=3, hours=2)),
    msg(1002, "A little bit, mostly crypto",                                "inbound",  "system",   ago(hours=22)),

    # Mike — Stage 3 (hesitant)
    msg(1003, "/start instagram_bio",                                       "inbound",  "system",   ago(days=6)),
    msg(1003, "Do you have any experience trading?",                        "outbound", "operator", ago(days=5)),
    msg(1003, "Yes I have tried forex before",                              "inbound",  "system",   ago(days=5)),
    msg(1003, "Is there something specific holding you back?",              "outbound", "operator", ago(days=5)),
    msg(1003, "I lost money before so I'm a bit scared",                    "inbound",  "system",   ago(days=4, hours=2)),
    msg(1003, "That's completely understandable",                           "outbound", "operator", ago(days=4)),

    # Lina — Stage 4 (link sent)
    msg(1004, "/start tiktok_link",                                         "inbound",  "system",   ago(days=5)),
    msg(1004, "Do you have any experience trading?",                        "outbound", "operator", ago(days=4)),
    msg(1004, "No but I want to learn",                                     "inbound",  "system",   ago(days=4)),
    msg(1004, "Is there something specific holding you back?",              "outbound", "operator", ago(days=4)),
    msg(1004, "Just not sure where to start",                               "inbound",  "system",   ago(days=3)),
    msg(1004, "Here is your link to open your free PuPrime account",        "outbound", "operator", ago(hours=10)),

    # Omar — Stage 5 (account created)
    msg(1005, "/start instagram_bio",                                       "inbound",  "system",   ago(days=7)),
    msg(1005, "Here is your link to open your free PuPrime account",        "outbound", "operator", ago(days=2)),
    msg(1005, "Done! I created my account",                                 "inbound",  "system",   ago(days=1)),
    msg(1005, "That's the hard part done, well done!",                      "outbound", "operator", ago(hours=18)),

    # Nour — Stage 6 (deposit intent)
    msg(1006, "/start tiktok_link",                                         "inbound",  "system",   ago(days=8)),
    msg(1006, "That's the hard part done, well done!",                      "outbound", "operator", ago(days=2)),
    msg(1006, "Thanks, what's next?",                                       "inbound",  "system",   ago(days=1)),
    msg(1006, "I'll show you exactly how to get set up with a deposit",     "outbound", "operator", ago(hours=5)),

    # Khalid — Stage 7 (deposited)
    msg(1007, "/start instagram_bio",                                       "inbound",  "system",   ago(days=10)),
    msg(1007, "I'll show you exactly how to get set up with a deposit",     "outbound", "operator", ago(days=3)),
    msg(1007, "Done! I deposited $500",                                     "inbound",  "system",   ago(hours=3)),
    msg(1007, "Welcome to the VIP room Khalid! 🎉",                         "outbound", "operator", ago(hours=2)),

    # Fatima — Stage 8 (VIP member)
    msg(1008, "/start tiktok_link",                                         "inbound",  "system",   ago(days=14)),
    msg(1008, "Welcome to the VIP room Fatima! 🎉",                         "outbound", "operator", ago(days=3)),
    msg(1008, "Thank you so much!",                                         "inbound",  "system",   ago(days=3)),
    msg(1008, "Really happy to have you here, let's make you some money!",  "outbound", "operator", ago(days=2)),
    msg(1008, "Looking forward to it!",                                     "inbound",  "system",   ago(hours=50)),
]

for m in messages:
    db.add(m)
db.commit()
print(f"✓ {len(messages)} messages created")

# ── stage history ────────────────────────────────────────────────────────────
history = [
    # Sara: 1→2
    StageHistory(contact_id=1002, from_stage=1, to_stage=2, moved_at=ago(days=3, hours=2), moved_by="system", trigger_keyword="any experience trading"),
    # Mike: 1→2→3
    StageHistory(contact_id=1003, from_stage=1, to_stage=2, moved_at=ago(days=5),          moved_by="system", trigger_keyword="any experience trading"),
    StageHistory(contact_id=1003, from_stage=2, to_stage=3, moved_at=ago(days=5),          moved_by="system", trigger_keyword="is there something specific holding you back"),
    # Lina: 1→2→3→4
    StageHistory(contact_id=1004, from_stage=1, to_stage=2, moved_at=ago(days=4),          moved_by="system", trigger_keyword="any experience trading"),
    StageHistory(contact_id=1004, from_stage=2, to_stage=3, moved_at=ago(days=3),          moved_by="system", trigger_keyword="is there something specific holding you back"),
    StageHistory(contact_id=1004, from_stage=3, to_stage=4, moved_at=ago(hours=10),        moved_by="system", trigger_keyword="your link to open your free puprime account"),
    # Omar: 1→4→5
    StageHistory(contact_id=1005, from_stage=1, to_stage=4, moved_at=ago(days=2),          moved_by="system", trigger_keyword="your link to open your free puprime account"),
    StageHistory(contact_id=1005, from_stage=4, to_stage=5, moved_at=ago(hours=18),        moved_by="system", trigger_keyword="the hard part done"),
    # Nour: 1→5→6
    StageHistory(contact_id=1006, from_stage=1, to_stage=5, moved_at=ago(days=2),          moved_by="system", trigger_keyword="the hard part done"),
    StageHistory(contact_id=1006, from_stage=5, to_stage=6, moved_at=ago(hours=5),         moved_by="system", trigger_keyword="exactly how to get set up"),
    # Khalid: 1→4→5→6→7
    StageHistory(contact_id=1007, from_stage=1, to_stage=4, moved_at=ago(days=3),          moved_by="system", trigger_keyword="your link to open your free puprime account"),
    StageHistory(contact_id=1007, from_stage=4, to_stage=6, moved_at=ago(days=2),          moved_by="system", trigger_keyword="exactly how to get set up"),
    StageHistory(contact_id=1007, from_stage=6, to_stage=7, moved_at=ago(hours=2),         moved_by="system", trigger_keyword="welcome to the vip room"),
    # Fatima: 1→7→8
    StageHistory(contact_id=1008, from_stage=1, to_stage=7, moved_at=ago(days=3),          moved_by="system", trigger_keyword="welcome to the vip room"),
    StageHistory(contact_id=1008, from_stage=7, to_stage=8, moved_at=ago(days=2),          moved_by="system", trigger_keyword="really happy to have you here"),
]

for h in history:
    db.add(h)
db.commit()
print(f"✓ {len(history)} stage history rows created")

db.close()
print("\n✅ Mock data ready. Start the backend and open the frontend.")
