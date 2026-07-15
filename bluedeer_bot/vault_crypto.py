"""Fernet encryption wrapper for the Blue Deer bot password vault.

The encryption key is read once from the VAULT_ENCRYPTION_KEY env var.
Generate a valid key with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class VaultCryptoError(Exception):
    """Raised when the vault key is missing, malformed, or a decrypt fails."""


_fernet_cache: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    """Lazy-initialize the Fernet cipher. Raises VaultCryptoError if the key is bad."""
    global _fernet_cache
    if _fernet_cache is not None:
        return _fernet_cache

    key = os.getenv("VAULT_ENCRYPTION_KEY", "").strip()
    if not key:
        raise VaultCryptoError("VAULT_ENCRYPTION_KEY is not set")

    try:
        _fernet_cache = Fernet(key.encode())
    except Exception as e:
        raise VaultCryptoError(f"VAULT_ENCRYPTION_KEY is malformed: {e}")

    return _fernet_cache


def is_configured() -> bool:
    """Return True if VAULT_ENCRYPTION_KEY is set and valid."""
    try:
        _get_fernet()
        return True
    except VaultCryptoError:
        return False


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return base64 Fernet ciphertext."""
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet ciphertext string. Raises VaultCryptoError on failure."""
    try:
        return _get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise VaultCryptoError(f"Decryption failed (key mismatch or corrupted): {e}")
