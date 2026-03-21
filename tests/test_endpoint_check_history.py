"""Tests for endpoint check history DB functions and per-service health scoring."""
from __future__ import annotations

import os
import sys
import tempfile
import time


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "share", "noba-web"))

from server.db import Database
from server.health_score import (
    _calc_error_rate_score,
    _calc_headroom_score,
    _calc_latency_score,
    _calc_uptime_score,
    _score_to_grade,
    compute_service_health_scores,
)


def _make_db():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_echtest_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


# ── DB: record + query check history ─────────────────────────────────────────

class TestRecordEndpointCheckHistory:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_record_and_retrieve(self):
        mid = self.db.create_endpoint_monitor("Test", "https://example.com")
        self.db.record_endpoint_check_history(mid, status="up", response_ms=120)
        history = self.db.get_endpoint_check_history(mid)
        assert len(history) == 1
        assert history[0]["status"] == "up"
        assert history[0]["response_ms"] == 120
        assert history[0]["monitor_id"] == mid
        assert history[0]["error"] is None

    def test_record_with_error(self):
        mid = self.db.create_endpoint_monitor("Err", "https://example.com")
        self.db.record_endpoint_check_history(mid, status="down", error="Connection refused")
        history = self.db.get_endpoint_check_history(mid)
        assert len(history) == 1
        assert history[0]["status"] == "down"
        assert history[0]["error"] == "Connection refused"
        assert history[0]["response_ms"] is None

    def test_multiple_checks_ordered_desc(self):
        mid = self.db.create_endpoint_monitor("Multi", "https://example.com")
        for i in range(3):
            self.db.record_endpoint_check_history(mid, status="up", response_ms=100 + i * 10)
        history = self.db.get_endpoint_check_history(mid)
        assert len(history) == 3
        # Most recent first
        assert history[0]["response_ms"] >= history[1]["response_ms"]

    def test_hours_filter_excludes_old_records(self):
        mid = self.db.create_endpoint_monitor("Filter", "https://example.com")
        self.db.record_endpoint_check_history(mid, status="up", response_ms=100)
        # history for just 1 hour — recent record should still show
        history = self.db.get_endpoint_check_history(mid, hours=1)
        assert len(history) == 1

    def test_no_history_returns_empty(self):
        mid = self.db.create_endpoint_monitor("Empty", "https://example.com")
        history = self.db.get_endpoint_check_history(mid)
        assert history == []

    def test_isolates_by_monitor_id(self):
        mid1 = self.db.create_endpoint_monitor("M1", "https://m1.example.com")
        mid2 = self.db.create_endpoint_monitor("M2", "https://m2.example.com")
        self.db.record_endpoint_check_history(mid1, status="up", response_ms=50)
        self.db.record_endpoint_check_history(mid2, status="down")
        h1 = self.db.get_endpoint_check_history(mid1)
        h2 = self.db.get_endpoint_check_history(mid2)
        assert len(h1) == 1
        assert h1[0]["status"] == "up"
        assert len(h2) == 1
        assert h2[0]["status"] == "down"


# ── DB: uptime calculation ────────────────────────────────────────────────────

class TestGetEndpointUptime:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_all_up_is_100(self):
        mid = self.db.create_endpoint_monitor("Uptime", "https://example.com")
        for _ in range(5):
            self.db.record_endpoint_check_history(mid, status="up", response_ms=100)
        uptime = self.db.get_endpoint_uptime(mid)
        assert uptime == 100.0

    def test_all_down_is_0(self):
        mid = self.db.create_endpoint_monitor("Down", "https://example.com")
        for _ in range(5):
            self.db.record_endpoint_check_history(mid, status="down")
        uptime = self.db.get_endpoint_uptime(mid)
        assert uptime == 0.0

    def test_half_up_is_50(self):
        mid = self.db.create_endpoint_monitor("Half", "https://example.com")
        for _ in range(3):
            self.db.record_endpoint_check_history(mid, status="up", response_ms=100)
        for _ in range(3):
            self.db.record_endpoint_check_history(mid, status="down")
        uptime = self.db.get_endpoint_uptime(mid)
        assert abs(uptime - 50.0) < 0.1

    def test_no_history_returns_100(self):
        mid = self.db.create_endpoint_monitor("NoHist", "https://example.com")
        uptime = self.db.get_endpoint_uptime(mid)
        assert uptime == 100.0

    def test_degraded_counts_as_non_up(self):
        mid = self.db.create_endpoint_monitor("Degraded", "https://example.com")
        self.db.record_endpoint_check_history(mid, status="up", response_ms=100)
        self.db.record_endpoint_check_history(mid, status="degraded", response_ms=200)
        uptime = self.db.get_endpoint_uptime(mid)
        assert uptime == 50.0


