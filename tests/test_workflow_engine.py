# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for workflow engine builders and validation."""
from __future__ import annotations

import pytest
from fastapi import HTTPException


def test_auto_builders_keys():
    """_AUTO_BUILDERS has all expected automation types."""
    from server.workflow_engine import _AUTO_BUILDERS

    expected = {"script", "webhook", "service", "delay", "http", "notify", "condition", "agent_command", "remediation"}
    assert set(_AUTO_BUILDERS.keys()) == expected


def test_auto_builders_all_callable():
    """Every value in _AUTO_BUILDERS is callable."""
    from server.workflow_engine import _AUTO_BUILDERS

    for name, builder in _AUTO_BUILDERS.items():
        assert callable(builder), f"Builder for '{name}' is not callable"


def test_validate_auto_config_script_requires_command_or_script():
    """Script automation requires 'command' or 'script' in config."""
    from server.workflow_engine import _validate_auto_config

    with pytest.raises(HTTPException) as exc_info:
        _validate_auto_config("script", {})
    assert exc_info.value.status_code == 400


def test_validate_auto_config_script_with_command_passes():
    """Script automation with 'command' key passes validation."""
    from server.workflow_engine import _validate_auto_config

    # Should not raise
    _validate_auto_config("script", {"command": "echo hello"})


def test_validate_auto_config_script_with_script_key_passes():
    """Script automation with 'script' key passes validation."""
    from server.workflow_engine import _validate_auto_config

    _validate_auto_config("script", {"script": "some-script"})


def test_validate_auto_config_webhook_requires_valid_url():
    """Webhook automation requires a valid URL."""
    from server.workflow_engine import _validate_auto_config

    with pytest.raises(HTTPException) as exc_info:
        _validate_auto_config("webhook", {})
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException):
        _validate_auto_config("webhook", {"url": "not-a-url"})


def test_validate_auto_config_webhook_with_valid_url_passes():
    """Webhook automation with valid http URL passes."""
    from server.workflow_engine import _validate_auto_config

    _validate_auto_config("webhook", {"url": "http://example.com/hook"})
    _validate_auto_config("webhook", {"url": "https://example.com/hook"})


def test_validate_auto_config_service_requires_service_key():
    """Service automation requires 'service' in config."""
    from server.workflow_engine import _validate_auto_config

    with pytest.raises(HTTPException) as exc_info:
        _validate_auto_config("service", {})
    assert exc_info.value.status_code == 400


def test_validate_auto_config_service_invalid_action():
    """Service automation rejects invalid action values."""
    from server.workflow_engine import _validate_auto_config

    with pytest.raises(HTTPException) as exc_info:
        _validate_auto_config("service", {"service": "nginx", "action": "destroy"})
    assert exc_info.value.status_code == 400


def test_validate_auto_config_service_valid_actions():
    """Service automation accepts start, stop, restart."""
    from server.workflow_engine import _validate_auto_config

    for action in ("start", "stop", "restart"):
        _validate_auto_config("service", {"service": "nginx", "action": action})


def test_validate_auto_config_delay_requires_seconds_or_duration():
    """Delay automation requires 'seconds' or 'duration'."""
    from server.workflow_engine import _validate_auto_config

    with pytest.raises(HTTPException) as exc_info:
        _validate_auto_config("delay", {})
    assert exc_info.value.status_code == 400


def test_validate_auto_config_delay_with_seconds_passes():
    """Delay automation with 'seconds' passes."""
    from server.workflow_engine import _validate_auto_config

    _validate_auto_config("delay", {"seconds": 5})


def test_validate_auto_config_delay_with_duration_passes():
    """Delay automation with 'duration' passes."""
    from server.workflow_engine import _validate_auto_config

    _validate_auto_config("delay", {"duration": 10})


def test_validate_auto_config_http_requires_valid_url():
    """HTTP step requires a valid URL."""
    from server.workflow_engine import _validate_auto_config

    with pytest.raises(HTTPException) as exc_info:
        _validate_auto_config("http", {})
    assert exc_info.value.status_code == 400


def test_validate_auto_config_http_with_valid_url_passes():
    """HTTP step with valid URL passes."""
    from server.workflow_engine import _validate_auto_config

    _validate_auto_config("http", {"url": "https://api.example.com/status"})


def test_validate_auto_config_notify_requires_message():
    """Notify automation requires 'message'."""
    from server.workflow_engine import _validate_auto_config

    with pytest.raises(HTTPException) as exc_info:
        _validate_auto_config("notify", {})
    assert exc_info.value.status_code == 400


def test_validate_auto_config_notify_with_message_passes():
    """Notify automation with message passes."""
    from server.workflow_engine import _validate_auto_config

    _validate_auto_config("notify", {"message": "Hello world"})


def test_validate_auto_config_condition_requires_condition():
    """Condition automation requires 'condition'."""
    from server.workflow_engine import _validate_auto_config

    with pytest.raises(HTTPException) as exc_info:
        _validate_auto_config("condition", {})
    assert exc_info.value.status_code == 400


