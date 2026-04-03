# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Transparent config value encryption using Fernet."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("noba")

# Key file location -- separate from config so backups don't include the key
_KEY_FILE = os.path.expanduser("~/.config/noba/.master.key")
_ENC_PREFIX = "ENC:"  # marker for encrypted values

_fernet = None


def _get_fernet():
    """Get or create the Fernet instance, generating key on first use."""
    global _fernet
    if _fernet is not None:
        return _fernet

    try:
        from cryptography.fernet import Fernet
    except ImportError:
        logger.debug("cryptography package not installed -- encryption disabled")
        return None

    if os.path.isfile(_KEY_FILE):
        with open(_KEY_FILE, "rb") as f:
            key = f.read().strip()
    else:
        key = Fernet.generate_key()
        os.makedirs(os.path.dirname(_KEY_FILE), exist_ok=True)
        fd = os.open(_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        logger.info("Generated new encryption key: %s", _KEY_FILE)

    _fernet = Fernet(key)
    return _fernet


def encrypt_value(value: str) -> str:
    """Encrypt a string value. Returns 'ENC:...' prefixed ciphertext."""
    if not value or value.startswith(_ENC_PREFIX):
        return value  # already encrypted or empty
    f = _get_fernet()
    if f is None:
        return value  # no encryption available
    token = f.encrypt(value.encode("utf-8"))
    return _ENC_PREFIX + token.decode("ascii")


def decrypt_value(value: str) -> str:
    """Decrypt an 'ENC:...' value. Returns plaintext. Non-encrypted values pass through."""
    if not isinstance(value, str) or not value.startswith(_ENC_PREFIX):
        return value  # not encrypted
    f = _get_fernet()
    if f is None:
        logger.warning("Cannot decrypt value -- cryptography package not installed")
        return value
    try:
        token = value[len(_ENC_PREFIX) :].encode("ascii")
        return f.decrypt(token).decode("utf-8")
    except Exception as e:
        logger.error("Failed to decrypt config value: %s", e)
        return value  # return as-is on failure (don't break startup)


def is_encrypted(value: str) -> bool:
    """Check if a value is encrypted."""
    return isinstance(value, str) and value.startswith(_ENC_PREFIX)
