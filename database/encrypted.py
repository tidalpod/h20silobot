"""Application-level encryption for sensitive database fields.

Values are stored as versioned Fernet ciphertext.  Legacy plaintext remains
readable long enough for the startup migration to convert it in place.
"""

from __future__ import annotations

import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator


ENCRYPTED_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    key = os.getenv("ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("ENCRYPTION_KEY is required for sensitive database fields")
    try:
        return Fernet(key.encode())
    except (TypeError, ValueError) as exc:
        raise RuntimeError("ENCRYPTION_KEY must be a valid Fernet key") from exc


def validate_encryption_key() -> Optional[str]:
    """Return a configuration error or None when the key is usable."""
    try:
        _fernet()
    except RuntimeError as exc:
        return str(exc)
    return None


def is_encrypted(value: Optional[str]) -> bool:
    return bool(value and value.startswith(ENCRYPTED_PREFIX))


def encrypt_sensitive_value(value: Optional[str]) -> Optional[str]:
    if value is None or value == "" or is_encrypted(value):
        return value
    token = _fernet().encrypt(str(value).encode()).decode()
    return f"{ENCRYPTED_PREFIX}{token}"


def decrypt_sensitive_value(value: Optional[str]) -> Optional[str]:
    if value is None or value == "" or not is_encrypted(value):
        # Backward compatibility for rows that have not reached the migration.
        return value
    token = value[len(ENCRYPTED_PREFIX):]
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Sensitive database value could not be decrypted") from exc


class EncryptedText(TypeDecorator):
    """Transparent Fernet encryption for SQLAlchemy string attributes."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_sensitive_value(value)

    def process_result_value(self, value, dialect):
        return decrypt_sensitive_value(value)