def test_validate_auto_config_condition_with_condition_passes():
    """Condition automation with condition string passes."""
    from server.workflow_engine import _validate_auto_config

    _validate_auto_config("condition", {"condition": "cpu > 80"})


def test_validate_auto_config_unknown_type_no_error():
    """Unknown automation type does not raise (no validation rule for it)."""
    from server.workflow_engine import _validate_auto_config

    # Unknown types fall through without raising
    _validate_auto_config("unknown_type", {})


# ── Outgoing webhook builder (never exercised before this commit) ───────────
#
# The outgoing-webhook automation was previously unreachable end-to-end:
# the frontend form only collected `url`, so `_build_auto_webhook_process`
# was always called with `{"url": ...}` — no body, no headers, and the
# HMAC signing helper was dead code because `config.get("secret")` was
# always "". The form now exposes method/body/headers/secret; these tests
# assert each path actually executes correctly so future regressions
# trip a red test instead of shipping a silent no-op.


def test_sign_request_headers_empty_secret_returns_empty():
    """No secret → no signature header (helper is a no-op)."""
    from server.workflow_engine import _sign_request_headers

    assert _sign_request_headers("", b"body") == {}
    assert _sign_request_headers(None, b"body") == {}


def test_sign_request_headers_hmac_sha256_correctness():
    """The signature must match a hand-computed HMAC-SHA256 of the body."""
    import hashlib
    import hmac

    from server.workflow_engine import _sign_request_headers

    secret = "s3cr3t-shared-with-receiver"
    body = b'{"event":"heal","target":"nas01"}'
    result = _sign_request_headers(secret, body)
    expected_sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert result == {"X-Noba-Signature": expected_sig}


def test_build_auto_webhook_process_signed_json_body(monkeypatch):
    """End-to-end: JSON body + signing secret produces the right request."""
    import hashlib
    import hmac
    from unittest.mock import MagicMock

    import httpx

    from server import workflow_engine

    captured = {}

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        captured["content"] = kwargs.get("content")
        resp = MagicMock()
        resp.text = "ok"
        resp.status_code = 200
        return resp

    monkeypatch.setattr(httpx, "request", fake_request)

    cfg = {
        "url": "https://example.com/hook",
        "method": "POST",
        "body": {"event": "heal", "target": "nas01"},
        "headers": {"X-Event": "noba-heal"},
        "secret": "s3cr3t-shared-with-receiver",
    }
    result = workflow_engine._build_auto_webhook_process(cfg)
    assert result is not None
    assert result.returncode == 0

    # Request was dispatched with the right method, URL, and serialised body.
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.com/hook"
    assert captured["content"] == b'{"event": "heal", "target": "nas01"}'

    headers = captured["headers"]
    assert headers["X-Event"] == "noba-heal"
    assert headers["Content-Type"] == "application/json"

    # Most importantly: signature header is correct HMAC over the serialised body.
    expected_sig = (
        "sha256="
        + hmac.new(
            b"s3cr3t-shared-with-receiver", captured["content"], hashlib.sha256,
        ).hexdigest()
    )
    assert headers["X-Noba-Signature"] == expected_sig


def test_build_auto_webhook_process_no_secret_no_signature(monkeypatch):
    """Without a secret the X-Noba-Signature header must not be set."""
    from unittest.mock import MagicMock

    import httpx

    from server import workflow_engine

    captured = {}

    def fake_request(method, url, **kwargs):
        captured["headers"] = kwargs.get("headers", {})
        resp = MagicMock()
        resp.text = "ok"
        resp.status_code = 200
        return resp

    monkeypatch.setattr(httpx, "request", fake_request)

    cfg = {
        "url": "https://example.com/hook",
        "method": "POST",
        "body": {"ping": True},
        # No "secret" key at all — signing must be skipped cleanly.
    }
    workflow_engine._build_auto_webhook_process(cfg)
    assert "X-Noba-Signature" not in captured["headers"]
    assert captured["headers"].get("Content-Type") == "application/json"


def test_build_auto_webhook_process_raw_string_body_signed(monkeypatch):
    """Raw string bodies (non-JSON) are also signed over the byte content."""
    import hashlib
    import hmac
    from unittest.mock import MagicMock

    import httpx

    from server import workflow_engine

    captured = {}

    def fake_request(method, url, **kwargs):
        captured["headers"] = kwargs.get("headers", {})
        captured["content"] = kwargs.get("content")
        resp = MagicMock()
        resp.text = "ok"
        resp.status_code = 200
        return resp

    monkeypatch.setattr(httpx, "request", fake_request)

    cfg = {
        "url": "https://example.com/hook",
        "body": "plain text alert — host down",
        "secret": "k",
    }
    workflow_engine._build_auto_webhook_process(cfg)

    assert captured["content"] == "plain text alert — host down".encode()
    expected_sig = (
        "sha256=" + hmac.new(b"k", captured["content"], hashlib.sha256).hexdigest()
    )
    assert captured["headers"]["X-Noba-Signature"] == expected_sig
    # No Content-Type injected for raw strings — caller can add one via headers.
    assert "Content-Type" not in captured["headers"]
