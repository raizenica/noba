# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for Round 2 alert enhancements: composite conditions, grouping,
maintenance windows, cooldown, heal state, and _safe_eval_single."""
from __future__ import annotations

import time
from unittest.mock import patch

from server.alerts import AlertState, _safe_eval, _safe_eval_single, in_maintenance_window


# ── Composite AND/OR conditions ──────────────────────────────────────────────
class TestCompositeAlerts:
    def test_single_condition_true(self):
        assert _safe_eval("cpuPercent > 80", {"cpuPercent": 90}) is True

    def test_single_condition_false(self):
        assert _safe_eval("cpuPercent > 80", {"cpuPercent": 50}) is False

    def test_and_both_true(self):
        assert _safe_eval(
            "cpuPercent > 80 AND memPercent > 70",
            {"cpuPercent": 90, "memPercent": 80},
        ) is True

    def test_and_one_false(self):
        assert _safe_eval(
            "cpuPercent > 80 AND memPercent > 70",
            {"cpuPercent": 90, "memPercent": 50},
        ) is False

    def test_and_both_false(self):
        assert _safe_eval(
            "cpuPercent > 80 AND memPercent > 70",
            {"cpuPercent": 50, "memPercent": 50},
        ) is False

    def test_or_one_true(self):
        assert _safe_eval(
            "cpuPercent > 80 OR memPercent > 70",
            {"cpuPercent": 50, "memPercent": 80},
        ) is True

    def test_or_both_true(self):
        assert _safe_eval(
            "cpuPercent > 80 OR memPercent > 70",
            {"cpuPercent": 90, "memPercent": 80},
        ) is True

    def test_or_both_false(self):
        assert _safe_eval(
            "cpuPercent > 80 OR memPercent > 70",
            {"cpuPercent": 50, "memPercent": 50},
        ) is False

    def test_malformed_returns_false(self):
        assert _safe_eval("bad condition", {}) is False

    def test_and_three_conditions(self):
        assert _safe_eval(
            "a > 1 AND b > 2 AND c > 3",
            {"a": 5, "b": 5, "c": 5},
        ) is True

    def test_and_three_conditions_one_false(self):
        assert _safe_eval(
            "a > 1 AND b > 2 AND c > 3",
            {"a": 5, "b": 5, "c": 1},
        ) is False

    def test_or_three_conditions_one_true(self):
        assert _safe_eval(
            "a > 100 OR b > 100 OR c > 3",
            {"a": 1, "b": 1, "c": 5},
        ) is True


# ── Alert grouping ───────────────────────────────────────────────────────────
class TestAlertGrouping:
    def test_buffer_and_flush(self):
        state = AlertState()
        state.buffer_group("cpu_group", "CPU high: 90%")
        state.buffer_group("cpu_group", "CPU high: 95%")
        msgs = state.flush_group("cpu_group")
        assert len(msgs) == 2
        assert msgs[0] == "CPU high: 90%"
        assert msgs[1] == "CPU high: 95%"
        assert state.flush_group("cpu_group") == []  # empty after flush

    def test_flush_nonexistent_group(self):
        state = AlertState()
        assert state.flush_group("nonexistent") == []

    def test_separate_groups(self):
        state = AlertState()
        state.buffer_group("group_a", "msg_a1")
        state.buffer_group("group_b", "msg_b1")
        state.buffer_group("group_a", "msg_a2")
        assert state.flush_group("group_a") == ["msg_a1", "msg_a2"]
        assert state.flush_group("group_b") == ["msg_b1"]

    def test_flush_is_destructive(self):
        state = AlertState()
        state.buffer_group("g", "first")
        state.flush_group("g")
        state.buffer_group("g", "second")
        msgs = state.flush_group("g")
        assert msgs == ["second"]


# ── Maintenance window ───────────────────────────────────────────────────────
class TestMaintenanceWindow:
    def test_not_in_window_empty(self):
        """No maintenance windows configured -> not in maintenance."""
        mock_fn = lambda: {"maintenanceWindows": []}  # noqa: E731
        assert in_maintenance_window(mock_fn) is False

    def test_not_in_window_no_key(self):
        """Missing maintenanceWindows key -> not in maintenance."""
        mock_fn = lambda: {}  # noqa: E731
        assert in_maintenance_window(mock_fn) is False

    @patch("server.scheduler._match_cron", return_value=True)
    def test_in_window_when_cron_matches(self, _mock_cron):
        """When _match_cron returns True for a window, we should be in maintenance."""
        mock_fn = lambda: {  # noqa: E731
            "maintenanceWindows": [{"start": "0 2 * * *", "duration_minutes": 60}]
        }
        assert in_maintenance_window(mock_fn) is True

    @patch("server.scheduler._match_cron", return_value=False)
    def test_not_in_window_when_cron_no_match(self, _mock_cron):
        """When _match_cron returns False, not in maintenance."""
        mock_fn = lambda: {  # noqa: E731
            "maintenanceWindows": [{"start": "0 2 * * *", "duration_minutes": 60}]
        }
        assert in_maintenance_window(mock_fn) is False


# ── Cooldown and heal state ──────────────────────────────────────────────────
class TestAlertState:
    def test_cooldown_ok_first_call(self):
        state = AlertState()
        assert state.cooldown_ok("test_key", cooldown=60) is True

    def test_cooldown_blocks_rapid_calls(self):
        state = AlertState()
        state.cooldown_ok("test_key", cooldown=60)
        assert state.cooldown_ok("test_key", cooldown=60) is False

    def test_cooldown_different_keys_independent(self):
        state = AlertState()
        assert state.cooldown_ok("key_a", cooldown=60) is True
        assert state.cooldown_ok("key_b", cooldown=60) is True

    def test_cooldown_expires(self):
        state = AlertState()
        state.cooldown_ok("test_key", cooldown=0)
        # With cooldown=0, next call should pass immediately
        assert state.cooldown_ok("test_key", cooldown=0) is True

    def test_heal_state_defaults(self):
        state = AlertState()
        h = state.heal_state("rule1")
        assert h["retries"] == 0
        assert h["circuit_open"] is False
        assert h["trigger_times"] == []
        assert h["circuit_open_at"] == 0

    def test_heal_state_returns_copy(self):
        """heal_state should return a copy, not a reference to internal state."""
        state = AlertState()
        h1 = state.heal_state("rule1")
        h1["retries"] = 999
        h2 = state.heal_state("rule1")
        assert h2["retries"] == 0

    def test_increment_retries(self):
        state = AlertState()
        assert state.increment_retries("rule1") == 1
        assert state.increment_retries("rule1") == 2
        assert state.increment_retries("rule1") == 3

    def test_reset_retries(self):
        state = AlertState()
        state.increment_retries("rule1")
        state.increment_retries("rule1")
        state.reset_retries("rule1")
        h = state.heal_state("rule1")
        assert h["retries"] == 0

    def test_reset_retries_nonexistent(self):
        """Resetting retries for a rule that was never tracked should not error."""
        state = AlertState()
        state.reset_retries("never_seen")  # should not raise

    def test_trigger_count(self):
        state = AlertState()
        now = time.time()
        state.append_trigger("rule1", now)
        state.append_trigger("rule1", now + 1)
        assert state.trigger_count("rule1") == 2

    def test_trigger_count_empty(self):
        state = AlertState()
        assert state.trigger_count("rule1") == 0

    def test_trigger_times_expire_after_one_hour(self):
        """Triggers older than 1 hour should be pruned on append."""
        state = AlertState()
        old_ts = time.time() - 7200  # 2 hours ago
        state.append_trigger("rule1", old_ts)
        # Appending a new trigger prunes old ones
        now = time.time()
        state.append_trigger("rule1", now)
        assert state.trigger_count("rule1") == 1

    def test_update_heal(self):
        state = AlertState()
        state.update_heal("rule1", circuit_open=True, circuit_open_at=12345)
        h = state.heal_state("rule1")
        assert h["circuit_open"] is True
        assert h["circuit_open_at"] == 12345


# ── _safe_eval_single (renamed original) ─────────────────────────────────────
class TestSafeEvalSingle:
    def test_greater_than(self):
        assert _safe_eval_single("x > 5", {"x": 10}) is True
        assert _safe_eval_single("x > 5", {"x": 3}) is False

    def test_less_than(self):
        assert _safe_eval_single("x < 5", {"x": 3}) is True
        assert _safe_eval_single("x < 5", {"x": 10}) is False

    def test_greater_equal(self):
        assert _safe_eval_single("x >= 10", {"x": 10}) is True
        assert _safe_eval_single("x >= 10", {"x": 9}) is False

    def test_less_equal(self):
        assert _safe_eval_single("x <= 10", {"x": 10}) is True
        assert _safe_eval_single("x <= 10", {"x": 11}) is False

    def test_equal(self):
        assert _safe_eval_single("x == 10", {"x": 10}) is True
        assert _safe_eval_single("x == 10", {"x": 5}) is False

    def test_not_equal(self):
        assert _safe_eval_single("x != 10", {"x": 5}) is True
        assert _safe_eval_single("x != 10", {"x": 10}) is False

    def test_missing_metric(self):
        assert _safe_eval_single("missing > 5", {}) is False

    def test_malformed_condition(self):
        assert _safe_eval_single("not a condition", {}) is False

    def test_empty_condition(self):
        assert _safe_eval_single("", {}) is False

    def test_float_comparison(self):
        assert _safe_eval_single("temp > 72.5", {"temp": 73.0}) is True
        assert _safe_eval_single("temp > 72.5", {"temp": 72.0}) is False

    def test_negative_threshold(self):
        assert _safe_eval_single("delta > -5", {"delta": 0}) is True
        assert _safe_eval_single("delta > -5", {"delta": -10}) is False

    def test_nested_metric_name(self):
        assert _safe_eval_single("disks[0].percent > 80", {"disks[0].percent": 95}) is True

    def test_injection_attempt(self):
        assert _safe_eval_single('import os; os.system("bad")', {}) is False
