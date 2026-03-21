"""Tests for per-rule autonomy enforcement in evaluate_alert_rules."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_rule(autonomy=None, action_type="restart_service", rule_id="rule-1"):
    """Build a minimal alert rule dict that will fire on cpu_percent > 50."""
    rule = {
        "id": rule_id,
        "condition": "cpu_percent > 50",
        "severity": "warning",
        "message": "CPU high",
        "channels": [],
        "action": {"type": action_type, "target": "nginx.service"},
    }
    if autonomy is not None:
        rule["autonomy"] = autonomy
    return rule


def _make_settings(rule):
    """Wrap a rule into a settings dict as read_settings_fn would return."""
    return {"alertRules": [rule], "notifications": {}}


def _flat_stats():
    """Stats dict that satisfies cpu_percent > 50."""
    return {"cpu_percent": 95.0}


def _run(rule, active_windows=None, *, mock_execute_heal=None, mock_dispatch=None,
         mock_insert_approval=None):
    """
    Run evaluate_alert_rules with the given rule.

    Patches:
    - server.db.db methods (insert_alert_history, insert_incident,
      get_active_maintenance_windows, insert_approval)
    - dispatch_notifications
    - _execute_heal
    - _alert_state (cooldown always passes, circuit not open)

    Returns (mock_dispatch, mock_execute_heal, mock_insert_approval)
    """
    from server.alerts import evaluate_alert_rules
    import server.db

    if active_windows is None:
        active_windows = []
    if mock_execute_heal is None:
        mock_execute_heal = MagicMock(return_value=True)
    if mock_dispatch is None:
        mock_dispatch = MagicMock()
    if mock_insert_approval is None:
        mock_insert_approval = MagicMock(return_value=1)

    settings = _make_settings(rule)

    # Patch methods directly on the live db singleton
    real_db = server.db.db
    with patch.object(real_db, "insert_alert_history", MagicMock()), \
         patch.object(real_db, "insert_incident", MagicMock()), \
         patch.object(real_db, "get_active_maintenance_windows",
                      MagicMock(return_value=active_windows)), \
         patch.object(real_db, "insert_approval", mock_insert_approval), \
         patch("server.alerts._execute_heal", mock_execute_heal), \
         patch("server.alerts.dispatch_notifications", mock_dispatch), \
         patch("server.alerts._alert_state") as mock_state:

        # Configure alert state so cooldown always passes and circuit is not open
        mock_state.cooldown_ok.return_value = True
        mock_state.heal_state.return_value = {
            "retries": 0, "trigger_times": [], "circuit_open": False, "circuit_open_at": 0,
        }
        mock_state.trigger_count.return_value = 1
        mock_state.increment_retries.return_value = 1

        evaluate_alert_rules(_flat_stats(), lambda: settings)

    return mock_dispatch, mock_execute_heal, mock_insert_approval


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestAutonomyExecute:
    def test_action_runs_immediately(self):
        """autonomy=execute → _execute_heal is called."""
        rule = _make_rule(autonomy="execute")
        mock_dispatch, mock_execute_heal, _ = _run(rule)
        mock_execute_heal.assert_called_once()

    def test_notification_dispatched(self):
        """autonomy=execute → notification is dispatched (unmodified message)."""
        rule = _make_rule(autonomy="execute")
        mock_dispatch, _, _ = _run(rule)
        mock_dispatch.assert_called()
        # Message should NOT have an approval prefix
        args = mock_dispatch.call_args[0]
        assert "[APPROVAL NEEDED]" not in args[1]

    def test_default_behaves_as_execute(self):
        """No autonomy field → defaults to execute → _execute_heal is called."""
        rule = _make_rule()  # no autonomy key
        assert "autonomy" not in rule
        _, mock_execute_heal, _ = _run(rule)
        mock_execute_heal.assert_called_once()


class TestAutonomyNotify:
    def test_no_action_called(self):
        """autonomy=notify → _execute_heal is NOT called."""
        rule = _make_rule(autonomy="notify")
        _, mock_execute_heal, _ = _run(rule)
        mock_execute_heal.assert_not_called()

    def test_notification_dispatched(self):
        """autonomy=notify → dispatch_notifications IS called."""
        rule = _make_rule(autonomy="notify")
        mock_dispatch, _, _ = _run(rule)
        mock_dispatch.assert_called()

    def test_no_approval_queued(self):
        """autonomy=notify → insert_approval is NOT called."""
        rule = _make_rule(autonomy="notify")
        _, _, mock_insert_approval = _run(rule)
        mock_insert_approval.assert_not_called()


class TestAutonomyApprove:
    def test_no_action_called(self):
        """autonomy=approve → _execute_heal is NOT called."""
        rule = _make_rule(autonomy="approve")
        _, mock_execute_heal, _ = _run(rule)
        mock_execute_heal.assert_not_called()

    def test_approval_queued(self):
        """autonomy=approve → db.insert_approval is called."""
        rule = _make_rule(autonomy="approve")
        _, _, mock_insert_approval = _run(rule)
        mock_insert_approval.assert_called_once()

    def test_approval_queued_with_correct_type(self):
        """autonomy=approve → insert_approval receives action_type from rule."""
        rule = _make_rule(autonomy="approve", action_type="flush_dns")
        mock_insert_approval = MagicMock(return_value=1)
        _run(rule, mock_insert_approval=mock_insert_approval)
        kwargs = mock_insert_approval.call_args[1]
        assert kwargs["action_type"] == "flush_dns"

    def test_notification_has_approval_prefix(self):
        """autonomy=approve → notification message starts with '[APPROVAL NEEDED]'."""
        rule = _make_rule(autonomy="approve")
        mock_dispatch, _, _ = _run(rule)
        mock_dispatch.assert_called()
        args = mock_dispatch.call_args[0]
        assert args[1].startswith("[APPROVAL NEEDED]")

    def test_approval_rule_id_in_automation_id(self):
        """autonomy=approve → insert_approval sets automation_id to rule_id."""
        rule = _make_rule(autonomy="approve", rule_id="my-rule-42")
        mock_insert_approval = MagicMock(return_value=1)
        _run(rule, mock_insert_approval=mock_insert_approval)
        kwargs = mock_insert_approval.call_args[1]
        assert kwargs["automation_id"] == "my-rule-42"


class TestAutonomyDisabled:
    def test_no_action_called(self):
        """autonomy=disabled → _execute_heal is NOT called."""
        rule = _make_rule(autonomy="disabled")
        _, mock_execute_heal, _ = _run(rule)
        mock_execute_heal.assert_not_called()

    def test_no_notification_dispatched(self):
        """autonomy=disabled → dispatch_notifications is NOT called."""
        rule = _make_rule(autonomy="disabled")
        mock_dispatch, _, _ = _run(rule)
        mock_dispatch.assert_not_called()

    def test_no_approval_queued(self):
        """autonomy=disabled → insert_approval is NOT called."""
        rule = _make_rule(autonomy="disabled")
        _, _, mock_insert_approval = _run(rule)
        mock_insert_approval.assert_not_called()


class TestMaintenanceWindowOverride:
    def test_window_overrides_execute_to_approve(self):
        """Active window with override_autonomy=approve overrides rule's execute level."""
        rule = _make_rule(autonomy="execute")
        window = {"id": 1, "name": "Maintenance", "override_autonomy": "approve"}
        mock_insert_approval = MagicMock(return_value=1)
        mock_dispatch = MagicMock()
        mock_execute_heal = MagicMock(return_value=True)

        _run(
            rule,
            active_windows=[window],
            mock_execute_heal=mock_execute_heal,
            mock_dispatch=mock_dispatch,
            mock_insert_approval=mock_insert_approval,
        )

        # Should NOT execute immediately
        mock_execute_heal.assert_not_called()
        # Should queue approval
        mock_insert_approval.assert_called_once()
        # Should send approval notification
        args = mock_dispatch.call_args[0]
        assert args[1].startswith("[APPROVAL NEEDED]")

    def test_window_overrides_execute_to_notify(self):
        """Active window with override_autonomy=notify suppresses action."""
        rule = _make_rule(autonomy="execute")
        window = {"id": 2, "name": "Maintenance", "override_autonomy": "notify"}
        _, mock_execute_heal, mock_insert_approval = _run(
            rule, active_windows=[window]
        )
        mock_execute_heal.assert_not_called()
        mock_insert_approval.assert_not_called()

    def test_window_overrides_execute_to_disabled(self):
        """Active window with override_autonomy=disabled skips everything."""
        rule = _make_rule(autonomy="execute")
        window = {"id": 3, "name": "Maintenance", "override_autonomy": "disabled"}
        mock_dispatch, mock_execute_heal, mock_insert_approval = _run(
            rule, active_windows=[window]
        )
        mock_execute_heal.assert_not_called()
        mock_dispatch.assert_not_called()
        mock_insert_approval.assert_not_called()

    def test_window_without_override_does_not_change_autonomy(self):
        """Active window with no override_autonomy does not change rule behavior."""
        rule = _make_rule(autonomy="execute")
        window = {"id": 4, "name": "Maintenance", "override_autonomy": None}
        _, mock_execute_heal, _ = _run(rule, active_windows=[window])
        # Rule autonomy=execute should still run
        mock_execute_heal.assert_called_once()

    def test_first_overriding_window_wins(self):
        """When multiple windows exist, first one with override_autonomy wins."""
        rule = _make_rule(autonomy="execute")
        windows = [
            {"id": 1, "name": "No override", "override_autonomy": None},
            {"id": 2, "name": "Override to notify", "override_autonomy": "notify"},
            {"id": 3, "name": "Override to approve", "override_autonomy": "approve"},
        ]
        _, mock_execute_heal, mock_insert_approval = _run(rule, active_windows=windows)
        # Second window wins (first with override_autonomy set) → notify
        mock_execute_heal.assert_not_called()
        mock_insert_approval.assert_not_called()  # notify, not approve


