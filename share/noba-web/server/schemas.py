# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Pydantic schemas for request validation."""
from __future__ import annotations

import re
from urllib.parse import urlparse

_SECRET_PATTERNS = re.compile(
    r"(token|key|pass|secret|password|credential|auth)", re.IGNORECASE
)


def is_secret_key(key: str) -> bool:
    """Check if a settings key name likely contains a secret value."""
    return bool(_SECRET_PATTERNS.search(key))


def validate_integration_urls(settings: dict) -> list[str]:
    """Validate that all URL-like settings use http/https scheme.

    Returns list of error messages (empty if all valid).
    """
    errors = []
    for k, v in settings.items():
        if not isinstance(v, str) or not v.strip():
            continue
        # Check keys that look like URLs
        if not any(s in k.lower() for s in ("url", "host", "server", "endpoint")):
            continue
        val = v.strip()
        # Skip if it looks like a bare hostname/IP (no scheme)
        if "://" not in val:
            continue
        parsed = urlparse(val)
        if parsed.scheme and parsed.scheme not in ("http", "https"):
            errors.append(
                f"Invalid URL scheme '{parsed.scheme}' for {k} — must be http or https"
            )
    return errors
