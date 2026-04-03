# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing executor: async execution + condition verification."""
from __future__ import annotations

import threading
import time
from unittest.mock import patch


def _make_plan(action_type="restart_container", condition="cpu_percent > 90"):
    from server.healing.models import HealEvent, HealRequest, HealPlan
    event = HealEvent(
        source="alert", rule_id="r1", condition=condition,
        target="nginx", severity="warning",
        timestamp=time.time(), metrics={"cpu_percent": 95},
    )
    request = HealRequest(
        correlation_key="nginx", events=[event],
        primary_target="nginx", severity="warning",
        created_at=time.time(),
    )
    return HealPlan(
        request=request, action_type=action_type,
        action_params={"container": "nginx"},
        escalation_step=0, trust_level="execute",
    )


class TestExecutor:
    @patch("server.healing.executor._get_fresh_metrics")
    @patch("server.remediation.execute_action")
    def test_successful_heal(self, mock_exec, mock_metrics):
        from server.healing.executor import HealExecutor
        mock_exec.return_value = {"success": True, "output": "OK", "duration_s": 1.0}
        # After heal, cpu drops below threshold
        mock_metrics.return_value = {"cpu_percent": 40}

        results = []
        done = threading.Event()

        def on_complete(outcome):
            results.append(outcome)
            done.set()

        executor = HealExecutor(settle_times={"restart_container": 0.01})
        executor.execute(_make_plan(), on_complete)
        done.wait(timeout=5)

        assert len(results) == 1
        assert results[0].action_success is True
        assert results[0].verified is True

    @patch("server.healing.executor._get_fresh_metrics")
    @patch("server.remediation.execute_action")
    def test_unverified_heal(self, mock_exec, mock_metrics):
        from server.healing.executor import HealExecutor
        mock_exec.return_value = {"success": True, "output": "OK", "duration_s": 1.0}
        # After heal, cpu still above threshold
        mock_metrics.return_value = {"cpu_percent": 95}

        results = []
        done = threading.Event()

        def on_complete(outcome):
            results.append(outcome)
            done.set()

        executor = HealExecutor(settle_times={"restart_container": 0.01})
        executor.execute(_make_plan(), on_complete)
        done.wait(timeout=5)

        assert len(results) == 1
        assert results[0].action_success is True
        assert results[0].verified is False

    @patch("server.remediation.execute_action")
    def test_failed_action(self, mock_exec):
        from server.healing.executor import HealExecutor
        mock_exec.return_value = {"success": False, "error": "boom", "duration_s": 0.5}

        results = []
        done = threading.Event()

        def on_complete(outcome):
            results.append(outcome)
            done.set()

        executor = HealExecutor(settle_times={"restart_container": 0.01})
        executor.execute(_make_plan(), on_complete)
        done.wait(timeout=5)

        assert len(results) == 1
        assert results[0].action_success is False

    def test_execute_is_nonblocking(self):
        from server.healing.executor import HealExecutor
        executor = HealExecutor(settle_times={"restart_container": 10})
        start = time.time()
        with patch("server.remediation.execute_action", return_value={"success": True}):
            executor.execute(_make_plan(), lambda o: None)
        elapsed = time.time() - start
        assert elapsed < 1.0  # Must return immediately

    @patch("server.remediation.execute_action")
    def test_exception_propagation(self, mock_exec):
        """When execute_action raises, outcome captures failure + exception detail."""
        from server.healing.executor import HealExecutor
        mock_exec.side_effect = RuntimeError("container runtime crashed")

        results = []
        done = threading.Event()

        def on_complete(outcome):
            results.append(outcome)
            done.set()

        executor = HealExecutor(settle_times={"restart_container": 0.01})
        executor.execute(_make_plan(), on_complete)
        done.wait(timeout=5)

        assert len(results) == 1
        assert results[0].action_success is False
        assert results[0].verified is False
        assert "container runtime crashed" in results[0].verification_detail
        assert results[0].duration_s >= 0

    @patch("server.healing.executor._get_fresh_metrics")
    @patch("server.remediation.execute_action")
    def test_multiple_concurrent_actions(self, mock_exec, mock_metrics):
        """Multiple concurrent executions each produce independent outcomes."""
        from server.healing.executor import HealExecutor
        mock_exec.return_value = {"success": True, "output": "OK", "duration_s": 0.1}
        mock_metrics.return_value = {"cpu_percent": 40}

        results = []
        lock = threading.Lock()
        barrier = threading.Barrier(3, timeout=5)

        def on_complete(outcome):
            with lock:
                results.append(outcome)
            if len(results) >= 3:
                try:
                    barrier.wait(timeout=0)
                except threading.BrokenBarrierError:
                    pass

        executor = HealExecutor(settle_times={"restart_container": 0.01})
        for _ in range(3):
            executor.execute(_make_plan(), on_complete)

        # Wait for all to finish
        deadline = time.time() + 5
        while len(results) < 3 and time.time() < deadline:
            time.sleep(0.05)

        assert len(results) == 3
        for outcome in results:
            assert outcome.action_success is True
            assert outcome.verified is True

    @patch("server.healing.executor._get_capability_manifest")
    @patch("server.healing.preflight.run_preflight")
    @patch("server.remediation.execute_action")
    def test_preflight_failure_blocks_action(self, mock_exec, mock_preflight, mock_manifest):
        """When preflight fails, action is never executed."""
        from server.healing.executor import HealExecutor
        from server.healing.preflight import PreFlightResult

        mock_manifest.return_value = None
        mock_preflight.return_value = PreFlightResult(
            passed=False, failure_reason="no_manifest",
        )

        results = []
        done = threading.Event()

        def on_complete(outcome):
            results.append(outcome)
            done.set()

        # Use an action type that has a FALLBACK_CHAINS entry
        plan = _make_plan(action_type="service_restart")
        executor = HealExecutor(settle_times={"service_restart": 0.01})
        executor.execute(plan, on_complete)
        done.wait(timeout=5)

        assert len(results) == 1
        assert results[0].action_success is False
        assert results[0].verified is False
        assert "preflight_failed" in results[0].verification_detail
        # execute_action must NOT have been called
        mock_exec.assert_not_called()

    @patch("server.healing.executor._get_fresh_metrics")
    @patch("server.remediation.execute_action")
    def test_verification_failure_after_successful_action(self, mock_exec, mock_metrics):
        """Action succeeds but post-check shows condition still firing."""
        from server.healing.executor import HealExecutor
        mock_exec.return_value = {"success": True, "output": "restarted", "duration_s": 1.0}
        # Metrics still bad after heal
        mock_metrics.return_value = {"cpu_percent": 99}

        results = []
        done = threading.Event()

        def on_complete(outcome):
            results.append(outcome)
            done.set()

        executor = HealExecutor(settle_times={"restart_container": 0.01})
        executor.execute(_make_plan(), on_complete)
        done.wait(timeout=5)

        assert len(results) == 1
        assert results[0].action_success is True
        assert results[0].verified is False
        assert "still true" in results[0].verification_detail
        assert results[0].metrics_after is not None
        assert results[0].metrics_after.get("cpu_percent") == 99

    @patch("server.healing.executor._get_fresh_metrics")
    @patch("server.remediation.execute_action")
    def test_empty_action_params(self, mock_exec, mock_metrics):
        """Plan with empty action_params still executes normally."""
        from server.healing.executor import HealExecutor
        from server.healing.models import HealEvent, HealRequest, HealPlan
        mock_exec.return_value = {"success": True, "output": "OK", "duration_s": 0.5}
        mock_metrics.return_value = {"cpu_percent": 30}

        event = HealEvent(
            source="alert", rule_id="r1", condition="cpu_percent > 90",
            target="nginx", severity="warning",
            timestamp=time.time(), metrics={"cpu_percent": 95},
        )
        request = HealRequest(
            correlation_key="nginx", events=[event],
            primary_target="nginx", severity="warning",
            created_at=time.time(),
        )
        plan = HealPlan(
            request=request, action_type="webhook",
            action_params={},
            escalation_step=0, trust_level="execute",
        )

        results = []
        done = threading.Event()

        def on_complete(outcome):
            results.append(outcome)
            done.set()

        executor = HealExecutor(settle_times={"webhook": 0.01})
        executor.execute(plan, on_complete)
        done.wait(timeout=5)

        assert len(results) == 1
        assert results[0].action_success is True
        mock_exec.assert_called_once()
        # Verify empty params were passed through
        call_args = mock_exec.call_args
        assert call_args[0][1] == {}

    @patch("server.healing.executor._get_fresh_metrics")
    @patch("server.remediation.execute_action")
    def test_unknown_action_type_uses_default_settle(self, mock_exec, mock_metrics):
        """Action type not in settle_times dict falls back to default 15s settle."""
        from server.healing.executor import HealExecutor
        mock_exec.return_value = {"success": True, "output": "OK", "duration_s": 0.1}
        mock_metrics.return_value = {"cpu_percent": 10}

        results = []
        done = threading.Event()

        def on_complete(outcome):
            results.append(outcome)
            done.set()

        # Use custom settle_times that does NOT include our action type
        plan = _make_plan(action_type="custom_unknown_action")
        executor = HealExecutor(settle_times={"restart_container": 0.01})
        # The executor will use dict.get(..., 15) so it would wait 15s.
        # We patch time.sleep to avoid actually waiting.
        with patch("server.healing.executor.time.sleep") as mock_sleep:
            executor.execute(plan, on_complete)
            done.wait(timeout=5)

        assert len(results) == 1
        assert results[0].action_success is True
        # Verify it tried to sleep for the default 15 seconds
        mock_sleep.assert_called_once_with(15)

    @patch("server.healing.executor._get_fresh_metrics")
    @patch("server.remediation.execute_action")
    def test_no_events_plan(self, mock_exec, mock_metrics):
        """Plan with no events: metrics_before is empty, verification passes vacuously."""
        from server.healing.executor import HealExecutor
        from server.healing.models import HealRequest, HealPlan
        mock_exec.return_value = {"success": True, "output": "OK", "duration_s": 0.1}
        mock_metrics.return_value = {}

        request = HealRequest(
            correlation_key="nginx", events=[],
            primary_target="nginx", severity="warning",
            created_at=time.time(),
        )
        plan = HealPlan(
            request=request, action_type="webhook",
            action_params={"url": "http://example.com"},
            escalation_step=0, trust_level="execute",
        )

        results = []
        done = threading.Event()

        def on_complete(outcome):
            results.append(outcome)
            done.set()

        executor = HealExecutor(settle_times={"webhook": 0.01})
        executor.execute(plan, on_complete)
        done.wait(timeout=5)

        assert len(results) == 1
        assert results[0].action_success is True
        # No events means no conditions to check: verified should be True
        assert results[0].verified is True
        assert results[0].metrics_before == {}

    @patch("server.remediation.execute_action")
    def test_failed_action_includes_error_detail(self, mock_exec):
        """Failed action outcome carries the error message from result."""
        from server.healing.executor import HealExecutor
        mock_exec.return_value = {
            "success": False, "error": "container not found", "duration_s": 0.2,
        }

        results = []
        done = threading.Event()

        def on_complete(outcome):
            results.append(outcome)
            done.set()

        executor = HealExecutor(settle_times={"restart_container": 0.01})
        executor.execute(_make_plan(), on_complete)
        done.wait(timeout=5)

        assert len(results) == 1
        assert results[0].action_success is False
        assert results[0].verified is False
        assert results[0].verification_detail == "container not found"

    @patch("server.healing.executor._get_fresh_metrics")
    @patch("server.remediation.execute_action")
    def test_metrics_before_captured_from_event(self, mock_exec, mock_metrics):
        """Outcome records metrics_before from the first event and metrics_after from fresh."""
        from server.healing.executor import HealExecutor
        mock_exec.return_value = {"success": True, "output": "OK", "duration_s": 0.5}
        mock_metrics.return_value = {"cpu_percent": 25, "mem_percent": 40}

        results = []
        done = threading.Event()

        def on_complete(outcome):
            results.append(outcome)
            done.set()

        executor = HealExecutor(settle_times={"restart_container": 0.01})
        executor.execute(_make_plan(), on_complete)
        done.wait(timeout=5)

        assert len(results) == 1
        assert results[0].metrics_before == {"cpu_percent": 95}
        assert results[0].metrics_after is not None
        assert "cpu_percent" in results[0].metrics_after


