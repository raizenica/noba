# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the WebSocket Origin check (CSWSH protection).

The helper lives in ``server.deps.check_ws_origin`` and is enforced by
every browser-facing WebSocket endpoint (agent_rdp, agent_terminal) BEFORE
any authentication work, so an attacker page opening a cross-origin WS
against NOBA gets a 403 handshake rejection instead of reaching the token
consume stage.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _patch_cors_origins(monkeypatch):
    """Make the allowlist deterministic for each test case.

    ``check_ws_origin`` reads ``server.app._cors_origins`` lazily. We patch
    it per-test so no test's allowlist leaks into another.
    """
    import server.app as _app

    def _set(origins):
        monkeypatch.setattr(_app, "_cors_origins", origins)
    _set([])  # default: no explicit allowlist
    return _set


def test_empty_origin_rejected():
    """Browsers always send Origin on WebSocket upgrades; missing → reject."""
    from server.deps import check_ws_origin
    assert check_ws_origin("", "noba.example.com") is False
    assert check_ws_origin(None, "noba.example.com") is False


def test_same_origin_by_hostname_allowed():
    """Same-host connection from the browser must succeed."""
    from server.deps import check_ws_origin
    assert check_ws_origin("https://noba.example.com", "noba.example.com") is True


def test_same_origin_ignores_port_in_request_host():
    """Request host may include a port — only the hostname matters."""
    from server.deps import check_ws_origin
    assert check_ws_origin("http://noba.local", "noba.local:8000") is True
    assert check_ws_origin("http://noba.local:8000", "noba.local:8000") is True


def test_cross_origin_rejected_without_allowlist():
    """With no explicit allowlist, cross-origin connections are rejected."""
    from server.deps import check_ws_origin
    assert check_ws_origin("https://evil.example.com", "noba.example.com") is False


def test_explicit_allowlist_match(_patch_cors_origins):
    """An origin in NOBA_CORS_ORIGINS is allowed even if not same-host."""
    _patch_cors_origins(["https://dashboard.partner.io"])
    from server.deps import check_ws_origin
    assert check_ws_origin("https://dashboard.partner.io", "noba.internal") is True


def test_explicit_allowlist_exact_match_only(_patch_cors_origins):
    """Allowlist match is exact — no subdomain wildcarding."""
    _patch_cors_origins(["https://dashboard.partner.io"])
    from server.deps import check_ws_origin
    # Sibling subdomain: not allowed.
    assert check_ws_origin("https://evil.partner.io", "noba.internal") is False
    # Different scheme: not allowed (the allowlist entry is https://).
    assert check_ws_origin("http://dashboard.partner.io", "noba.internal") is False


def test_malformed_origin_rejected():
    """A non-URL Origin header must be rejected cleanly (no exception)."""
    from server.deps import check_ws_origin
    assert check_ws_origin("not-a-url", "noba.example.com") is False
    assert check_ws_origin("://", "noba.example.com") is False


def test_missing_request_host_rejects_same_origin_path():
    """Without a request Host header, same-origin matching is impossible."""
    from server.deps import check_ws_origin
    assert check_ws_origin("https://noba.example.com", "") is False
    assert check_ws_origin("https://noba.example.com", None) is False


def test_origin_with_nonstandard_port_matches_hostname():
    """Origin is normalised to hostname for the same-origin check."""
    from server.deps import check_ws_origin
    assert check_ws_origin("http://noba.local:3000", "noba.local") is True


def test_case_sensitive_hostname_exact_match():
    """Hostnames are case-insensitive in DNS but urlparse lowercases them."""
    from server.deps import check_ws_origin
    # urlparse lowercases the hostname, so these should still match.
    assert check_ws_origin("https://NOBA.EXAMPLE.COM", "noba.example.com") is True
