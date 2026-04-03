# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the Infrastructure Health Score (Feature 7)."""
from __future__ import annotations

import asyncio
import time

import pytest

from server.db import Database
from server.health_score import compute_health_score


@pytest.fixture()
def db(tmp_path):
    """Create a fresh in-memory-like Database with a temp path."""
    path = str(tmp_path / "test.db")
    return Database(path)


def _run(coro):
    """Helper to run async functions in tests."""
    return asyncio.run(coro)


class TestHealthScoreBasic:
    """Test compute_health_score returns the expected structure."""

    def test_empty_data_returns_full_score(self, db):
        """With no agents and no monitors, expect maximum score."""
        result = _run(compute_health_score(db, {}, {}))
        assert "score" in result
        assert "categories" in result
        assert "timestamp" in result
        assert "grade" in result
        assert 0 <= result["score"] <= 100
        # With no data to penalize, should be high
        assert result["score"] >= 80

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
            assert 0 <= cat["score"] <= 10
            assert cat["status"] in ("ok", "warning", "critical")

    def test_grade_assignment(self, db):
        """Score-to-grade mapping."""
        result = _run(compute_health_score(db, {}, {}))
        score = result["score"]
        grade = result["grade"]
        if score >= 90:
            assert grade == "A"
        elif score >= 75:
            assert grade == "B"
        elif score >= 60:
            assert grade == "C"
        elif score >= 40:
            assert grade == "D"
        else:
            assert grade == "F"


class TestCapacityScoring:
    """Test capacity category responds to CPU/memory/disk stats."""

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
        result = _run(compute_health_score(db, {}, {
            "cpuPercent": 20, "memPercent": 40,
            "disks": [{"mount": "/", "percent": 96}],
        }))
        cap = result["categories"]["capacity"]
        assert cap["score"] < 10
        assert any("Disk" in r for r in cap["recommendations"])

    def test_normal_values_full_score(self, db):
        result = _run(compute_health_score(db, {}, {
            "cpuPercent": 30, "memPercent": 50,
            "disks": [{"mount": "/", "percent": 60}],
        }))
        cap = result["categories"]["capacity"]
        assert cap["score"] == 10
        assert cap["status"] == "ok"


class TestMonitoringCoverage:
    """Test monitoring coverage based on agent data."""

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
            "host1": {"_received": now - 10},   # online
            "host2": {"_received": now - 300},   # offline (>120s)
        }
        result = _run(compute_health_score(db, agents, {}))
        mon = result["categories"]["monitoring_coverage"]
        assert mon["score"] == 5.0  # 1/2 = 50% -> 5
        assert len(mon["recommendations"]) > 0

    def test_no_agents_full_score(self, db):
        result = _run(compute_health_score(db, {}, {}))
        mon = result["categories"]["monitoring_coverage"]
        assert mon["score"] == 10.0


class TestCertificateHealth:
    """Test certificate health from endpoint monitors."""

    def test_no_monitors_full_score(self, db):
        result = _run(compute_health_score(db, {}, {}))
        cert = result["categories"]["certificate_health"]
        assert cert["score"] == 10

    def test_expiring_cert_reduces_score(self, db):
        # Create a monitor with an almost-expired cert
        db.create_endpoint_monitor("Test Site", "https://example.com")
        monitors = db.get_endpoint_monitors()
        if monitors:
            mon_id = monitors[0]["id"]
            db.record_endpoint_check(mon_id, status="ok", response_ms=100,
                                     cert_expiry_days=5)
        result = _run(compute_health_score(db, {}, {}))
        cert = result["categories"]["certificate_health"]
        assert cert["score"] < 10
        assert len(cert["recommendations"]) > 0


class TestBackupFreshness:
    """Test backup freshness category."""

    def test_no_backups_partial_score(self, db):
        result = _run(compute_health_score(db, {}, {}))
        bak = result["categories"]["backup_freshness"]
        assert bak["score"] == 5.0  # no data -> neutral
        assert len(bak["recommendations"]) > 0


class TestOverallScoreNormalization:
    """Test that the score is properly normalized to 0-100."""

    def test_score_is_percentage(self, db):
        result = _run(compute_health_score(db, {}, {}))
        assert isinstance(result["score"], int)
        assert 0 <= result["score"] <= 100

    def test_raw_total_matches_categories(self, db):
        result = _run(compute_health_score(db, {}, {}))
        cat_sum = sum(c["score"] for c in result["categories"].values())
        assert abs(result["total_raw"] - cat_sum) < 0.1

    def test_max_raw_is_60(self, db):
        """6 categories * 10 max each = 60."""
        result = _run(compute_health_score(db, {}, {}))
        assert result["max_raw"] == 60
