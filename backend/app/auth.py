"""
JWT authentication for the CRM dashboard.

Three roles (highest → lowest privilege):
  developer  — full access, can tag affiliates
  admin      — full CRM access, can tag affiliates (business owner)
  operator   — lead management only, no affiliate tagging

Credentials are stored in .env and never committed.
Token expiry: 24 hours.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Literal

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    DEVELOPER_PASSWORD,
    DEVELOPER_USERNAME,
    OPERATOR_PASSWORD,
    OPERATOR_USERNAME,
    SECRET_KEY,
)

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

Role = Literal["developer", "admin", "operator"]

_security = HTTPBearer()


def _user_map() -> dict:
    users = {}
    if DEVELOPER_USERNAME and DEVELOPER_PASSWORD:
        users[DEVELOPER_USERNAME] = {"password": DEVELOPER_PASSWORD, "role": "developer"}
    if ADMIN_USERNAME and ADMIN_PASSWORD:
        users[ADMIN_USERNAME] = {"password": ADMIN_PASSWORD, "role": "admin"}
    if OPERATOR_USERNAME and OPERATOR_PASSWORD:
        users[OPERATOR_USERNAME] = {"password": OPERATOR_PASSWORD, "role": "operator"}
    return users


def authenticate_user(username: str, password: str) -> dict | None:
    user = _user_map().get(username)
    if not user:
        return None
    if not secrets.compare_digest(password, user["password"]):
        return None
    return {"username": username, "role": user["role"]}


def create_access_token(username: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": username, "role": role, "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> dict:
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub", "")
        role: str = payload.get("role", "")
        if not username or not role:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"username": username, "role": role}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def require_roles(*roles: str):
    """Dependency that checks the current user has one of the given roles."""
    def _check(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return _check
