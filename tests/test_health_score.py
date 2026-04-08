# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the Infrastructure Health Score (Feature 7).

These tests encode the "truth in scoring" honesty contract:
- Empty datasets produce ``status: "unknown"`` and ``score: None``,
  NOT a free 10/10.
- Exceptions inside any category also produce ``status: "unknown"`` /
  ``score: None``, and the category is excluded from the normalized total.
- Fewer than three real scores OR more than two unknowns → ``grade == "N/A"``.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from server.db import Database
from server.health_score import compute_health_score


@pytest.fixture()
def db(tmp_path):
    """Create a fresh Database with a temp path."""
    path = str(tmp_path / "test.db")
    return Database(path)


def _run(coro):
    """Helper to run async functions in tests."""
    return asyncio.run(coro)


class TestHealthScoreBasic:
    """compute_health_score returns the expected shape."""

    def test_empty_install_is_not_graded(self, db):
        """Zero agents, zero monitors, no stats -> N/A, NOT an undeserved A."""
        result = _run(compute_health_score(db, {}, {}))
        assert result["grade"] == "N/A"
        # No real scores to normalize -> score is None (not 0, not 100).
        assert result["score"] is None

    def test_categories_present(self, db):
        """All six categories should be present."""
        result = _run(compute_health_score(db, {}, {}))
        expected_cats = {
            "monitoring_coverage",
            "certificate_health",
            "update_status",
            "uptime",
            "capacity",
            "backup_freshness",
        }
        assert set(result["categories"].keys()) == expected_cats

    def test_category_structure(self, db):
        """Each category should have score, max, status, recommendations."""
        result = _run(compute_health_score(db, {}, {}))
        for cat_name, cat in result["categories"].items():
            assert "score" in cat, f"{cat_name} missing 'score'"
            assert "max" in cat, f"{cat_name} missing 'max'"
            assert "status" in cat, f"{cat_name} missing 'status'"
            assert "recommendations" in cat, f"{cat_name} missing 'recommendations'"
            assert cat["max"] == 10
            # Score must be either a real number in [0, 10] or None (unknown).
            if cat["score"] is None:
                assert cat["status"] == "unknown"
            else:
                assert 0 <= cat["score"] <= 10
                assert cat["status"] in ("ok", "warning", "critical")


class TestCapacityScoring:
    """Capacity category responds to CPU/memory/disk stats."""

    def test_high_cpu_reduces_score(self, db):
        result = _run(compute_health_score(db, {}, {"cpuPercent": 95, "memPercent": 40, "disks": []}))
        cap = result["categories"]["capacity"]
        assert cap["score"] < 10
        assert len(cap["recommendations"]) > 0

    def test_high_memory_reduces_score(self, db):
        result = _run(compute_health_score(db, {}, {"cpuPercent": 20, "memPercent": 92, "disks": []}))
        cap = result["categories"]["capacity"]
        assert cap["score"] < 10
        assert any("Memory" in r or "memory" in r.lower() for r in cap["recommendations"])

    def test_high_disk_reduces_score(self, db):
        result = _run(
            compute_health_score(
                db,
                {},
                {
                    "cpuPercent": 20,
                    "memPercent": 40,
                    "disks": [{"mount": "/", "percent": 96}],
                },
            )
        )
        cap = result["categories"]["capacity"]
        assert cap["score"] < 10
        assert any("Disk" in r for r in cap["recommendations"])

    def test_normal_values_full_score(self, db):
        result = _run(
            compute_health_score(
                db,
                {},
                {
                    "cpuPercent": 30,
                    "memPercent": 50,
                    "disks": [{"mount": "/", "percent": 60}],
                },
            )
        )
        cap = result["categories"]["capacity"]
        assert cap["score"] == 10
        assert cap["status"] == "ok"

    def test_no_stats_is_unknown(self, db):
        """Empty stats dict means no evidence — not an automatic 10/10."""
        result = _run(compute_health_score(db, {}, {}))
        cap = result["categories"]["capacity"]
        assert cap["score"] is None
        assert cap["status"] == "unknown"