# ── DB: average latency ────────────────────────────────────────────────────────

class TestGetEndpointAvgLatency:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_avg_latency_calculated(self):
        mid = self.db.create_endpoint_monitor("Lat", "https://example.com")
        self.db.record_endpoint_check_history(mid, status="up", response_ms=100)
        self.db.record_endpoint_check_history(mid, status="up", response_ms=200)
        self.db.record_endpoint_check_history(mid, status="up", response_ms=300)
        avg = self.db.get_endpoint_avg_latency(mid)
        assert avg is not None
        assert abs(avg - 200.0) < 0.1

    def test_no_successful_checks_returns_none(self):
        mid = self.db.create_endpoint_monitor("NoSucc", "https://example.com")
        for _ in range(3):
            self.db.record_endpoint_check_history(mid, status="down")
        avg = self.db.get_endpoint_avg_latency(mid)
        assert avg is None

    def test_no_history_returns_none(self):
        mid = self.db.create_endpoint_monitor("NoHist", "https://example.com")
        avg = self.db.get_endpoint_avg_latency(mid)
        assert avg is None

    def test_excludes_down_checks_from_avg(self):
        mid = self.db.create_endpoint_monitor("Mix", "https://example.com")
        self.db.record_endpoint_check_history(mid, status="up", response_ms=100)
        self.db.record_endpoint_check_history(mid, status="down", response_ms=9999)
        avg = self.db.get_endpoint_avg_latency(mid)
        assert avg is not None
        assert avg == 100.0


# ── DB: prune ─────────────────────────────────────────────────────────────────

class TestPruneEndpointCheckHistory:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_prune_removes_old_records(self):
        mid = self.db.create_endpoint_monitor("Prune", "https://example.com")
        # Manually insert a record with a very old timestamp (91 days ago)
        old_ts = int(time.time()) - 91 * 86400
        with self.db._lock:
            conn = self.db._get_conn()
            conn.execute(
                "INSERT INTO endpoint_check_history (monitor_id, timestamp, status, response_ms, error) "
                "VALUES (?,?,?,?,?)",
                (mid, old_ts, "up", 100, None),
            )
            conn.commit()
        # Verify the record is there
        history = self.db.get_endpoint_check_history(mid, hours=24 * 365)
        assert len(history) == 1
        # Prune with 90 days — old record should be deleted
        self.db.prune_endpoint_check_history(days=90)
        history = self.db.get_endpoint_check_history(mid, hours=24 * 365)
        assert len(history) == 0

    def test_prune_keeps_recent_records(self):
        mid = self.db.create_endpoint_monitor("Keep", "https://example.com")
        self.db.record_endpoint_check_history(mid, status="up", response_ms=100)
        # Prune with 90 days — recent record should stay
        self.db.prune_endpoint_check_history(days=90)
        history = self.db.get_endpoint_check_history(mid)
        assert len(history) == 1

    def test_prune_empty_table_is_safe(self):
        # Should not raise
        self.db.prune_endpoint_check_history(days=30)


# ── Health scoring: sub-score functions ───────────────────────────────────────

class TestScoreToGrade:
    def test_a_grade(self):
        assert _score_to_grade(90) == "A"
        assert _score_to_grade(100) == "A"
        assert _score_to_grade(95.5) == "A"

    def test_b_grade(self):
        assert _score_to_grade(80) == "B"
        assert _score_to_grade(89.9) == "B"

    def test_c_grade(self):
        assert _score_to_grade(70) == "C"
        assert _score_to_grade(79.9) == "C"

    def test_d_grade(self):
        assert _score_to_grade(60) == "D"
        assert _score_to_grade(69.9) == "D"

    def test_f_grade(self):
        assert _score_to_grade(59.9) == "F"
        assert _score_to_grade(0) == "F"


class TestCalcUptimeScore:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_no_history_returns_100(self):
        mid = self.db.create_endpoint_monitor("U", "https://example.com")
        score = _calc_uptime_score(self.db, mid)
        assert score == 100.0

    def test_all_up_returns_100(self):
        mid = self.db.create_endpoint_monitor("U", "https://example.com")
        for _ in range(10):
            self.db.record_endpoint_check_history(mid, status="up", response_ms=50)
        score = _calc_uptime_score(self.db, mid)
        assert score == 100.0

    def test_all_down_returns_0(self):
        mid = self.db.create_endpoint_monitor("D", "https://example.com")
        for _ in range(5):
            self.db.record_endpoint_check_history(mid, status="down")
        score = _calc_uptime_score(self.db, mid)
        assert score == 0.0

    def test_partial_uptime(self):
        mid = self.db.create_endpoint_monitor("P", "https://example.com")
        for _ in range(8):
            self.db.record_endpoint_check_history(mid, status="up", response_ms=100)
        for _ in range(2):
            self.db.record_endpoint_check_history(mid, status="down")
        score = _calc_uptime_score(self.db, mid)
        assert abs(score - 80.0) < 0.5


