# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the security posture scoring feature."""
from __future__ import annotations

import os
import sys
import tempfile

# Ensure the agent module is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "share", "noba-agent"))

from server.db import Database


def _make_db():
    """Create a fresh temp DB for each test."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_test_sec_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


# ── Database layer tests ─────────────────────────────────────────────────────

class TestRecordScan:
    def test_record_and_retrieve_score(self):
        db, path = _make_db()
        try:
            findings = [
                {
                    "severity": "high",
                    "category": "ssh",
                    "description": "PermitRootLogin enabled",
                    "remediation": "Disable root login",
                },
                {
                    "severity": "medium",
                    "category": "firewall",
                    "description": "No firewall active",
                    "remediation": "Enable ufw",
                },
            ]
            sid = db.record_security_scan("host-a", 60, findings)
            assert sid is not None

            scores = db.get_security_scores()
            assert len(scores) == 1
            assert scores[0]["hostname"] == "host-a"
            assert scores[0]["score"] == 60
            assert len(scores[0]["findings"]) == 2
        finally:
            _cleanup(path)

    def test_record_multiple_hosts(self):
        db, path = _make_db()
        try:
            db.record_security_scan("host-a", 80, [])
            db.record_security_scan("host-b", 60, [{"severity": "high", "category": "ssh",
                                                      "description": "test", "remediation": "fix"}])
            scores = db.get_security_scores()
            assert len(scores) == 2
            hosts = {s["hostname"] for s in scores}
            assert hosts == {"host-a", "host-b"}
        finally:
            _cleanup(path)

    def test_latest_score_per_host(self):
        db, path = _make_db()
        try:
            db.record_security_scan("host-a", 50, [])
            db.record_security_scan("host-a", 75, [])
            scores = db.get_security_scores()
            assert len(scores) == 1
            assert scores[0]["score"] == 75
        finally:
            _cleanup(path)


class TestGetFindings:
    def test_findings_stored_correctly(self):
        db, path = _make_db()
        try:
            findings = [
                {"severity": "high", "category": "ssh",
                 "description": "Root login enabled", "remediation": "Disable it"},
                {"severity": "low", "category": "updates",
                 "description": "Auto-updates off", "remediation": "Enable them"},
            ]
            db.record_security_scan("host-a", 70, findings)
            result = db.get_security_findings()
            assert len(result) == 2
            assert result[0]["hostname"] == "host-a"
            assert result[0]["category"] in ("ssh", "updates")
        finally:
            _cleanup(path)

    def test_filter_by_severity(self):
        db, path = _make_db()
        try:
            findings = [
                {"severity": "high", "category": "ssh",
                 "description": "test high", "remediation": "fix"},
                {"severity": "low", "category": "updates",
                 "description": "test low", "remediation": "fix"},
            ]
            db.record_security_scan("host-a", 70, findings)
            high = db.get_security_findings(severity="high")
            assert len(high) == 1
            assert high[0]["severity"] == "high"
        finally:
            _cleanup(path)

    def test_filter_by_hostname(self):
        db, path = _make_db()
        try:
            db.record_security_scan("host-a", 80,
                                    [{"severity": "low", "category": "ssh",
                                      "description": "a finding", "remediation": "fix"}])
            db.record_security_scan("host-b", 60,
                                    [{"severity": "high", "category": "firewall",
                                      "description": "b finding", "remediation": "fix"}])
            a_only = db.get_security_findings(hostname="host-a")
            assert len(a_only) == 1
            assert a_only[0]["hostname"] == "host-a"
        finally:
            _cleanup(path)


class TestAggregateScore:
    def test_aggregate_average(self):
        db, path = _make_db()
        try:
            db.record_security_scan("host-a", 80, [])
            db.record_security_scan("host-b", 60, [])
            agg = db.get_aggregate_security_score()
            assert agg["score"] == 70
            assert agg["agent_count"] == 2
        finally:
            _cleanup(path)

    def test_aggregate_empty(self):
        db, path = _make_db()
        try:
            agg = db.get_aggregate_security_score()
            assert agg["score"] is None
            assert agg["agent_count"] == 0
        finally:
            _cleanup(path)

    def test_aggregate_single(self):
        db, path = _make_db()
        try:
            db.record_security_scan("host-a", 90, [])
            agg = db.get_aggregate_security_score()
            assert agg["score"] == 90
            assert agg["agent_count"] == 1
        finally:
            _cleanup(path)


class TestScoreHistory:
    def test_history_returned(self):
        db, path = _make_db()
        try:
            db.record_security_scan("host-a", 50, [])
            db.record_security_scan("host-a", 75, [])
            db.record_security_scan("host-b", 60, [])
            history = db.get_security_score_history()
            assert len(history) == 3
        finally:
            _cleanup(path)

    def test_history_filtered_by_host(self):
        db, path = _make_db()
        try:
            db.record_security_scan("host-a", 50, [])
            db.record_security_scan("host-b", 60, [])
            history = db.get_security_score_history(hostname="host-a")
            assert len(history) == 1
            assert history[0]["hostname"] == "host-a"
        finally:
            _cleanup(path)


# ── Scoring algorithm tests (agent side) ─────────────────────────────────────

class TestScoreCalculation:
    def test_perfect_score(self):
        from commands import _calculate_security_score
        assert _calculate_security_score([]) == 100

    def test_single_high_finding(self):
        from commands import _calculate_security_score
        findings = [{"severity": "high", "category": "ssh", "description": "x"}]
        score = _calculate_security_score(findings)
        assert score == 80  # 100 - 20

    def test_mixed_findings(self):
        from commands import _calculate_security_score
        findings = [
            {"severity": "high", "category": "ssh", "description": "x"},
            {"severity": "medium", "category": "firewall", "description": "x"},
            {"severity": "low", "category": "updates", "description": "x"},
        ]
        score = _calculate_security_score(findings)
        # 100 - 20 - 10 - 5 = 65
        assert score == 65

    def test_cap_high_deductions(self):
        from commands import _calculate_security_score
        # 4 high findings = 80 but capped at 60
        findings = [{"severity": "high", "category": f"cat{i}", "description": "x"} for i in range(4)]
        score = _calculate_security_score(findings)
        assert score == 40  # 100 - 60 (capped)

    def test_cap_medium_deductions(self):
        from commands import _calculate_security_score
        # 5 medium findings = 50 but capped at 30
        findings = [{"severity": "medium", "category": f"cat{i}", "description": "x"} for i in range(5)]
        score = _calculate_security_score(findings)
        assert score == 70  # 100 - 30 (capped)

    def test_floor_at_zero(self):
        from commands import _calculate_security_score
        # 3 high + 3 medium + 3 low = min(60,60) + min(30,30) + min(15,15) = 105 -> capped to 0
        findings = (
            [{"severity": "high", "category": f"h{i}", "description": "x"} for i in range(3)]
            + [{"severity": "medium", "category": f"m{i}", "description": "x"} for i in range(3)]
            + [{"severity": "low", "category": f"l{i}", "description": "x"} for i in range(3)]
        )
        score = _calculate_security_score(findings)
        assert score == 0  # 100 - 60 - 30 - 15 = -5 -> 0
