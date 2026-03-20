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
    """Accept http:// scheme."""
    from server.integrations.base import BaseIntegration

    result = BaseIntegration.validate_url("http://localhost:8080")
    assert result == "http://localhost:8080"


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
