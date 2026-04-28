"""
One-shot backup of the existing single-tenant data (workspace_id=1) into a JSON
file that can be re-imported manually or kept as an audit trail.

Run from backend/:
    python -m scripts.backup_legacy_workspace                # dumps to backups/legacy-workspace-YYYY-MM-DD.json
    python -m scripts.backup_legacy_workspace --out file.json
"""

import argparse
import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, init_db


def _row_to_dict(row) -> dict:
    out = {}
    for col in row.__table__.columns:
        v = getattr(row, col.name)
        if isinstance(v, (datetime, date)):
            v = v.isoformat()
        elif isinstance(v, bytes):
            v = v.decode("utf-8", errors="replace")
        out[col.name] = v
    return out


def dump(out_path: str) -> None:
    from app.database.models import (
        Contact, Message, StageHistory, FollowUpQueue, FollowUpTemplate,
        StageKeyword, StageLabel, QuickReply, Workspace, Organization,
        TeamMember, Affiliate, Campaign, AdCampaign, AdCreative, PendingChannel,
        AuditLog,
    )
    init_db()
    db = SessionLocal()
    try:
        out: dict[str, list[dict]] = {}
        for table in [
            Organization, Workspace, Contact, Message, StageHistory,
            FollowUpQueue, FollowUpTemplate, StageKeyword, StageLabel, QuickReply,
            TeamMember, Affiliate, Campaign, AdCampaign, AdCreative, PendingChannel,
            AuditLog,
        ]:
            rows = db.query(table).all()
            out[table.__tablename__] = [_row_to_dict(r) for r in rows]
            print(f"  dumped {len(rows):>5} rows from {table.__tablename__}")
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(out, f, indent=2, default=str)
        print(f"\nBackup written to {out_path}")
        print(f"Total tables: {len(out)}")
    finally:
        db.close()


def main():
    ap = argparse.ArgumentParser()
    default = f"backups/legacy-workspace-{date.today().isoformat()}.json"
    ap.add_argument("--out", default=default)
    args = ap.parse_args()
    dump(args.out)


if __name__ == "__main__":
    main()