class TestNewActionTypeDelegation:
    def test_flush_dns_delegates_to_remediation(self):
        """action.type=flush_dns → remediation.execute_action is called."""
        from server.alerts import _execute_heal
        import server.remediation as rem_module

        action_cfg = {"type": "flush_dns"}
        mock_result = {"success": True, "output": "DNS flushed"}

        with patch.object(rem_module, "execute_action", return_value=mock_result) as mock_exec:
            result = _execute_heal(action_cfg, "rule-dns", lambda: {})

        mock_exec.assert_called_once()
        assert mock_exec.call_args[0][0] == "flush_dns"
        assert result is True

    def test_clear_cache_delegates_to_remediation(self):
        """action.type=clear_cache → remediation.execute_action is called."""
        from server.alerts import _execute_heal
        import server.remediation as rem_module

        action_cfg = {"type": "clear_cache", "target": "system"}

        with patch.object(rem_module, "execute_action",
                          return_value={"success": True, "output": "cleared"}) as mock_exec:
            result = _execute_heal(action_cfg, "rule-cache", lambda: {})

        mock_exec.assert_called_once()
        assert result is True

    def test_trigger_backup_delegates_to_remediation(self):
        """action.type=trigger_backup → remediation.execute_action is called."""
        from server.alerts import _execute_heal
        import server.remediation as rem_module

        action_cfg = {"type": "trigger_backup", "source": "home"}

        with patch.object(rem_module, "execute_action",
                          return_value={"success": True, "output": "ok"}) as mock_exec:
            result = _execute_heal(action_cfg, "rule-backup", lambda: {})

        mock_exec.assert_called_once()
        assert mock_exec.call_args[0][0] == "trigger_backup"

    def test_scale_container_delegates_to_remediation(self):
        """action.type=scale_container → remediation.execute_action is called."""
        from server.alerts import _execute_heal
        import server.remediation as rem_module

        action_cfg = {"type": "scale_container", "container": "app", "cpu_limit": "2"}

        with patch.object(rem_module, "execute_action",
                          return_value={"success": False, "error": "fail"}) as mock_exec:
            result = _execute_heal(action_cfg, "rule-scale", lambda: {})

        mock_exec.assert_called_once()
        assert result is False

    def test_run_playbook_delegates_to_remediation(self):
        """action.type=run_playbook → remediation.execute_action is called."""
        from server.alerts import _execute_heal
        import server.remediation as rem_module

        action_cfg = {"type": "run_playbook", "playbook_id": "pb-001"}

        with patch.object(rem_module, "execute_action",
                          return_value={"success": True, "output": "started"}) as mock_exec:
            result = _execute_heal(action_cfg, "rule-playbook", lambda: {})

        mock_exec.assert_called_once()
        assert mock_exec.call_args[0][0] == "run_playbook"

    def test_failover_dns_delegates_to_remediation(self):
        """action.type=failover_dns → remediation.execute_action is called."""
        from server.alerts import _execute_heal
        import server.remediation as rem_module

        action_cfg = {"type": "failover_dns", "primary": "1.1.1.1", "secondary": "8.8.8.8"}

        with patch.object(rem_module, "execute_action",
                          return_value={"success": True, "output": "done"}) as mock_exec:
            _execute_heal(action_cfg, "rule-failover", lambda: {})

        mock_exec.assert_called_once()

    def test_legacy_restart_service_not_delegated(self):
        """action.type=restart_service uses original handler, NOT remediation."""
        from server.alerts import _execute_heal
        import server.remediation as rem_module

        action_cfg = {"type": "restart_service", "target": "nginx.service"}

        with patch.object(rem_module, "execute_action",
                          return_value={"success": True}) as mock_exec, \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _execute_heal(action_cfg, "rule-svc", lambda: {})

        mock_exec.assert_not_called()

    def test_legacy_restart_container_not_delegated(self):
        """action.type=restart_container uses original handler, NOT remediation."""
        from server.alerts import _execute_heal
        import server.remediation as rem_module

        action_cfg = {"type": "restart_container", "target": "myapp"}

        with patch.object(rem_module, "execute_action",
                          return_value={"success": True}) as mock_exec, \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _execute_heal(action_cfg, "rule-ct", lambda: {})

        mock_exec.assert_not_called()
