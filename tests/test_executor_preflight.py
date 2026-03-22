"""Tests for executor pre-flight integration."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import threading


class TestExecutorPreflight:
    def test_execution_blocked_when_no_manifest(self):
        """If no capability manifest exists for the target host, action should fail gracefully."""
        from server.healing.executor import HealExecutor
        from server.healing.models import HealPlan, HealRequest, HealEvent

        event = HealEvent(
            source="alert", rule_id="test", condition="cpu > 90",
            target="unknown-host", severity="warning", timestamp=0, metrics={},
        )
        request = HealRequest(
            correlation_key="test:cpu", events=[event],
            primary_target="unknown-host", severity="warning", created_at=0,
        )
        plan = HealPlan(
            request=request, action_type="service_restart",
            action_params={"service": "nginx"}, escalation_step=0,
            trust_level="execute", reason="test", skipped_actions=[],
        )

        executor = HealExecutor(settle_times={"service_restart": 0})
        outcomes = []
        done = threading.Event()

        def on_complete(outcome):
            outcomes.append(outcome)
            done.set()

        # Mock DB to return None for manifest (unknown host)
        with patch("server.healing.executor._get_capability_manifest", return_value=None):
            executor.execute(plan, on_complete=on_complete)
            done.wait(timeout=5)

        assert len(outcomes) == 1
        assert outcomes[0].action_success is False
        assert "preflight" in (outcomes[0].verification_detail or "").lower() or "no_manifest" in (outcomes[0].verification_detail or "").lower()

    def test_execution_proceeds_when_no_fallback_chain(self):
        """Actions without fallback chains should skip preflight entirely."""
        from server.healing.executor import HealExecutor
        from server.healing.models import HealPlan, HealRequest, HealEvent

        event = HealEvent(
            source="alert", rule_id="test", condition="cpu > 90",
            target="myhost", severity="warning", timestamp=0,
            metrics={"cpu": 95},
        )
        request = HealRequest(
            correlation_key="test:cpu", events=[event],
            primary_target="myhost", severity="warning", created_at=0,
        )
        plan = HealPlan(
            request=request, action_type="webhook",
            action_params={"url": "http://example.com"}, escalation_step=0,
            trust_level="execute", reason="test", skipped_actions=[],
        )

        executor = HealExecutor(settle_times={"webhook": 0})
        outcomes = []
        done = threading.Event()

        def on_complete(outcome):
            outcomes.append(outcome)
            done.set()

        with patch("server.remediation.execute_action", return_value={"success": True, "output": "OK", "duration_s": 0.1}), \
             patch("server.healing.executor._get_fresh_metrics", return_value={"cpu": 50}):
            executor.execute(plan, on_complete=on_complete)
            done.wait(timeout=5)

        assert len(outcomes) == 1
        assert outcomes[0].action_success is True

    def test_execution_proceeds_when_preflight_passes(self):
        """When preflight passes, execution should proceed normally."""
        from server.healing.executor import HealExecutor
        from server.healing.models import HealPlan, HealRequest, HealEvent
        from server.healing.preflight import PreFlightResult

        event = HealEvent(
            source="alert", rule_id="test", condition="cpu > 90",
            target="myhost", severity="warning", timestamp=0,
            metrics={"cpu": 95},
        )
        request = HealRequest(
            correlation_key="test:cpu", events=[event],
            primary_target="myhost", severity="warning", created_at=0,
        )
        plan = HealPlan(
            request=request, action_type="service_restart",
            action_params={"service": "nginx"}, escalation_step=0,
            trust_level="execute", reason="test", skipped_actions=[],
        )

        executor = HealExecutor(settle_times={"service_restart": 0})
        outcomes = []
        done = threading.Event()

        def on_complete(outcome):
            outcomes.append(outcome)
            done.set()

        passed_result = PreFlightResult(
            passed=True, resolved_handler={"requires": "systemctl", "cmd": "systemctl restart {service}"},
        )

        with patch("server.healing.executor._get_capability_manifest", return_value=MagicMock()), \
             patch("server.healing.preflight.run_preflight", return_value=passed_result), \
             patch("server.remediation.execute_action", return_value={"success": True, "output": "OK", "duration_s": 0.1}), \
             patch("server.healing.executor._get_fresh_metrics", return_value={"cpu": 50}):
            executor.execute(plan, on_complete=on_complete)
            done.wait(timeout=5)

        assert len(outcomes) == 1
        assert outcomes[0].action_success is True
