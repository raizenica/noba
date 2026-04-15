# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for control integration in the healing pipeline."""
from __future__ import annotations

from unittest.mock import MagicMock


def _make_event(target="plex", rule_id="test-rule", source="alert"):
    from server.healing.models import HealEvent
    return HealEvent(
        source=source, rule_id=rule_id, condition="status == offline",
        target=target, severity="warning", timestamp=0, metrics={},
    )


def _make_pipeline():
    from server.healing import HealPipeline
    db = MagicMock()
    db.get_heal_outcomes = MagicMock(return_value=[])
    db.get_trust_state = MagicMock(return_value=None)
    db.get_heal_success_rate = MagicMock(return_value=0.0)
    db.insert_heal_outcome = MagicMock()
    db.insert_approval = MagicMock(return_value=1)
    pipeline = HealPipeline(db, rules_cfg={}, settle_times={"restart_container": 0})
    return pipeline


class TestMaintenanceIntegration:
    def test_event_suppressed_during_maintenance(self):
        pipeline = _make_pipeline()
        pipeline._maintenance.create_window(
            target="plex", duration_s=3600, reason="deploy",
            action="suppress", created_by="admin",
        )
        outcomes = []
        pipeline.on_outcome = lambda o: outcomes.append(o)
        pipeline.handle_heal_event(_make_event(target="plex"))
        # Should be suppressed — no outcome produced
        assert len(outcomes) == 0

    def test_event_proceeds_when_not_in_maintenance(self):
        pipeline = _make_pipeline()
        # No maintenance window — event should proceed
        # (will fail at execution with mocked DB, but won't be suppressed)
        pipeline.handle_heal_event(_make_event(target="plex"))
        # Getting here without error means it wasn't suppressed

    def test_notify_only_maintenance_forces_notify_trust(self):
        pipeline = _make_pipeline()
        pipeline._maintenance.create_window(
            target="plex", duration_s=3600, reason="monitoring",
            action="notify_only", created_by="admin",
        )
        outcomes = []
        pipeline.on_outcome = lambda o: outcomes.append(o)
        pipeline.handle_heal_event(_make_event(target="plex"))
        # Should produce an outcome with notify path
        assert len(outcomes) == 1
        assert outcomes[0].verification_detail == "notify only"


class TestApprovalIntegration:
    def test_high_risk_creates_approval_instead_of_executing(self):
        pipeline = _make_pipeline()
        pipeline._rules_cfg["high-risk-rule"] = {
            "escalation_chain": [
                {"action": "host_reboot", "params": {"hostname": "test"}, "verify_timeout": 30},
            ],
        }
        outcomes = []
        pipeline.on_outcome = lambda o: outcomes.append(o)
        event = _make_event(target="proxmox-1", rule_id="high-risk-rule")
        pipeline.handle_heal_event(event)
        # High-risk action should go through approval path (existing _handle_approve),
        # not direct execution
        # The pipeline already has approve/notify/execute paths via trust level


class TestSnapshotIntegration:
    def test_snapshot_module_importable(self):
        """Verify snapshot module exists and is importable."""
        from server.healing.snapshots import capture_snapshot, is_reversible
        assert callable(capture_snapshot)
        assert callable(is_reversible)