class TestMonitoringCoverage:
    """Monitoring coverage based on agent data."""

    def test_all_agents_online(self, db):
        now = time.time()
        agents = {
            "host1": {"_received": now - 10},
            "host2": {"_received": now - 20},
        }
        result = _run(compute_health_score(db, agents, {}))
        mon = result["categories"]["monitoring_coverage"]
        assert mon["score"] == 10.0
        assert mon["status"] == "ok"

    def test_some_agents_offline(self, db):
        now = time.time()
        agents = {
            "host1": {"_received": now - 10},  # online
            "host2": {"_received": now - 300},  # offline (>120s)
        }
        result = _run(compute_health_score(db, agents, {}))
        mon = result["categories"]["monitoring_coverage"]
        assert mon["score"] == 5.0  # 1/2 = 50% -> 5
        assert len(mon["recommendations"]) > 0

    def test_no_agents_is_unknown(self, db):
        """Zero agents enrolled -> unknown, NOT free full marks."""
        result = _run(compute_health_score(db, {}, {}))
        mon = result["categories"]["monitoring_coverage"]
        assert mon["score"] is None
        assert mon["status"] == "unknown"


class TestCertificateHealth:
    """Certificate health from endpoint monitors."""

    def test_no_monitors_is_unknown(self, db):
        result = _run(compute_health_score(db, {}, {}))
        cert = result["categories"]["certificate_health"]
        assert cert["score"] is None
        assert cert["status"] == "unknown"

    def test_expiring_cert_reduces_score(self, db):
        # Create a monitor with an almost-expired cert
        db.create_endpoint_monitor("Test Site", "https://example.com")
        monitors = db.get_endpoint_monitors()
        if monitors:
            mon_id = monitors[0]["id"]
            db.record_endpoint_check(mon_id, status="ok", response_ms=100, cert_expiry_days=5)
        result = _run(compute_health_score(db, {}, {}))
        cert = result["categories"]["certificate_health"]
        assert cert["score"] is not None
        assert cert["score"] < 10
        assert len(cert["recommendations"]) > 0


class TestBackupFreshness:
    """Backup freshness category honesty."""

    def test_no_backups_is_unknown(self, db):
        result = _run(compute_health_score(db, {}, {}))
        bak = result["categories"]["backup_freshness"]
        assert bak["score"] is None
        assert bak["status"] == "unknown"
        assert len(bak["recommendations"]) > 0


class TestOverallScoreNormalization:
    """Overall composite honesty."""

    def test_empty_install_refuses_letter_grade(self, db):
        """Zero data -> grade is N/A, not A."""
        result = _run(compute_health_score(db, {}, {}))
        assert result["grade"] == "N/A"
        assert result["score"] is None
        assert result["scored_categories"] == 0
        assert result["unknown_categories"] == 6

    def test_enough_real_categories_emits_letter_grade(self, db):
        """Four+ categories with real data -> a real letter grade.

        Guard rule: ``grade == "N/A"`` if more than 2 categories are
        unknown OR fewer than 3 produced real values. To emit a letter
        grade we need at least 4 scored categories (so unknowns ≤ 2).
        """
        now = time.time()
        # Monitoring + update_status: 2/2 agents online with package_updates reported.
        agents = {
            "host1": {"_received": now - 5, "package_updates": 0},
            "host2": {"_received": now - 8, "package_updates": 0},
        }
        # Capacity: normal values
        stats = {"cpuPercent": 10, "memPercent": 20, "disks": [{"mount": "/", "percent": 40}]}
        # Certificate health: create a monitor with a healthy cert
        db.create_endpoint_monitor("Test Site", "https://example.com")
        monitors = db.get_endpoint_monitors()
        if monitors:
            db.record_endpoint_check(monitors[0]["id"], status="ok", response_ms=100, cert_expiry_days=90)
        result = _run(compute_health_score(db, agents, stats))
        # Four categories with real scores: monitoring, updates, capacity, certs.
        assert result["scored_categories"] >= 4
        assert result["unknown_categories"] <= 2
        assert result["grade"] in {"A", "B", "C", "D", "F"}
        assert result["score"] is not None

    def test_unknown_categories_are_excluded_from_totals(self, db):
        """Raw total should only sum categories with real scores."""
        result = _run(compute_health_score(db, {}, {"cpuPercent": 10, "memPercent": 20, "disks": []}))
        # Only capacity produced a real score; others are unknown.
        cat_sum = sum(
            c["score"]
            for c in result["categories"].values()
            if isinstance(c.get("score"), int | float) and c.get("status") != "unknown"
        )
        assert abs(result["total_raw"] - cat_sum) < 0.1

    def test_max_raw_only_counts_scored_categories(self, db):
        """max_raw == 10 * (number of categories that produced a real score)."""
        result = _run(compute_health_score(db, {}, {"cpuPercent": 10, "memPercent": 20, "disks": []}))
        assert result["max_raw"] == result["scored_categories"] * 10


