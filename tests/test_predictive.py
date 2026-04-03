# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing.predictive: prediction and anomaly evaluation."""
from __future__ import annotations

import time
from unittest.mock import patch


class TestPredictionEvaluator:
    def test_emits_event_when_threshold_approaching(self):
        from server.healing.predictive import evaluate_predictions
        # Mock prediction returning full_at in 20 hours (within 24h warning window)
        future = time.time() + (20 * 3600)  # 20 hours from now
        from datetime import datetime, timezone
        full_at_iso = datetime.fromtimestamp(future, tz=timezone.utc).isoformat()

        mock_result = {
            "metrics": {"disk_percent": {"projection": []}},
            "combined": {
                "full_at": full_at_iso,
                "primary_metric": "disk_percent",
                "confidence": "high",
                "slope_per_day": 3.5,
            },
        }
        with patch("server.healing.predictive._run_prediction", return_value=mock_result):
            events = evaluate_predictions(metric_groups={"disk": ["disk_percent"]})
            assert len(events) >= 1
            assert events[0].source == "prediction"
            assert events[0].severity == "warning"  # 24h window = warning

    def test_no_event_when_far_from_threshold(self):
        from server.healing.predictive import evaluate_predictions
        future = time.time() + (500 * 3600)  # 500 hours away
        from datetime import datetime, timezone
        full_at_iso = datetime.fromtimestamp(future, tz=timezone.utc).isoformat()

        mock_result = {
            "metrics": {"disk_percent": {"projection": []}},
            "combined": {
                "full_at": full_at_iso,
                "primary_metric": "disk_percent",
                "confidence": "medium",
                "slope_per_day": 0.5,
            },
        }
        with patch("server.healing.predictive._run_prediction", return_value=mock_result):
            events = evaluate_predictions(metric_groups={"disk": ["disk_percent"]})
            assert len(events) == 0  # too far away

    def test_no_event_when_no_full_at(self):
        from server.healing.predictive import evaluate_predictions
        mock_result = {
            "metrics": {"cpu_percent": {"projection": []}},
            "combined": {
                "full_at": None,
                "primary_metric": "cpu_percent",
                "confidence": "low",
                "slope_per_day": 0.1,
            },
        }
        with patch("server.healing.predictive._run_prediction", return_value=mock_result):
            events = evaluate_predictions(metric_groups={"cpu": ["cpu_percent"]})
            assert len(events) == 0

    def test_72h_horizon_gets_info_severity(self):
        from server.healing.predictive import evaluate_predictions
        future = time.time() + (50 * 3600)  # 50 hours = within 72h window
        from datetime import datetime, timezone
        full_at_iso = datetime.fromtimestamp(future, tz=timezone.utc).isoformat()

        mock_result = {
            "metrics": {"mem_percent": {"projection": []}},
            "combined": {
                "full_at": full_at_iso,
                "primary_metric": "mem_percent",
                "confidence": "high",
                "slope_per_day": 2.0,
            },
        }
        with patch("server.healing.predictive._run_prediction", return_value=mock_result):
            events = evaluate_predictions(metric_groups={"memory": ["mem_percent"]})
            assert len(events) >= 1
            assert events[0].severity == "info"  # 72h window = info


class TestAnomalyEvaluation:
    def test_emits_event_for_anomaly(self):
        from server.healing.predictive import evaluate_anomalies
        anomalies = [{"level": "warning", "msg": "Anomaly: CPU 98% (above normal 40-75%)"}]
        with patch("server.healing.predictive._check_anomalies", return_value=anomalies):
            events = evaluate_anomalies()
            assert len(events) >= 1
            assert events[0].source == "anomaly"

    def test_no_event_when_no_anomalies(self):
        from server.healing.predictive import evaluate_anomalies
        with patch("server.healing.predictive._check_anomalies", return_value=[]):
            events = evaluate_anomalies()
            assert len(events) == 0


class TestStaleDataGuard:
    def test_stale_data_blocks_evaluation(self):
        from server.healing.predictive import is_data_stale
        # Last collect was 5 minutes ago, interval is 5s — very stale
        assert is_data_stale(last_collect_time=time.time() - 300, collect_interval=5)

    def test_fresh_data_passes(self):
        from server.healing.predictive import is_data_stale
        assert not is_data_stale(last_collect_time=time.time() - 3, collect_interval=5)

    def test_stale_threshold_is_2x_interval(self):
        from server.healing.predictive import is_data_stale
        # Exactly at 2x boundary — should be stale
        assert is_data_stale(last_collect_time=time.time() - 10.1, collect_interval=5)
        # Just under 2x — not stale
        assert not is_data_stale(last_collect_time=time.time() - 9.9, collect_interval=5)


class TestPredictiveRunner:
    def test_run_cycle_returns_events(self):
        from server.healing.predictive import run_predictive_cycle
        with patch("server.healing.predictive.is_data_stale", return_value=False), \
             patch("server.healing.predictive.evaluate_predictions", return_value=[]), \
             patch("server.healing.predictive.evaluate_anomalies", return_value=[]):
            events = run_predictive_cycle()
            assert isinstance(events, list)

    def test_run_cycle_skips_when_stale(self):
        from server.healing.predictive import run_predictive_cycle
        with patch("server.healing.predictive.is_data_stale", return_value=True):
            events = run_predictive_cycle()
            assert len(events) == 0  # stale data = no events
