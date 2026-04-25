"""
Audit-log helper. Records security-relevant actions to the audit_log table.

Designed to never raise — a failure to write the audit log should not break
the user-facing operation. Failures are logged at WARNING and dropped.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.database.models import AuditLog
from app.services.net import client_ip as _client_ip

logger = logging.getLogger(__name__)


def log_audit(
    db: Session,
    *,
    action: str,
    actor: Optional[dict] = None,
    target_type: Optional[str] = None,
    target_id: Optional[object] = None,
    detail: Optional[str] = None,
    workspace_id: Optional[int] = None,
    request: Optional[Request] = None,
) -> None:
    """
    Record an audit event. Safe to call inside a transaction; commits its own row.
    Never raises — failures are logged and swallowed so the calling endpoint
    is unaffected.

    `actor` is the dict returned by `get_current_user` (has username, role,
    workspace_id, org_id). For unauthenticated events (e.g. failed login),
    pass actor=None and pass `detail` with the attempted username.
    """
    try:
        actor = actor or {}
        row = AuditLog(
            action=action,
            actor_username=(actor.get("username") or None),
            actor_role=(actor.get("role") or None),
            workspace_id=workspace_id if workspace_id is not None else actor.get("workspace_id"),
            org_id=actor.get("org_id"),
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            detail=detail,
            ip_address=_client_ip(request),
        )
        db.add(row)
        db.commit()
    except Exception as e:
        logger.warning("audit log write failed (%s): %s", action, e)
        try:
            db.rollback()
        except Exception:
            pass