class TestLedgerRecording:
    """Verify that HealOutcome is correctly recorded to the ledger."""

    def test_ledger_record_success(self):
        """Ledger record() extracts correct fields from a successful outcome."""
        from server.healing.ledger import record
        from server.healing.models import HealOutcome

        plan = _make_plan()
        outcome = HealOutcome(
            plan=plan,
            action_success=True,
            verified=True,
            verification_detail="cpu_percent > 90 resolved",
            duration_s=2.5,
            metrics_before={"cpu_percent": 95},
            metrics_after={"cpu_percent": 40},
        )

        from unittest.mock import MagicMock
        mock_db = MagicMock()
        mock_db.insert_heal_outcome.return_value = 42

        result_id = record(outcome, mock_db)
        assert result_id == 42
        mock_db.insert_heal_outcome.assert_called_once()

        call_kwargs = mock_db.insert_heal_outcome.call_args
        # Verify key fields
        assert call_kwargs.kwargs["correlation_key"] == "nginx"
        assert call_kwargs.kwargs["rule_id"] == "r1"
        assert call_kwargs.kwargs["target"] == "nginx"
        assert call_kwargs.kwargs["action_type"] == "restart_container"
        assert call_kwargs.kwargs["action_success"] is True
        assert call_kwargs.kwargs["verified"] is True
        assert call_kwargs.kwargs["duration_s"] == 2.5

    def test_ledger_record_failed_outcome(self):
        """Ledger record() handles failed outcome correctly."""
        from server.healing.ledger import record
        from server.healing.models import HealOutcome

        plan = _make_plan()
        outcome = HealOutcome(
            plan=plan,
            action_success=False,
            verified=False,
            verification_detail="Exception: boom",
            duration_s=0.1,
            metrics_before={"cpu_percent": 95},
        )

        from unittest.mock import MagicMock
        mock_db = MagicMock()
        mock_db.insert_heal_outcome.return_value = 7

        result_id = record(outcome, mock_db)
        assert result_id == 7
        call_kwargs = mock_db.insert_heal_outcome.call_args
        assert call_kwargs.kwargs["action_success"] is False
        assert call_kwargs.kwargs["verified"] is False

    def test_ledger_record_with_extra_audit_fields(self):
        """Ledger record() passes recognised extra fields through to DB."""
        from server.healing.ledger import record
        from server.healing.models import HealOutcome

        plan = _make_plan()
        outcome = HealOutcome(
            plan=plan,
            action_success=True,
            verified=True,
            duration_s=1.0,
            metrics_before={},
            extra={
                "risk_level": "high",
                "snapshot_id": "snap-123",
                "instance_id": "i-abc",
                "unknown_field": "ignored",
            },
        )

        from unittest.mock import MagicMock
        mock_db = MagicMock()
        mock_db.insert_heal_outcome.return_value = 99

        record(outcome, mock_db)
        call_kwargs = mock_db.insert_heal_outcome.call_args
        assert call_kwargs.kwargs["risk_level"] == "high"
        assert call_kwargs.kwargs["snapshot_id"] == "snap-123"
        assert call_kwargs.kwargs["instance_id"] == "i-abc"
        # unknown_field should NOT be passed
        assert "unknown_field" not in call_kwargs.kwargs

    def test_ledger_record_no_events(self):
        """Ledger record() handles plan with empty events list."""
        from server.healing.ledger import record
        from server.healing.models import HealOutcome, HealRequest, HealPlan

        request = HealRequest(
            correlation_key="test", events=[],
            primary_target="test-host", severity="info",
        )
        plan = HealPlan(
            request=request, action_type="webhook",
            action_params={}, escalation_step=0, trust_level="execute",
        )
        outcome = HealOutcome(
            plan=plan, action_success=True, verified=True,
            duration_s=0.5, metrics_before={},
        )

        from unittest.mock import MagicMock
        mock_db = MagicMock()
        mock_db.insert_heal_outcome.return_value = 1

        record(outcome, mock_db)
        call_kwargs = mock_db.insert_heal_outcome.call_args
        assert call_kwargs.kwargs["rule_id"] == ""
        assert call_kwargs.kwargs["condition"] == ""
        assert call_kwargs.kwargs["source"] == "unknown"
