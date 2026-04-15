# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for health score integration with healing pipeline."""
from __future__ import annotations


class TestHealthScoreThresholds:
    def test_low_capacity_generates_suggestion(self):
        from server.healing.health_triggers import evaluate_health_thresholds
        categories = {
            "capacity": {"score": 3, "max": 10, "details": "disk at 92%"},
            "monitoring": {"score": 8, "max": 10},
            "certificates": {"score": 9, "max": 10},
            "updates": {"score": 7, "max": 10},
            "uptime": {"score": 9, "max": 10},
            "backup": {"score": 8, "max": 10},
        }
        suggestions, events = evaluate_health_thresholds(categories)
        assert len(suggestions) >= 1
        assert any("capacity" in s["message"].lower() for s in suggestions)

    def test_low_cert_health_generates_suggestion(self):
        from server.healing.health_triggers import evaluate_health_thresholds
        categories = {
            "capacity": {"score": 8, "max": 10},
            "monitoring": {"score": 8, "max": 10},
            "certificates": {"score": 3, "max": 10, "details": "cert expiring in 5 days"},
            "updates": {"score": 7, "max": 10},
            "uptime": {"score": 9, "max": 10},
            "backup": {"score": 8, "max": 10},
        }
        suggestions, events = evaluate_health_thresholds(categories)
        assert any("cert" in s["message"].lower() for s in suggestions)

    def test_low_backup_generates_suggestion(self):
        from server.healing.health_triggers import evaluate_health_thresholds
        categories = {
            "capacity": {"score": 8, "max": 10},
            "monitoring": {"score": 8, "max": 10},
            "certificates": {"score": 9, "max": 10},
            "updates": {"score": 7, "max": 10},
            "uptime": {"score": 9, "max": 10},
            "backup": {"score": 2, "max": 10, "details": "no backup in 72h"},
        }
        suggestions, events = evaluate_health_thresholds(categories)
        assert any("backup" in s["message"].lower() for s in suggestions)

    def test_all_healthy_no_suggestions(self):
        from server.healing.health_triggers import evaluate_health_thresholds
        categories = {
            "capacity": {"score": 8, "max": 10},
            "monitoring": {"score": 9, "max": 10},
            "certificates": {"score": 9, "max": 10},
            "updates": {"score": 7, "max": 10},
            "uptime": {"score": 9, "max": 10},
            "backup": {"score": 8, "max": 10},
        }
        suggestions, events = evaluate_health_thresholds(categories)
        assert len(suggestions) == 0

    def test_low_capacity_emits_heal_event(self):
        from server.healing.health_triggers import evaluate_health_thresholds
        categories = {
            "capacity": {"score": 2, "max": 10, "details": "disk at 95%"},
            "monitoring": {"score": 8, "max": 10},
            "certificates": {"score": 9, "max": 10},
            "updates": {"score": 7, "max": 10},
            "uptime": {"score": 9, "max": 10},
            "backup": {"score": 8, "max": 10},
        }
        suggestions, events = evaluate_health_thresholds(categories)
        # Very low capacity should also emit a heal event for cleanup
        assert len(events) >= 1
        assert events[0].source == "health_score"

    def test_thresholds_configurable(self):
        from server.healing.health_triggers import evaluate_health_thresholds
        categories = {
            "capacity": {"score": 5, "max": 10},
            "monitoring": {"score": 8, "max": 10},
            "certificates": {"score": 9, "max": 10},
            "updates": {"score": 7, "max": 10},
            "uptime": {"score": 9, "max": 10},
            "backup": {"score": 8, "max": 10},
        }
        # Default threshold for capacity is 4, score=5 should NOT trigger
        suggestions, events = evaluate_health_thresholds(categories)
        assert len(suggestions) == 0
        # But with custom threshold of 6, score=5 SHOULD trigger
        suggestions, events = evaluate_health_thresholds(
            categories, thresholds={"capacity": 6},
        )
        assert len(suggestions) >= 1
