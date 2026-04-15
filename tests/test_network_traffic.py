# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for network traffic analysis: agent command + agent_config risk level."""
from __future__ import annotations

import os
import sys
import threading
import time

# Ensure agent package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "share", "noba-agent"))
# Ensure server package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "share", "noba-web"))


# ── Agent command tests ───────────────────────────────────────────────────────

class TestCmdNetworkStats:
    """Test _cmd_network_stats from agent.py."""

    def test_returns_ok_status(self):
        from commands import _cmd_network_stats
        result = _cmd_network_stats({}, {})
        assert result["status"] == "ok"

    def test_has_interfaces_key(self):
        from commands import _cmd_network_stats
        result = _cmd_network_stats({}, {})
        assert "interfaces" in result
        assert isinstance(result["interfaces"], list)

    def test_has_connections_key(self):
        from commands import _cmd_network_stats
        result = _cmd_network_stats({}, {})
        assert "connections" in result
        assert isinstance(result["connections"], list)

    def test_has_top_talkers_key(self):
        from commands import _cmd_network_stats
        result = _cmd_network_stats({}, {})
        assert "top_talkers" in result
        assert isinstance(result["top_talkers"], list)

    def test_interface_fields(self):
        from commands import _cmd_network_stats
        result = _cmd_network_stats({}, {})
        for iface in result["interfaces"]:
            assert "name" in iface
            assert "rx_bytes" in iface
            assert "tx_bytes" in iface
            assert "rx_rate" in iface
            assert "tx_rate" in iface
            # Values should be non-negative
            assert iface["rx_bytes"] >= 0
            assert iface["tx_bytes"] >= 0
            assert iface["rx_rate"] >= 0
            assert iface["tx_rate"] >= 0

    def test_lo_excluded(self):
        from commands import _cmd_network_stats
        result = _cmd_network_stats({}, {})
        iface_names = [i["name"] for i in result["interfaces"]]
        assert "lo" not in iface_names

    def test_rate_calculation_on_second_call(self):
        """Second call should produce non-zero rates if traffic occurred."""
        from commands import _cmd_network_stats
        # First call sets the baseline
        _cmd_network_stats({}, {})
        # Small sleep to get a non-zero dt
        time.sleep(0.05)
        # Second call should have rates (they might be 0 if no traffic)
        result = _cmd_network_stats({}, {})
        for iface in result["interfaces"]:
            # Rates should be >= 0 (not negative even if counters wrapped)
            assert iface["rx_rate"] >= 0
            assert iface["tx_rate"] >= 0

    def test_connections_capped_at_200(self):
        from commands import _cmd_network_stats
        result = _cmd_network_stats({}, {})
        assert len(result["connections"]) <= 200

    def test_top_talkers_capped_at_20(self):
        from commands import _cmd_network_stats
        result = _cmd_network_stats({}, {})
        assert len(result["top_talkers"]) <= 20


class TestPrevNetReadingsThreadSafety:
    """Ensure the module-level _prev_net_readings is protected by its lock."""

    def test_concurrent_calls(self):
        from commands import _cmd_network_stats
        errors = []

        def worker():
            try:
                for _ in range(5):
                    result = _cmd_network_stats({}, {})
                    assert result["status"] == "ok"
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert not errors, f"Thread errors: {errors}"


# ── agent_config risk level tests ─────────────────────────────────────────────

class TestNetworkStatsRiskLevel:
    """Verify network_stats is registered in RISK_LEVELS."""

    def test_in_risk_levels(self):
        from server.agent_config import RISK_LEVELS
        assert "network_stats" in RISK_LEVELS

    def test_risk_is_low(self):
        from server.agent_config import RISK_LEVELS
        assert RISK_LEVELS["network_stats"] == "low"

    def test_viewer_cannot_execute(self):
        from server.agent_config import RISK_LEVELS, check_role_permission
        risk = RISK_LEVELS["network_stats"]
        assert not check_role_permission("viewer", risk)

    def test_operator_can_execute(self):
        from server.agent_config import RISK_LEVELS, check_role_permission
        risk = RISK_LEVELS["network_stats"]
        assert check_role_permission("operator", risk)

    def test_admin_can_execute(self):
        from server.agent_config import RISK_LEVELS, check_role_permission
        risk = RISK_LEVELS["network_stats"]
        assert check_role_permission("admin", risk)

    def test_in_v2_capabilities(self):
        from server.agent_config import get_agent_capabilities
        caps = get_agent_capabilities("2.0.0")
        assert "network_stats" in caps


# ── Agent handler registry test ───────────────────────────────────────────────

class TestNetworkStatsInHandlers:
    """Verify network_stats is in the execute_commands handler map."""

    def test_handler_registered(self):
        from commands import execute_commands
        # Execute a network_stats command and check it doesn't return 'Unknown command'
        results = execute_commands(
            [{"type": "network_stats", "id": "test-1", "params": {}}],
            {},
        )
        assert len(results) == 1
        assert results[0]["status"] == "ok"
        assert results[0]["type"] == "network_stats"
        assert "interfaces" in results[0]
