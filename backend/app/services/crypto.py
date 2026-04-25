"""
Symmetric encryption for sensitive DB columns (bot tokens, Telethon sessions,
webhook secrets, Meta access tokens).

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` library.

Key handling:
  - Production:  ENCRYPTION_KEY env var REQUIRED. Must be a 32-byte urlsafe-base64
                 string (Fernet's native format). Generate with:
                 python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  - Development: if ENCRYPTION_KEY is missing AND APP_ENV != production, falls back
                 to a deterministic dev-only key so local dev databases keep working
                 without an .env. Never used in production.

Versioning:
  Every ciphertext is prefixed with "enc:v1:" so we can spot encrypted vs legacy
  plaintext at a glance and rotate the algorithm in the future without breaking
  existing rows.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

ENC_PREFIX = "enc:v1:"
_DEV_FALLBACK_SEED = b"telelytics-dev-only-do-not-use-in-prod"


def _resolve_key() -> bytes:
    """Resolve the Fernet key from env, with a dev-only deterministic fallback."""
    raw = os.getenv("ENCRYPTION_KEY", "").strip()
    app_env = os.getenv("APP_ENV", "production").strip().lower()
    if raw:
        # Validate by attempting to construct a Fernet — raises if malformed
        try:
            Fernet(raw.encode())
            return raw.encode()
        except Exception as e:
            raise RuntimeError(
                f"ENCRYPTION_KEY is set but not a valid Fernet key ({e}). "
                "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            ) from e

    if app_env in ("production", "prod"):
        raise RuntimeError(
            "ENCRYPTION_KEY env var is required in production. "
            "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )

    # Dev fallback — deterministic, never use in prod
    digest = hashlib.sha256(_DEV_FALLBACK_SEED).digest()
    return base64.urlsafe_b64encode(digest)


_FERNET: Optional[Fernet] = None


def _fernet() -> Fernet:
    global _FERNET
    if _FERNET is None:
        _FERNET = Fernet(_resolve_key())
    return _FERNET


def encrypt(plain: Optional[str]) -> Optional[str]:
    """Encrypt a string. None passes through. Output is prefixed with 'enc:v1:'."""
    if plain is None:
        return None
    if not isinstance(plain, str):
        plain = str(plain)
    if plain.startswith(ENC_PREFIX):
        # Already encrypted — don't double-wrap (defensive, shouldn't happen via TypeDecorator)
        return plain
    return ENC_PREFIX + _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(value: Optional[str]) -> Optional[str]:
    """
    Decrypt a value. None passes through. Legacy plaintext (no prefix) is
    returned as-is so existing rows keep working until they're next written.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    if not value.startswith(ENC_PREFIX):
        return value  # legacy plaintext — opportunistically re-encrypted on next write
    payload = value[len(ENC_PREFIX):]
    try:
        return _fernet().decrypt(payload.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error("Decryption failed — wrong ENCRYPTION_KEY? Returning empty string.")
        return ""
