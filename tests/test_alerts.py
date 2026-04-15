# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the alerts module: safe_eval condition parser."""
from server.alerts import _safe_eval


class TestSafeEval:
    def _flat(self, **kwargs):
        return {k: float(v) for k, v in kwargs.items()}

    def test_greater_than_true(self):
        assert _safe_eval("cpu_percent > 90", self._flat(cpu_percent=95))

    def test_greater_than_false(self):
        assert not _safe_eval("cpu_percent > 90", self._flat(cpu_percent=80))

    def test_less_than(self):
        assert _safe_eval("cpu_temp < 70", self._flat(cpu_temp=50))

    def test_greater_equal(self):
        assert _safe_eval("disk_percent >= 85", self._flat(disk_percent=85))

    def test_less_equal(self):
        assert _safe_eval("mem_percent <= 50", self._flat(mem_percent=50))

    def test_equal(self):
        assert _safe_eval("cpu_percent == 100", self._flat(cpu_percent=100))

    def test_not_equal(self):
        assert _safe_eval("cpu_percent != 50", self._flat(cpu_percent=75))

    def test_missing_metric(self):
        assert not _safe_eval("nonexistent > 0", {})

    def test_injection_attempt(self):
        assert not _safe_eval('import os; os.system("evil")', {})
        assert not _safe_eval("", {})
        assert not _safe_eval("no_operator", {})