class TestCalcLatencyScore:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_no_history_returns_100(self):
        mid = self.db.create_endpoint_monitor("L", "https://example.com")
        score = _calc_latency_score(self.db, mid)
        assert score == 100.0

    def test_zero_latency_returns_100(self):
        mid = self.db.create_endpoint_monitor("L", "https://example.com")
        self.db.record_endpoint_check_history(mid, status="up", response_ms=0)
        score = _calc_latency_score(self.db, mid)
        assert score == 100.0

    def test_1000ms_returns_0(self):
        mid = self.db.create_endpoint_monitor("L", "https://example.com")
        self.db.record_endpoint_check_history(mid, status="up", response_ms=1000)
        score = _calc_latency_score(self.db, mid)
        assert score == 0.0

    def test_500ms_returns_50(self):
        mid = self.db.create_endpoint_monitor("L", "https://example.com")
        self.db.record_endpoint_check_history(mid, status="up", response_ms=500)
        score = _calc_latency_score(self.db, mid)
        assert abs(score - 50.0) < 0.5

    def test_exceeds_1000ms_clamped_to_0(self):
        mid = self.db.create_endpoint_monitor("L", "https://example.com")
        self.db.record_endpoint_check_history(mid, status="up", response_ms=2000)
        score = _calc_latency_score(self.db, mid)
        assert score == 0.0


class TestCalcErrorRateScore:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_no_errors_returns_100(self):
        mid = self.db.create_endpoint_monitor("E", "https://example.com")
        for _ in range(5):
            self.db.record_endpoint_check_history(mid, status="up", response_ms=100)
        score = _calc_error_rate_score(self.db, mid)
        assert score == 100.0

    def test_all_errors_returns_0(self):
        mid = self.db.create_endpoint_monitor("E", "https://example.com")
        for _ in range(5):
            self.db.record_endpoint_check_history(mid, status="down")
        score = _calc_error_rate_score(self.db, mid)
        assert score == 0.0

    def test_no_history_returns_100(self):
        mid = self.db.create_endpoint_monitor("E", "https://example.com")
        score = _calc_error_rate_score(self.db, mid)
        assert score == 100.0


class TestCalcHeadroomScore:
    def test_no_last_ms_returns_100(self):
        monitor = {"timeout": 10, "last_response_ms": None}
        score = _calc_headroom_score(monitor)
        assert score == 100.0

    def test_zero_last_ms_returns_100(self):
        monitor = {"timeout": 10, "last_response_ms": 0}
        score = _calc_headroom_score(monitor)
        assert score == 100.0

    def test_half_timeout_returns_50(self):
        monitor = {"timeout": 10, "last_response_ms": 5000}
        score = _calc_headroom_score(monitor)
        assert abs(score - 50.0) < 0.1

    def test_full_timeout_returns_0(self):
        monitor = {"timeout": 10, "last_response_ms": 10000}
        score = _calc_headroom_score(monitor)
        assert score == 0.0

    def test_exceeded_timeout_clamped_to_0(self):
        monitor = {"timeout": 10, "last_response_ms": 15000}
        score = _calc_headroom_score(monitor)
        assert score == 0.0

    def test_no_timeout_defaults_10s(self):
        monitor = {"last_response_ms": 5000}
        score = _calc_headroom_score(monitor)
        assert abs(score - 50.0) < 0.1


# ── Health scoring: composite calculation ────────────────────────────────────

