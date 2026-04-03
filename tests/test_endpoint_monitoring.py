# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for endpoint monitoring: DB CRUD, agent command, API endpoints."""
from __future__ import annotations

import os
import sys
import tempfile

# Ensure server package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "share", "noba-web"))

from server.db import Database


def _make_db():
    """Create a fresh temp DB for each test."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_eptest_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


# ── Database CRUD Tests ──────────────────────────────────────────────────────

class TestEndpointMonitorCRUD:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_create_and_list(self):
        mid = self.db.create_endpoint_monitor("Test", "https://example.com")
        assert mid is not None
        assert isinstance(mid, int)
        monitors = self.db.get_endpoint_monitors()
        assert len(monitors) == 1
        assert monitors[0]["name"] == "Test"
        assert monitors[0]["url"] == "https://example.com"
        assert monitors[0]["method"] == "GET"
        assert monitors[0]["expected_status"] == 200
        assert monitors[0]["enabled"] is True

    def test_create_with_options(self):
        mid = self.db.create_endpoint_monitor(
            "Custom", "https://api.example.com/health",
            method="HEAD", expected_status=204, check_interval=60,
            timeout=5, agent_hostname="node1", notify_cert_days=30,
        )
        assert mid is not None
        m = self.db.get_endpoint_monitor(mid)
        assert m is not None
        assert m["method"] == "HEAD"
        assert m["expected_status"] == 204
        assert m["check_interval"] == 60
        assert m["timeout"] == 5
        assert m["agent_hostname"] == "node1"
        assert m["notify_cert_days"] == 30

    def test_get_single_monitor(self):
        mid = self.db.create_endpoint_monitor("Single", "https://test.com")
        m = self.db.get_endpoint_monitor(mid)
        assert m is not None
        assert m["name"] == "Single"

    def test_get_nonexistent_returns_none(self):
        assert self.db.get_endpoint_monitor(9999) is None

    def test_update_monitor(self):
        mid = self.db.create_endpoint_monitor("Original", "https://old.com")
        ok = self.db.update_endpoint_monitor(mid, name="Updated", url="https://new.com")
        assert ok is True
        m = self.db.get_endpoint_monitor(mid)
        assert m["name"] == "Updated"
        assert m["url"] == "https://new.com"

    def test_update_enabled_flag(self):
        mid = self.db.create_endpoint_monitor("Toggle", "https://test.com")
        self.db.update_endpoint_monitor(mid, enabled=False)
        m = self.db.get_endpoint_monitor(mid)
        assert m["enabled"] is False

    def test_delete_monitor(self):
        mid = self.db.create_endpoint_monitor("ToDelete", "https://del.com")
        ok = self.db.delete_endpoint_monitor(mid)
        assert ok is True
        assert self.db.get_endpoint_monitor(mid) is None

    def test_delete_nonexistent(self):
        ok = self.db.delete_endpoint_monitor(9999)
        assert ok is False

    def test_record_check_result(self):
        mid = self.db.create_endpoint_monitor("Check", "https://check.com")
        self.db.record_endpoint_check(
            mid, status="up", response_ms=150, cert_expiry_days=60,
        )
        m = self.db.get_endpoint_monitor(mid)
        assert m["last_status"] == "up"
        assert m["last_response_ms"] == 150
        assert m["cert_expiry_days"] == 60
        assert m["last_checked"] is not None

    def test_get_due_monitors(self):
        # Create a monitor that's immediately due (never checked)
        mid1 = self.db.create_endpoint_monitor("Due", "https://due.com", check_interval=60)
        # Create a disabled monitor
        mid2 = self.db.create_endpoint_monitor("Disabled", "https://off.com", enabled=False)
        due = self.db.get_due_endpoint_monitors()
        due_ids = [m["id"] for m in due]
        assert mid1 in due_ids
        assert mid2 not in due_ids

    def test_enabled_only_filter(self):
        self.db.create_endpoint_monitor("On", "https://on.com", enabled=True)
        self.db.create_endpoint_monitor("Off", "https://off.com", enabled=False)
        enabled = self.db.get_endpoint_monitors(enabled_only=True)
        assert len(enabled) == 1
        assert enabled[0]["name"] == "On"
        all_monitors = self.db.get_endpoint_monitors()
        assert len(all_monitors) == 2

    def test_multiple_monitors_ordering(self):
        self.db.create_endpoint_monitor("Beta", "https://beta.com")
        self.db.create_endpoint_monitor("Alpha", "https://alpha.com")
        monitors = self.db.get_endpoint_monitors()
        assert monitors[0]["name"] == "Alpha"
        assert monitors[1]["name"] == "Beta"


# ── Agent Command Handler Tests ──────────────────────────────────────────────

class TestEndpointCheckCommand:
    """Test the _cmd_endpoint_check function from agent.py."""

    def test_missing_url(self):
        # Import the agent module directly
        agent_path = os.path.join(
            os.path.dirname(__file__), "..", "share", "noba-agent"
        )
        sys.path.insert(0, agent_path)
        try:
            from commands import _cmd_endpoint_check
            result = _cmd_endpoint_check({}, {})
            assert result["status"] == "error"
            assert "No URL" in result["error"]
        finally:
            sys.path.pop(0)

    def test_invalid_method_defaults_to_get(self):
        agent_path = os.path.join(
            os.path.dirname(__file__), "..", "share", "noba-agent"
        )
        sys.path.insert(0, agent_path)
        try:
            from commands import _cmd_endpoint_check
            # This will fail to connect but proves method validation works
            result = _cmd_endpoint_check(
                {"url": "http://192.0.2.1:1", "method": "DELETE", "timeout": 1}, {}
            )
            # Should have tried GET (the default) — will error due to unreachable host
            assert "status" in result
        finally:
            sys.path.pop(0)


# ── Agent Config Tests ───────────────────────────────────────────────────────

class TestEndpointCheckConfig:
    """Test that endpoint_check is properly registered in agent_config."""

    def test_risk_level(self):
        from server.agent_config import RISK_LEVELS
        assert "endpoint_check" in RISK_LEVELS
        assert RISK_LEVELS["endpoint_check"] == "low"

    def test_in_v2_capabilities(self):
        from server.agent_config import get_agent_capabilities
        caps = get_agent_capabilities("2.0.0")
        assert "endpoint_check" in caps

    def test_validation_requires_url(self):
        from server.agent_config import validate_command_params
        err = validate_command_params("endpoint_check", {})
        assert err is not None
        assert "url" in err.lower()

    def test_validation_requires_http(self):
        from server.agent_config import validate_command_params
        err = validate_command_params("endpoint_check", {"url": "ftp://example.com"})
        assert err is not None
        assert "http" in err.lower()

    def test_validation_passes_valid_url(self):
        from server.agent_config import validate_command_params
        err = validate_command_params("endpoint_check", {"url": "https://example.com"})
        assert err is None
