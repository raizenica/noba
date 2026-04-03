# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing.condition_eval: safe_eval_single, safe_eval, flatten_metrics."""
from __future__ import annotations


from server.healing.condition_eval import (
    flatten_metrics,
    safe_eval,
    safe_eval_single,
    validate_condition,
)


class TestValidateCondition:
    def test_valid_simple(self):
        assert validate_condition("cpuPercent > 90") is None

    def test_valid_composite_and(self):
        assert validate_condition("cpuPercent > 80 AND memPercent > 70") is None

    def test_valid_composite_or(self):
        assert validate_condition("cpuPercent > 80 OR memPercent > 70") is None

    def test_valid_all_operators(self):
        for op in (">", "<", ">=", "<=", "==", "!="):
            assert validate_condition(f"metric {op} 42") is None

    def test_valid_array_metric(self):
        assert validate_condition("disks[0].percent >= 85") is None

    def test_valid_negative_threshold(self):
        assert validate_condition("temp > -10") is None

    def test_valid_decimal_threshold(self):
        assert validate_condition("load > 1.5") is None

    def test_empty_string(self):
        assert validate_condition("") is not None

    def test_whitespace_only(self):
        assert validate_condition("   ") is not None

    def test_bare_operator(self):
        err = validate_condition(">")
        assert err is not None
        assert "Invalid condition" in err

    def test_missing_threshold(self):
        err = validate_condition("cpuPercent >")
        assert err is not None

    def test_missing_operator(self):
        err = validate_condition("cpuPercent 90")
        assert err is not None

    def test_garbage_string(self):
        err = validate_condition("hello world foo bar")
        assert err is not None

    def test_injection_attempt(self):
        err = validate_condition("__import__('os').system('id') > 0")
        assert err is not None

    def test_composite_with_one_bad_part(self):
        err = validate_condition("cpuPercent > 80 AND badcondition")
        assert err is not None
        assert "Invalid condition" in err

    def test_string_threshold_rejected(self):
        err = validate_condition("cpu > abc")
        assert err is not None


class TestSafeEvalSingle:
    def test_greater_than_true(self):
        assert safe_eval_single("cpu_percent > 90", {"cpu_percent": 95.0}) is True

    def test_greater_than_false(self):
        assert safe_eval_single("cpu_percent > 90", {"cpu_percent": 80.0}) is False

    def test_less_than_true(self):
        assert safe_eval_single("cpu_temp < 70", {"cpu_temp": 50.0}) is True

    def test_less_than_false(self):
        assert safe_eval_single("cpu_temp < 70", {"cpu_temp": 80.0}) is False

    def test_missing_metric_returns_false(self):
        assert safe_eval_single("cpu_percent > 90", {}) is False

    def test_injection_attempt_returns_false(self):
        # Code injection in condition string should fail to parse and return False
        assert safe_eval_single("__import__('os').system('id') > 0", {}) is False

    def test_greater_equal(self):
        assert safe_eval_single("disk_percent >= 85", {"disk_percent": 85.0}) is True

    def test_less_equal(self):
        assert safe_eval_single("mem_percent <= 50", {"mem_percent": 50.0}) is True

    def test_equal(self):
        assert safe_eval_single("cpu_percent == 100", {"cpu_percent": 100.0}) is True

    def test_not_equal(self):
        assert safe_eval_single("cpu_percent != 50", {"cpu_percent": 75.0}) is True

    def test_flat_key_syntax_stripped(self):
        # Condition strings that include flat['key'] notation should still work
        assert safe_eval_single("flat['cpu_percent'] > 80", {"cpu_percent": 90.0}) is True


class TestSafeEval:
    def test_single_condition_true(self):
        assert safe_eval("cpu_percent > 80", {"cpu_percent": 90.0}) is True

    def test_single_condition_false(self):
        assert safe_eval("cpu_percent > 80", {"cpu_percent": 70.0}) is False

    def test_and_both_true(self):
        assert safe_eval(
            "cpu_percent > 80 AND mem_percent > 70",
            {"cpu_percent": 90.0, "mem_percent": 80.0},
        ) is True

    def test_and_one_false(self):
        assert safe_eval(
            "cpu_percent > 80 AND mem_percent > 70",
            {"cpu_percent": 90.0, "mem_percent": 50.0},
        ) is False

    def test_and_both_false(self):
        assert safe_eval(
            "cpu_percent > 80 AND mem_percent > 70",
            {"cpu_percent": 50.0, "mem_percent": 50.0},
        ) is False

    def test_or_one_true(self):
        assert safe_eval(
            "cpu_percent > 80 OR mem_percent > 70",
            {"cpu_percent": 50.0, "mem_percent": 80.0},
        ) is True

    def test_or_both_false(self):
        assert safe_eval(
            "cpu_percent > 80 OR mem_percent > 70",
            {"cpu_percent": 50.0, "mem_percent": 50.0},
        ) is False

    def test_or_both_true(self):
        assert safe_eval(
            "cpu_percent > 80 OR mem_percent > 70",
            {"cpu_percent": 90.0, "mem_percent": 80.0},
        ) is True


class TestFlattenMetrics:
    def test_scalar_values_preserved(self):
        stats = {"cpu_percent": 55.0, "mem_percent": 40, "hostname": "srv1"}
        flat = flatten_metrics(stats)
        assert flat["cpu_percent"] == 55.0
        assert flat["mem_percent"] == 40
        assert flat["hostname"] == "srv1"

    def test_nested_list_of_dicts(self):
        stats = {
            "disks": [
                {"name": "sda", "percent": 80.0},
                {"name": "sdb", "percent": 60.0},
            ]
        }
        flat = flatten_metrics(stats)
        assert flat["disks[0].percent"] == 80.0
        assert flat["disks[1].percent"] == 60.0

    def test_non_numeric_nested_values_skipped(self):
        stats = {
            "disks": [
                {"name": "sda", "percent": 80.0},
            ]
        }
        flat = flatten_metrics(stats)
        # "name" is a string, not numeric — should be excluded from flat
        assert "disks[0].name" not in flat
        assert "disks[0].percent" in flat

    def test_empty_stats(self):
        assert flatten_metrics({}) == {}

    def test_list_of_non_dicts_ignored(self):
        # A list that contains plain values (not dicts) should not be expanded
        stats = {"values": [1, 2, 3]}
        flat = flatten_metrics(stats)
        assert "values" not in flat
        assert "values[0]" not in flat
