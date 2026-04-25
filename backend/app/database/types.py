"""
Custom SQLAlchemy column types.

EncryptedText: stores the value Fernet-encrypted at rest. App code reads/writes
plaintext as if it were a normal Text column — encryption happens transparently
on bind, decryption on result.
"""

from __future__ import annotations

from sqlalchemy.types import Text, TypeDecorator

from app.services.crypto import decrypt, encrypt


class EncryptedText(TypeDecorator):
    """Transparent encryption layer over a TEXT column."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value)

    def process_result_value(self, value, dialect):
        return decrypt(value)
