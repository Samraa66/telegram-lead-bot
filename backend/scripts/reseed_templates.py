"""
Wipe and re-seed the follow_up_templates table with clean message text (no labels).
Run from the backend/ directory: python scripts/reseed_templates.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.database.models import FollowUpTemplate
from app.database import _TEMPLATE_SEEDS

db = SessionLocal()
try:
    deleted = db.query(FollowUpTemplate).delete()
    print(f"Deleted {deleted} existing template(s).")

    for stage, seq, text in _TEMPLATE_SEEDS:
        db.add(FollowUpTemplate(stage=stage, sequence_num=seq, message_text=text))

    db.commit()
    print(f"Inserted {len(_TEMPLATE_SEEDS)} clean template(s).")
finally:
    db.close()