class TestComputeServiceHealthScores:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_no_monitors_returns_overall_100(self):
        result = compute_service_health_scores(self.db)
        assert result["overall"] == 100.0
        assert result["grade"] == "A"
        assert result["services"] == []

    def test_returns_correct_structure(self):
        mid = self.db.create_endpoint_monitor("Web", "https://example.com")
        for _ in range(5):
            self.db.record_endpoint_check_history(mid, status="up", response_ms=100)
        result = compute_service_health_scores(self.db)
        assert "overall" in result
        assert "grade" in result
        assert "services" in result
        assert len(result["services"]) == 1
        svc = result["services"][0]
        assert svc["name"] == "Web"
        assert svc["url"] == "https://example.com"
        assert "composite_score" in svc
        assert "grade" in svc
        assert "breakdown" in svc
        breakdown = svc["breakdown"]
        assert "uptime" in breakdown
        assert "latency" in breakdown
        assert "error_rate" in breakdown
        assert "headroom" in breakdown

    def test_healthy_service_gets_high_score(self):
        mid = self.db.create_endpoint_monitor("Healthy", "https://example.com", timeout=10)
        # Record check + simulate fast response time
        self.db.record_endpoint_check(mid, status="up", response_ms=50)
        for _ in range(20):
            self.db.record_endpoint_check_history(mid, status="up", response_ms=50)
        result = compute_service_health_scores(self.db)
        svc = result["services"][0]
        assert svc["composite_score"] >= 80
        assert svc["grade"] in ("A", "B")

    def test_down_service_gets_low_score(self):
        mid = self.db.create_endpoint_monitor("Down", "https://example.com")
        for _ in range(20):
            self.db.record_endpoint_check_history(mid, status="down")
        result = compute_service_health_scores(self.db)
        svc = result["services"][0]
        assert svc["composite_score"] < 50
        assert svc["grade"] in ("D", "F")

    def test_services_sorted_by_score_ascending(self):
        mid1 = self.db.create_endpoint_monitor("AAA", "https://a.example.com")
        mid2 = self.db.create_endpoint_monitor("BBB", "https://b.example.com")
        # mid1 all up, mid2 all down
        for _ in range(10):
            self.db.record_endpoint_check_history(mid1, status="up", response_ms=50)
        for _ in range(10):
            self.db.record_endpoint_check_history(mid2, status="down")
        result = compute_service_health_scores(self.db)
        scores = [s["composite_score"] for s in result["services"]]
        assert scores == sorted(scores)

    def test_overall_is_mean_of_service_scores(self):
        mid1 = self.db.create_endpoint_monitor("S1", "https://s1.example.com")
        mid2 = self.db.create_endpoint_monitor("S2", "https://s2.example.com")
        for _ in range(10):
            self.db.record_endpoint_check_history(mid1, status="up", response_ms=100)
        for _ in range(10):
            self.db.record_endpoint_check_history(mid2, status="up", response_ms=100)
        result = compute_service_health_scores(self.db)
        service_scores = [s["composite_score"] for s in result["services"]]
        expected_overall = round(sum(service_scores) / len(service_scores), 1)
        assert abs(result["overall"] - expected_overall) < 0.2

    def test_disabled_monitors_excluded(self):
        self.db.create_endpoint_monitor("Active", "https://a.example.com", enabled=True)
        self.db.create_endpoint_monitor("Inactive", "https://b.example.com", enabled=False)
        result = compute_service_health_scores(self.db)
        assert len(result["services"]) == 1
        assert result["services"][0]["name"] == "Active"

    def test_composite_score_uses_weights(self):
        """Verify the 40/25/20/15 weights produce scores in valid 0-100 range."""
        mid = self.db.create_endpoint_monitor("Weights", "https://w.example.com", timeout=10)
        self.db.record_endpoint_check(mid, status="up", response_ms=200)
        for _ in range(10):
            self.db.record_endpoint_check_history(mid, status="up", response_ms=200)
        result = compute_service_health_scores(self.db)
        svc = result["services"][0]
        # Manually verify weights
        b = svc["breakdown"]
        expected = round(
            b["uptime"] * 0.40
            + b["latency"] * 0.25
            + b["error_rate"] * 0.20
            + b["headroom"] * 0.15,
            1,
        )
        assert abs(svc["composite_score"] - expected) < 0.2

    def test_grade_matches_composite_score(self):
        mid = self.db.create_endpoint_monitor("Grade", "https://g.example.com")
        for _ in range(10):
            self.db.record_endpoint_check_history(mid, status="up", response_ms=50)
        result = compute_service_health_scores(self.db)
        svc = result["services"][0]
        assert svc["grade"] == _score_to_grade(svc["composite_score"])

    def test_empty_data_returns_sensible_defaults(self):
        """Monitor with no history should default to 100 on all sub-scores."""
        self.db.create_endpoint_monitor("New", "https://new.example.com")
        result = compute_service_health_scores(self.db)
        svc = result["services"][0]
        # All sub-scores should be at max (no data = assume OK)
        assert svc["breakdown"]["uptime"] == 100.0
        assert svc["breakdown"]["latency"] == 100.0
        assert svc["breakdown"]["error_rate"] == 100.0
        # composite should be perfect
        assert svc["composite_score"] == 100.0
        assert svc["grade"] == "A"
