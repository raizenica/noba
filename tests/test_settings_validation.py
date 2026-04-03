# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for settings validation schemas."""
from __future__ import annotations

from server.schemas import is_secret_key, validate_integration_urls


def test_is_secret_key_token():
    """'token' pattern is detected as a secret."""
    assert is_secret_key("piholeToken") is True


def test_is_secret_key_api_key():
    """'key' pattern is detected as a secret."""
    assert is_secret_key("api_key") is True


def test_is_secret_key_password():
    """'pass' pattern is detected as a secret."""
    assert is_secret_key("unifiPassword") is True


def test_is_secret_key_secret():
    """'secret' pattern is detected as a secret."""
    assert is_secret_key("oidc_secret") is True


def test_is_secret_key_credential():
    """'credential' pattern is detected as a secret."""
    assert is_secret_key("plexCredential") is True


def test_is_secret_key_auth():
    """'auth' pattern is detected as a secret."""
    assert is_secret_key("hassAuth") is True


def test_is_secret_key_case_insensitive():
    """Secret pattern matching is case-insensitive."""
    assert is_secret_key("API_KEY") is True
    assert is_secret_key("PASSWORD") is True
    assert is_secret_key("AuthToken") is True


def test_is_secret_key_url_not_secret():
    """URL keys are not flagged as secrets."""
    assert is_secret_key("piholeUrl") is False


def test_is_secret_key_refresh_interval_not_secret():
    """refreshInterval is not a secret."""
    assert is_secret_key("refreshInterval") is False


def test_is_secret_key_monitored_services_not_secret():
    """monitoredServices is not a secret."""
    assert is_secret_key("monitoredServices") is False


def test_validate_urls_valid_http():
    """Valid http URL passes without errors."""
    errors = validate_integration_urls({"piholeUrl": "http://192.168.1.1"})
    assert errors == []


def test_validate_urls_valid_https():
    """Valid https URL passes without errors."""
    errors = validate_integration_urls({"plexUrl": "https://plex.local:32400"})
    assert errors == []


def test_validate_urls_multiple_valid():
    """Multiple valid URLs all pass."""
    errors = validate_integration_urls({
        "piholeUrl": "http://192.168.1.1",
        "plexUrl": "https://plex.local:32400",
    })
    assert errors == []


def test_validate_urls_invalid_scheme_file():
    """file:// scheme is rejected."""
    errors = validate_integration_urls({"piholeUrl": "file:///etc/passwd"})
    assert len(errors) == 1
    assert "file" in errors[0]


def test_validate_urls_invalid_scheme_ftp():
    """ftp:// scheme is rejected."""
    errors = validate_integration_urls({"backupUrl": "ftp://files.example.com"})
    assert len(errors) == 1
    assert "ftp" in errors[0]


def test_validate_urls_bare_hostname_ok():
    """Bare hostnames without a scheme are not rejected (no ://)."""
    errors = validate_integration_urls({
        "piholeUrl": "192.168.1.1:8080",
        "plexHost": "plex.local",
    })
    assert errors == []


def test_validate_urls_empty_string_ok():
    """Empty URL string is not rejected (integration not configured)."""
    errors = validate_integration_urls({"piholeUrl": ""})
    assert errors == []


def test_validate_urls_whitespace_only_ok():
    """Whitespace-only URL string is not rejected."""
    errors = validate_integration_urls({"plexUrl": "  "})
    assert errors == []


def test_validate_urls_non_url_key_ignored():
    """Keys that don't look like URLs are ignored even with bad values."""
    errors = validate_integration_urls({
        "refreshInterval": "ftp://should-be-ignored",
        "monitoredServices": "file:///also-ignored",
    })
    assert errors == []


def test_validate_urls_returns_error_message_with_key_name():
    """Error message includes the offending key name."""
    errors = validate_integration_urls({"piholeUrl": "file:///etc/passwd"})
    assert len(errors) == 1
    assert "piholeUrl" in errors[0]


def test_validate_urls_host_key_checked():
    """Keys containing 'host' are also validated."""
    errors = validate_integration_urls({"plexHost": "ftp://plex.local"})
    assert len(errors) == 1
    assert "ftp" in errors[0]


def test_validate_urls_server_key_checked():
    """Keys containing 'server' are also validated."""
    errors = validate_integration_urls({"mqttServer": "file:///var/run/mqtt"})
    assert len(errors) == 1


def test_validate_urls_endpoint_key_checked():
    """Keys containing 'endpoint' are also validated."""
    errors = validate_integration_urls({"apiEndpoint": "ftp://api.example.com"})
    assert len(errors) == 1
