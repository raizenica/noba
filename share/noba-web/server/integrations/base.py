# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Shared infrastructure for integrations: HTTP client pools, helpers, base class.

## CF-9 — per-category connection pool sharding (2026-04-08)

httpx 0.28.x has no per-host connection cap in ``Limits`` (only pool-wide
``max_connections`` / ``max_keepalive_connections`` / ``keepalive_expiry``).
That means a single shared ``httpx.Client`` is a starvation risk: if one slow
target (e.g. a Keycloak admin-cli call doing ~1 s LDAP work, or an un-indexed
database query) holds every connection in the pool, every *other* integration
queues behind it.

The fix is bulkheading: one ``httpx.Client`` per integration category, sized
to that category's expected fan-out. A slow NAS box can saturate the ``nas``
pool without affecting ``dns`` or ``monitoring``. On top of that, a
per-``(category, instance_id)`` semaphore (cap = 4) prevents a *single*
instance within a category from monopolising its category's pool during a
heal storm.

Callers migrate from the legacy shared ``_client`` to
``get_category_client(category)``. Uncategorised callers (tests, ad-hoc
scripts, and any collector not yet migrated) continue to use ``_client``,
which is now wired to the ``default`` category pool — so there is no
behavioural cliff during the migration.

Research provenance: Phase B Group G.5 finding, integrated as Contract C15
in ``2026-04-08-phase4-PLAN-INDEX.md`` (enterprise plan set).
"""
from __future__ import annotations

import logging
import os
import threading
import time
import urllib.parse
from contextlib import contextmanager

import httpx

_POOL_CONNECTIONS = int(os.environ.get("NOBA_POOL_CONNECTIONS", 20))
_POOL_KEEPALIVE = int(os.environ.get("NOBA_POOL_KEEPALIVE", 10))
_DEFAULT_TIMEOUT = 4

logger = logging.getLogger("noba")


class TransientError(Exception):
    """Transient failures: timeouts, 5xx, connection errors."""


class ConfigError(Exception):
    """Configuration errors: 401, bad URL, missing credentials."""


# ── Category pool limits (CF-9) ──────────────────────────────────────────────
#
# Each category gets its own httpx.Client, sized by expected fan-out and the
# typical call latency of that platform family. Numbers are deliberately small
# — the point of bulkheading is *isolation*, not aggregate throughput. If you
# find yourself wanting to raise these, consider whether you actually want
# batching (tokens from a rate limiter) instead of pool growth.
#
# Unknown / legacy / uncategorised calls go through the ``default`` pool,
# which is sized to the pre-CF-9 pool-wide cap (20) so existing collectors
# keep their previous throughput until they're migrated.
_CATEGORY_POOL_LIMITS: dict[str, httpx.Limits] = {
    # High fan-out categories — many platforms, many parallel read calls.
    "monitoring":       httpx.Limits(max_connections=8, max_keepalive_connections=4, keepalive_expiry=30),
    "container_runtime": httpx.Limits(max_connections=8, max_keepalive_connections=4, keepalive_expiry=30),
    "media_management": httpx.Limits(max_connections=8, max_keepalive_connections=4, keepalive_expiry=30),

    # Mid-sized categories — steady fan-out, not especially slow.
    "nas":             httpx.Limits(max_connections=6, max_keepalive_connections=3, keepalive_expiry=30),
    "hypervisor":      httpx.Limits(max_connections=6, max_keepalive_connections=3, keepalive_expiry=30),
    "media_server":    httpx.Limits(max_connections=6, max_keepalive_connections=3, keepalive_expiry=30),
    "smart_home":      httpx.Limits(max_connections=6, max_keepalive_connections=3, keepalive_expiry=30),
    "git_devops":      httpx.Limits(max_connections=6, max_keepalive_connections=3, keepalive_expiry=30),
    "database":        httpx.Limits(max_connections=6, max_keepalive_connections=3, keepalive_expiry=30),
    "network_hardware": httpx.Limits(max_connections=6, max_keepalive_connections=3, keepalive_expiry=30),
    "document_wiki":   httpx.Limits(max_connections=6, max_keepalive_connections=3, keepalive_expiry=30),

    # Smaller or typically-slow categories — tighter caps to enforce isolation.
    "dns":             httpx.Limits(max_connections=4, max_keepalive_connections=2, keepalive_expiry=30),
    "download_client": httpx.Limits(max_connections=4, max_keepalive_connections=2, keepalive_expiry=30),
    "identity_auth":   httpx.Limits(max_connections=4, max_keepalive_connections=2, keepalive_expiry=30),
    "mail":            httpx.Limits(max_connections=4, max_keepalive_connections=2, keepalive_expiry=30),
    "backup":          httpx.Limits(max_connections=4, max_keepalive_connections=2, keepalive_expiry=30),
    "certificate":     httpx.Limits(max_connections=4, max_keepalive_connections=2, keepalive_expiry=30),
    "reverse_proxy":   httpx.Limits(max_connections=4, max_keepalive_connections=2, keepalive_expiry=30),
    "security":        httpx.Limits(max_connections=4, max_keepalive_connections=2, keepalive_expiry=30),
    "automation":      httpx.Limits(max_connections=4, max_keepalive_connections=2, keepalive_expiry=30),
    "cloud":           httpx.Limits(max_connections=4, max_keepalive_connections=2, keepalive_expiry=30),

    # Default / legacy bucket — matches the pre-CF-9 global pool size so
    # legacy callers behave identically until migrated.
    "default":         httpx.Limits(
        max_connections=_POOL_CONNECTIONS,
        max_keepalive_connections=_POOL_KEEPALIVE,
        keepalive_expiry=30,
    ),
}

_category_clients: dict[str, httpx.Client] = {}
_category_clients_lock = threading.Lock()


def get_category_client(category: str) -> httpx.Client:
    """Return the shared ``httpx.Client`` for an integration category.

    Lazily constructs a per-category client on first use. Unknown categories
    fall back to the ``default`` pool so typos never silently skip
    bulkheading (they'd just share the default bucket with other legacy
    callers, which is the worst case we already had pre-CF-9).
    """
    pool = _CATEGORY_POOL_LIMITS.get(category)
    if pool is None:
        logger.debug("get_category_client: unknown category %r, falling back to 'default'", category)
        category = "default"
        pool = _CATEGORY_POOL_LIMITS["default"]

    # Fast path: already built.
    client = _category_clients.get(category)
    if client is not None:
        return client

    with _category_clients_lock:
        # Re-check inside the lock.
        client = _category_clients.get(category)
        if client is not None:
            return client
        client = httpx.Client(
            timeout=_DEFAULT_TIMEOUT,
            follow_redirects=False,
            limits=pool,
        )
        _category_clients[category] = client
        return client


# Legacy shared client — aliased to the default category pool so that any
# remaining un-migrated call site gets the same bulkheaded behaviour. Keeping
# the name ``_client`` so existing imports and test monkey-patches continue
# to work during the incremental CF-9 migration.
_client = get_category_client("default")


# ── Per-(category, instance_id) semaphore (CF-9) ─────────────────────────────
#
# Even with per-category pools, a single misbehaving instance inside a category
# can still monopolise its category's connections. The semaphore caps
# concurrency for any one (category, instance_id) pair at 4 — enough for
# healthy retry + fan-out, not enough to starve sibling instances.
#
# Lazily created, keyed by (category, instance_id). Instance ids are
# integration-specific (URL, hostname, config key — whatever the caller uses
# to distinguish instances within a category).
_SEMAPHORE_CAP = int(os.environ.get("NOBA_PER_INSTANCE_CAP", 4))
_instance_semaphores: dict[tuple[str, str], threading.BoundedSemaphore] = {}
_instance_semaphores_lock = threading.Lock()


def get_instance_semaphore(category: str, instance_id: str) -> threading.BoundedSemaphore:
    """Return the bounded semaphore for a (category, instance_id) pair.

    Lazily instantiated at ``_SEMAPHORE_CAP`` (default 4). Wrap dispatch code
    in ``with get_instance_semaphore(cat, inst):`` to enforce per-instance
    concurrency isolation.
    """
    key = (category, instance_id)
    sem = _instance_semaphores.get(key)
    if sem is not None:
        return sem

    with _instance_semaphores_lock:
        sem = _instance_semaphores.get(key)
        if sem is not None:
            return sem
        sem = threading.BoundedSemaphore(_SEMAPHORE_CAP)
        _instance_semaphores[key] = sem
        return sem


@contextmanager
def instance_slot(category: str, instance_id: str):
    """Context manager that acquires the per-instance semaphore.

    Usage::

        with instance_slot("dns", pihole_url):
            r = get_category_client("dns").get(...)
    """
    sem = get_instance_semaphore(category, instance_id)
    acquired = sem.acquire(timeout=30)
    if not acquired:
        raise TransientError(
            f"instance_slot timeout: {category}/{instance_id} — concurrent cap hit, try again later",
        )
    try:
        yield
    finally:
        sem.release()


def ssl_verify(setting: bool | str = True):
    """Convert a verify_ssl config value to the httpx verify parameter.

    - True/False → passed directly (verify or skip)
    - str → treated as a CA bundle file path
    """
    if isinstance(setting, str) and setting not in ("", "0", "false", "False") and os.path.isfile(setting):
        return setting  # CA bundle path
    if isinstance(setting, str):
        return setting.lower() not in ("", "0", "false", "no")
    return bool(setting)


def _http_get(
    url: str,
    headers: dict | None = None,
    timeout: int = 4,
    verify: bool | str | None = None,
    *,
    category: str = "default",
) -> dict | list:
    """Execute GET request with classified error propagation.

    Args:
        url: URL to fetch.
        headers: Optional request headers.
        timeout: Per-request timeout in seconds (default 4).
        verify: Override SSL verification. None = use shared client (verify=True).
                False = skip verification. str = CA bundle path.
        category: Integration category for pool selection (CF-9). Defaults to
                  ``"default"`` so every pre-CF-9 caller keeps working
                  unchanged.

    Raises:
        ConfigError: 4xx (Auth/URL) errors that require user attention.
        TransientError: 5xx or network errors that may resolve on retry.
    """
    try:
        if verify is not None and verify is not True:
            # Use a one-off client with custom verify setting — this path
            # bypasses the category pool because custom verify settings are
            # incompatible with connection reuse across hosts.
            with httpx.Client(timeout=timeout, follow_redirects=False, verify=verify) as c:
                r = c.get(url, headers=headers or {})
        elif category == "default":
            # Reference the module-level `_client` by name so tests that patch
            # ``server.integrations.base._client`` continue to exercise the
            # default-category pool through their mock.
            r = _client.get(url, headers=headers or {}, timeout=timeout)
        else:
            r = get_category_client(category).get(url, headers=headers or {}, timeout=timeout)
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
