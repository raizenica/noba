# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing.dry_run: pipeline simulation without execution."""
from __future__ import annotations

from unittest.mock import MagicMock


class TestDryRun:
    def _make_event(self, target="proxmox-1", rule_id="cpu-high"):
        from server.healing.models import HealEvent
        return HealEvent(
            source="test", rule_id=rule_id, condition="cpu_percent > 95",
            target=target, severity="warning", timestamp=0,
            metrics={"cpu_percent": 97},
        )

    def test_dry_run_returns_simulation_result(self):
        from server.healing.dry_run import simulate_heal_event
        event = self._make_event()
        db = MagicMock()
        db.get_heal_outcomes = MagicMock(return_value=[])
        db.get_trust_state = MagicMock(return_value=None)
        db.get_heal_success_rate = MagicMock(return_value=0.0)
        result = simulate_heal_event(event, db=db)
        assert isinstance(result, dict)
        assert "would_correlate" in result
        assert "dependency_analysis" in result
        assert "would_select" in result
        assert "pre_flight" in result

    def test_dry_run_does_not_execute(self):
        from server.healing.dry_run import simulate_heal_event
        event = self._make_event()
        db = MagicMock()
        db.get_heal_outcomes = MagicMock(return_value=[])
        db.get_trust_state = MagicMock(return_value=None)
        db.get_heal_success_rate = MagicMock(return_value=0.0)
        db.insert_heal_outcome = MagicMock()
        simulate_heal_event(event, db=db)
        # insert_heal_outcome should NOT be called (no actual execution)
        db.insert_heal_outcome.assert_not_called()

    def test_dry_run_includes_action_details(self):
        from server.healing.dry_run import simulate_heal_event
        event = self._make_event()
        db = MagicMock()
        db.get_heal_outcomes = MagicMock(return_value=[])
        db.get_trust_state = MagicMock(return_value=None)
        db.get_heal_success_rate = MagicMock(return_value=0.0)
        result = simulate_heal_event(event, db=db, rules_cfg={
            "cpu-high": {
                "escalation_chain": [
                    {"action": "restart_service", "params": {"service": "nginx"}, "verify_timeout": 30},
                ],
            },
        })
        selected = result.get("would_select", {})
        assert selected.get("action") == "restart_service" or selected.get("action_type") == "restart_service"

    def test_dry_run_includes_rollback_info(self):
        from server.healing.dry_run import simulate_heal_event
        event = self._make_event()
        db = MagicMock()
        db.get_heal_outcomes = MagicMock(return_value=[])
        db.get_trust_state = MagicMock(return_value=None)
        db.get_heal_success_rate = MagicMock(return_value=0.0)
        result = simulate_heal_event(event, db=db, rules_cfg={
            "cpu-high": {
                "escalation_chain": [
                    {"action": "scale_container", "params": {"container": "app"}, "verify_timeout": 30},
                ],
            },
        })
        assert "rollback_plan" in result

    def test_dry_run_with_maintenance_shows_suppressed(self):
        from server.healing.dry_run import simulate_heal_event
        event = self._make_event()
        db = MagicMock()
        db.get_heal_outcomes = MagicMock(return_value=[])
        db.get_trust_state = MagicMock(return_value=None)
        db.get_heal_success_rate = MagicMock(return_value=0.0)
        result = simulate_heal_event(event, db=db, in_maintenance=True)
        assert result.get("suppressed") is True
        assert "maintenance" in result.get("suppression_reason", "").lower()
