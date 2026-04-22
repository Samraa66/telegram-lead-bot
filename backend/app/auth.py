"""
JWT authentication for the CRM dashboard.

Roles (highest → lowest privilege):
  developer    — full access
  admin        — full CRM access
  operator     — lead management only
  vip_manager  — members dashboard only
  affiliate    — self-service portal only (scoped to their own data)

Static credentials (developer/admin/operator/vip_manager) are stored in .env.
Affiliate credentials are generated on create and stored (hashed) in the DB.

Token expiry: 24 hours.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import (
    ADMIN_PASSWORD, ADMIN_USERNAME,
    VIP_MANAGER_PASSWORD, VIP_MANAGER_USERNAME,
    DEVELOPER_PASSWORD, DEVELOPER_USERNAME,
    OPERATOR_PASSWORD, OPERATOR_USERNAME,
    SECRET_KEY,
)

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

Role = Literal["developer", "admin", "operator", "vip_manager", "affiliate"]

_security = HTTPBearer()


# ---------------------------------------------------------------------------
# Password hashing (pbkdf2 — stdlib only)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Return a storable 'salt$hash' string."""
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000).hex()
    return f"{salt}${h}"


def verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored 'salt$hash' string."""
    try:
        salt, h = stored.split("$", 1)
        expected = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000).hex()
        return secrets.compare_digest(expected, h)
    except Exception:
        return False


def generate_password(length: int = 10) -> str:
    """Generate a readable random password (letters + digits, no ambiguous chars)."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ---------------------------------------------------------------------------
# Static user map (env-based roles)
# ---------------------------------------------------------------------------

def _user_map() -> dict:
    users = {}
    if DEVELOPER_USERNAME and DEVELOPER_PASSWORD:
        users[DEVELOPER_USERNAME] = {"password": DEVELOPER_PASSWORD, "role": "developer"}
    if ADMIN_USERNAME and ADMIN_PASSWORD:
        users[ADMIN_USERNAME] = {"password": ADMIN_PASSWORD, "role": "admin"}
    if OPERATOR_USERNAME and OPERATOR_PASSWORD:
        users[OPERATOR_USERNAME] = {"password": OPERATOR_PASSWORD, "role": "operator"}
    if VIP_MANAGER_USERNAME and VIP_MANAGER_PASSWORD:
        users[VIP_MANAGER_USERNAME] = {"password": VIP_MANAGER_PASSWORD, "role": "vip_manager"}
    return users


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def authenticate_user(username: str, password: str, db=None) -> Optional[dict]:
    """
    Check credentials against env-based users first, then DB affiliates.
    Returns dict with username, role, and optionally affiliate_id.
    """
    # Static roles
    user = _user_map().get(username)
    if user:
        if not secrets.compare_digest(password, user["password"]):
            return None
        return {"username": username, "role": user["role"]}

    # Team member (DB-backed: operator / vip_manager / admin)
    if db is not None:
        from app.database.models import TeamMember
        member = db.query(TeamMember).filter(
            TeamMember.username == username,
            TeamMember.is_active.is_(True),
        ).first()
        if member and verify_password(password, member.password_hash):
            return {"username": username, "role": member.role, "team_member_id": member.id}

    # Affiliate (DB-backed)
    if db is not None:
        from app.database.models import Affiliate
        aff = db.query(Affiliate).filter(
            Affiliate.login_username == username,
            Affiliate.is_active.is_(True),
        ).first()
        if aff and aff.login_password_hash and verify_password(password, aff.login_password_hash):
            return {"username": username, "role": "affiliate", "affiliate_id": aff.id}

    return None


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------

def create_access_token(
    username: str,
    role: str,
    workspace_id: int = 1,
    org_id: int = 1,
    org_role: str = "member",
    affiliate_id: Optional[int] = None,
) -> str:
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": username,
        "role": role,
        "workspace_id": workspace_id,
        "org_id": org_id,
        "org_role": org_role,
        "exp": expire,
    }
    if affiliate_id is not None:
        payload["affiliate_id"] = affiliate_id
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> dict:
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub", "")
        role: str = payload.get("role", "")
        if not username or not role:
            raise HTTPException(status_code=401, detail="Invalid token")
        result = {
            "username": username,
            "role": role,
            "workspace_id": int(payload.get("workspace_id", 1)),
            "org_id": int(payload.get("org_id", 1)),
            "org_role": payload.get("org_role", "member"),
        }
        if "affiliate_id" in payload:
            result["affiliate_id"] = payload["affiliate_id"]
        return result
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_workspace_id(current_user: dict = Depends(get_current_user)) -> int:
    """FastAPI dependency — returns the workspace_id from the current JWT."""
    return current_user.get("workspace_id", 1)


def get_org_id(current_user: dict = Depends(get_current_user)) -> int:
    """FastAPI dependency — returns the org_id from the current JWT."""
    return current_user.get("org_id", 1)


def require_org_owner(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Ensure the caller is an org owner.
    Accepts org_role=org_owner (new JWTs) OR role=developer/admin (legacy JWTs
    that predate the org_role claim — same people, just older tokens).
    """
    if (
        current_user.get("org_role") == "org_owner"
        or current_user.get("role") in ("developer", "admin")
    ):
        return current_user
    raise HTTPException(status_code=403, detail="Org owner access required")


def require_roles(*roles: str):
    """Dependency that checks the current user has one of the given roles."""
    def _check(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return _check


def require_affiliate(current_user: dict = Depends(get_current_user)) -> dict:
    """Dependency that ensures the caller is an authenticated affiliate."""
    if current_user["role"] != "affiliate" or "affiliate_id" not in current_user:
        raise HTTPException(status_code=403, detail="Affiliate access only")
    return current_user


# ---------------------------------------------------------------------------
# Telegram Login Widget verification
# ---------------------------------------------------------------------------

def verify_telegram_auth(data: dict, bot_token: str) -> bool:
    """
    Verify the auth data returned by the Telegram Login Widget.
    https://core.telegram.org/widgets/login#checking-authorization
    """
    received_hash = data.get("hash", "")
    auth_date = int(data.get("auth_date", 0))
    # Reject data older than 24 hours
    if time.time() - auth_date > 86400:
        return False
    check_fields = {k: v for k, v in data.items() if k != "hash"}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(check_fields.items()))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return secrets.compare_digest(computed, received_hash)
