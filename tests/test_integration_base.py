# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for BaseIntegration retry, caching, and URL validation."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import httpx
import pytest


def test_url_scheme_validation_rejects_file():
    """Reject file:// scheme."""
    from server.integrations.base import BaseIntegration, ConfigError

    with pytest.raises(ConfigError):
        BaseIntegration.validate_url("file:///etc/passwd")


def test_url_scheme_validation_rejects_ftp():
    """Reject ftp:// scheme."""
    from server.integrations.base import BaseIntegration, ConfigError

    with pytest.raises(ConfigError):
        BaseIntegration.validate_url("ftp://example.com")


def test_url_scheme_validation_accepts_http():
    """Accept http:// scheme with a public host."""
    from server.integrations.base import BaseIntegration

    result = BaseIntegration.validate_url("http://8.8.8.8:8080")
    assert result == "http://8.8.8.8:8080"


def test_url_scheme_validation_accepts_https():
    """Accept https:// scheme."""
    from server.integrations.base import BaseIntegration

    result = BaseIntegration.validate_url("https://example.com")
    assert result == "https://example.com"


def test_url_scheme_validation_strips_trailing_slash():
    """validate_url strips trailing slash."""
    from server.integrations.base import BaseIntegration

    result = BaseIntegration.validate_url("https://example.com/")
    assert result == "https://example.com"


def test_retry_on_timeout_succeeds_second_attempt():
    """Retry on timeout, succeed on second attempt."""
    from server.integrations.base import BaseIntegration

    class ConcreteIntegration(BaseIntegration):
        def __init__(self):
            super().__init__(retries=2)
            self._call_count = 0

        def _fetch(self):
            self._call_count += 1
            if self._call_count == 1:
                raise httpx.TimeoutException("timeout")
            return {"ok": True}

    bi = ConcreteIntegration()
    result = bi.get()
    assert result == {"ok": True}
    assert bi._call_count == 2


def test_config_error_no_retry_on_4xx():
    """Don't retry on 4xx status errors (raises ConfigError immediately)."""
    from server.integrations.base import BaseIntegration, ConfigError

    class ConcreteIntegration(BaseIntegration):
        def __init__(self):
            super().__init__(retries=3)
            self._call_count = 0

        def _fetch(self):
            self._call_count += 1
            mock_response = MagicMock()
            mock_response.status_code = 401
            raise httpx.HTTPStatusError(
                "401 Unauthorized",
                request=MagicMock(),
                response=mock_response,
            )

    bi = ConcreteIntegration()
    with pytest.raises(ConfigError):
        bi.get()
    assert bi._call_count == 1  # No retry on 4xx


def test_cache_ttl_returns_cached_data():
    """Second call within TTL returns cached data without re-fetching."""
    from server.integrations.base import BaseIntegration

    class ConcreteIntegration(BaseIntegration):
        def __init__(self):
            super().__init__(ttl=60)
            self._call_count = 0

        def _fetch(self):
            self._call_count += 1
            return {"cached": True}

    bi = ConcreteIntegration()
    result1 = bi.get()
    result2 = bi.get()

    assert result1 == {"cached": True}
    assert result2 == {"cached": True}
    assert bi._call_count == 1  # Only fetched once


def test_cache_expired_refetches():
    """Call after TTL expiry re-fetches."""
    from server.integrations.base import BaseIntegration

    class ConcreteIntegration(BaseIntegration):
        def __init__(self):
            super().__init__(ttl=0.01)  # 10ms TTL
            self._call_count = 0

        def _fetch(self):
            self._call_count += 1
            return {"count": self._call_count}

    bi = ConcreteIntegration()
    bi.get()
    time.sleep(0.02)  # Let TTL expire
    result2 = bi.get()

    assert bi._call_count == 2
    assert result2 == {"count": 2}


def test_exhausted_retries_raises_transient_error():
    """Raise TransientError when all retries fail."""
    from server.integrations.base import BaseIntegration, TransientError

    class ConcreteIntegration(BaseIntegration):
        def __init__(self):
            super().__init__(retries=2)
            self._call_count = 0

        def _fetch(self):
            self._call_count += 1
            raise httpx.TimeoutException("timeout")

    bi = ConcreteIntegration()
    with pytest.raises(TransientError):
        bi.get()
    assert bi._call_count == 2  # initial + 1 retry


def test_no_cache_by_default():
    """Default ttl=0 means no caching — fetch is called every time."""
    from server.integrations.base import BaseIntegration

    class ConcreteIntegration(BaseIntegration):
        def __init__(self):
            super().__init__()  # ttl defaults to 0
            self._call_count = 0

        def _fetch(self):
            self._call_count += 1
            return {"n": self._call_count}

    bi = ConcreteIntegration()
    bi.get()
    bi.get()
    assert bi._call_count == 2


def test_validate_url_accepts_loopback():
    """Accept 127.0.0.1 — on-prem deployments may target localhost services."""
    from server.integrations.base import BaseIntegration

    result = BaseIntegration.validate_url("http://127.0.0.1:8080")
    assert result == "http://127.0.0.1:8080"


def test_validate_url_accepts_localhost():
    """Accept http://localhost — on-prem deployments use local services."""
    from server.integrations.base import BaseIntegration

    result = BaseIntegration.validate_url("http://localhost/api")
    assert result == "http://localhost/api"


def test_validate_url_accepts_private_10():
    """Accept 10.x.x.x RFC1918 range — standard on-prem network."""
    from server.integrations.base import BaseIntegration

    result = BaseIntegration.validate_url("http://10.0.0.1/unifi")
    assert result == "http://10.0.0.1/unifi"


def test_validate_url_accepts_private_192():
    """Accept 192.168.x.x RFC1918 range — standard home/SMB network."""
    from server.integrations.base import BaseIntegration

    result = BaseIntegration.validate_url("http://192.168.1.1:8443")
    assert result == "http://192.168.1.1:8443"


def test_validate_url_accepts_link_local():
    """Accept 169.254.x.x link-local — may be used in isolated networks."""
    from server.integrations.base import BaseIntegration

    result = BaseIntegration.validate_url("http://169.254.169.254/metadata")
    assert result == "http://169.254.169.254/metadata"


def test_validate_url_accepts_public_ip():
    """Accept public IPs — they are valid integration targets."""
    from server.integrations.base import BaseIntegration

    result = BaseIntegration.validate_url("http://8.8.8.8/api")
    assert result == "http://8.8.8.8/api"


def test_validate_url_accepts_public_hostname():
    """Accept non-localhost hostnames — DNS resolution not performed at validation."""
    from server.integrations.base import BaseIntegration

    result = BaseIntegration.validate_url("https://my-nas.example.com")
    assert result == "https://my-nas.example.com"
