# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Shared infrastructure for integrations: HTTP client, helpers, base class."""
from __future__ import annotations

import logging
import os
import time
import urllib.parse

import httpx

_POOL_CONNECTIONS = int(os.environ.get("NOBA_POOL_CONNECTIONS", 20))
_POOL_KEEPALIVE = int(os.environ.get("NOBA_POOL_KEEPALIVE", 10))

logger = logging.getLogger("noba")

# Shared client with connection pooling and sensible defaults.
# follow_redirects disabled to prevent SSRF via redirect to internal IPs.
_client = httpx.Client(
    timeout=4,
    follow_redirects=False,
    limits=httpx.Limits(
        max_connections=_POOL_CONNECTIONS,
        max_keepalive_connections=_POOL_KEEPALIVE,
        keepalive_expiry=30,
    ),
)


def ssl_verify(setting: bool | str = True):
    """Convert a verify_ssl config value to the httpx verify parameter.

    - True/False → passed directly (verify or skip)
    - str → treated as a CA bundle file path
    """
    if isinstance(setting, str) and setting not in ("", "0", "false", "False"):
        if os.path.isfile(setting):
            return setting  # CA bundle path
    if isinstance(setting, str):
        return setting.lower() not in ("", "0", "false", "no")
    return bool(setting)


def _http_get(url: str, headers: dict | None = None, timeout: int = 4,
              verify: bool | str | None = None) -> dict | list:
    """Execute GET request with classified error propagation.

    Args:
        verify: Override SSL verification. None = use shared client (verify=True).
                False = skip verification. str = CA bundle path.

    Raises:
        ConfigError: 4xx (Auth/URL) errors that require user attention.
        TransientError: 5xx or network errors that may resolve on retry.
    """
    try:
        if verify is not None and verify is not True:
            # Use a one-off client with custom verify setting
            with httpx.Client(timeout=timeout, follow_redirects=False, verify=verify) as c:
                r = c.get(url, headers=headers or {})
        else:
            r = _client.get(url, headers=headers or {}, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        # 4xx (except 408 Timeout / 429 Rate Limit) are ConfigErrors
        if 400 <= code < 500 and code not in (408, 429):
            raise ConfigError(f"HTTP {code}: {exc.response.text[:100]}") from exc
        raise TransientError(f"HTTP {code}") from exc
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        raise TransientError(str(exc)) from exc
    except httpx.HTTPError as exc:
        raise TransientError(str(exc)) from exc


# ---------------------------------------------------------------------------
# BaseIntegration — future-use base class for structured integrations
# ---------------------------------------------------------------------------


class TransientError(Exception):
    """Transient failures: timeouts, 5xx, connection errors."""


class ConfigError(Exception):
    """Configuration errors: 401, bad URL, missing credentials."""


class BaseIntegration:
    """Base class for structured integrations with retry + cache support.

    Subclass and override ``_fetch(self) -> dict | list | None`` to use.
    """

    retries: int = 2
    ttl: float = 0  # seconds; 0 = no cache

    def __init__(self, *, retries: int | None = None, ttl: float | None = None) -> None:
        if retries is not None:
            self.retries = retries
        if ttl is not None:
            self.ttl = ttl
        self._cache_value: dict | list | None = None
        self._cache_ts: float = 0.0

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def validate_url(url: str) -> str:
        """Validate URL scheme (http/https only) and return normalised URL.

        Private/RFC1918 IPs are explicitly allowed — NOBA is designed for
        on-premises deployments where integrations (TrueNAS, Proxmox, Pi-hole,
        etc.) run on the local network.
        """
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ConfigError(f"Unsupported URL scheme: {parsed.scheme!r}")
        return url.rstrip("/")

    # -- public API -----------------------------------------------------------

    def get(self) -> dict | list | None:
        """Execute the integration with retries and optional TTL caching."""
        if self.ttl and self._cache_ts and time.time() - self._cache_ts < self.ttl:
            return self._cache_value

        last_exc: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                result = self._fetch()
                if self.ttl:
                    self._cache_value = result
                    self._cache_ts = time.time()
                return result
            except ConfigError:
                raise
            except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                last_exc = exc
                # Classify: 4xx (except 408/429) -> ConfigError
                if isinstance(exc, httpx.HTTPStatusError):
                    code = exc.response.status_code
                    if 400 <= code < 500 and code not in (408, 429):
                        raise ConfigError(str(exc)) from exc
                # Exponential backoff for transient errors
                if attempt < self.retries:
                    time.sleep(min(2 ** (attempt - 1), 8))
            except (httpx.HTTPError, OSError) as exc:
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(min(2 ** (attempt - 1), 8))

        raise TransientError(str(last_exc)) from last_exc

    def _fetch(self) -> dict | list | None:
        """Override in subclasses to perform the actual HTTP call(s)."""
        raise NotImplementedError
