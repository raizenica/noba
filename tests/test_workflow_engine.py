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