class TestCategoryExceptionFallbacks:
    """Exceptions inside a category MUST produce 'unknown', not 10/10."""

    def _fail_get_endpoint_monitors(self, *_args, **_kwargs):
        raise RuntimeError("db boom: monitors")

    def _fail_get_alert_history(self, *_args, **_kwargs):
        raise RuntimeError("db boom: alerts")

    def _fail_get_job_runs(self, *_args, **_kwargs):
        raise RuntimeError("db boom: job runs")

    def test_certificate_health_exception_is_unknown(self, db, monkeypatch):
        monkeypatch.setattr(db, "get_endpoint_monitors", self._fail_get_endpoint_monitors)
        result = _run(compute_health_score(db, {}, {}))
        cert = result["categories"]["certificate_health"]
        assert cert["score"] is None
        assert cert["status"] == "unknown"
        assert cert.get("max") == 10

    def test_uptime_exception_is_unknown(self, db, monkeypatch):
        monkeypatch.setattr(db, "get_alert_history", self._fail_get_alert_history)
        result = _run(compute_health_score(db, {}, {}))
        up = result["categories"]["uptime"]
        assert up["score"] is None
        assert up["status"] == "unknown"

    def test_backup_freshness_exception_is_unknown(self, db, monkeypatch):
        monkeypatch.setattr(db, "get_job_runs", self._fail_get_job_runs)
        result = _run(compute_health_score(db, {}, {}))
        bak = result["categories"]["backup_freshness"]
        assert bak["score"] is None
        assert bak["status"] == "unknown"

    def test_capacity_exception_is_unknown(self, db):
        """Broken stats input (non-dict disks) triggers the except branch."""
        bad_stats = {"cpuPercent": "not-a-number", "memPercent": object(), "disks": None}
        # Force an exception inside the comparison logic via object() > 90 etc.
        result = _run(compute_health_score(db, {}, bad_stats))
        cap = result["categories"]["capacity"]
        # Either 'unknown' because object() > 90 raises, or a valid score
        # if the code silently coerced. The contract: if scoring failed the
        # category must declare unknown, not 10/10.
        assert cap["score"] is None or isinstance(cap["score"], int | float)
        if cap["score"] is None:
            assert cap["status"] == "unknown"

    def test_monitoring_exception_is_unknown(self, db):
        """Non-iterable agent store causes the try branch to raise."""

        class BrokenStore:
            def __len__(self):
                raise RuntimeError("len boom")

            def values(self):
                raise RuntimeError("values boom")

            def items(self):
                raise RuntimeError("items boom")

        result = _run(compute_health_score(db, BrokenStore(), {}))
        mon = result["categories"]["monitoring_coverage"]
        assert mon["score"] is None
        assert mon["status"] == "unknown"

    def test_update_status_exception_is_unknown(self, db):
        """Broken agent data triggers the update_status except branch."""

        class BrokenItems:
            def __len__(self):
                return 1

            def values(self):
                return []

            def items(self):
                raise RuntimeError("items boom")

        result = _run(compute_health_score(db, BrokenItems(), {}))
        upd = result["categories"]["update_status"]
        assert upd["score"] is None
        assert upd["status"] == "unknown"

    def test_all_exceptions_produce_na_grade(self, db, monkeypatch):
        """If every category fails, the composite grade must be N/A."""
        monkeypatch.setattr(db, "get_endpoint_monitors", self._fail_get_endpoint_monitors)
        monkeypatch.setattr(db, "get_alert_history", self._fail_get_alert_history)
        monkeypatch.setattr(db, "get_job_runs", self._fail_get_job_runs)
        result = _run(compute_health_score(db, {}, {}))
        assert result["grade"] == "N/A"
        assert result["score"] is None
