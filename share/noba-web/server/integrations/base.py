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
_client = httpx.Client(
    timeout=4,
    follow_redirects=True,
    limits=httpx.Limits(
        max_connections=_POOL_CONNECTIONS,
        max_keepalive_connections=_POOL_KEEPALIVE,
        keepalive_expiry=30,
    ),
)


def _http_get(url: str, headers: dict | None = None, timeout: int = 4) -> dict | list:
    r = _client.get(url, headers=headers or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


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
        """Reject non-http/https schemes; return normalised URL."""
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
