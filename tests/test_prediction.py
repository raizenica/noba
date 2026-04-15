# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the multi-metric prediction engine (prediction.py)."""
from __future__ import annotations

import math
import time
from unittest.mock import patch


from server.prediction import (
    _linear_regression,
    _detect_seasonality,
    _residual_std,
    _project_with_confidence,
    _combine_predictions,
    predict_capacity,
)


# ---------------------------------------------------------------------------
# _linear_regression
# ---------------------------------------------------------------------------

class TestLinearRegression:
    def test_perfect_fit_known_slope(self):
        """y = 2x + 5 should give slope=2, intercept=5, r_squared=1."""
        xs = list(range(10))
        ys = [2 * x + 5 for x in xs]
        result = _linear_regression(xs, ys)
        assert abs(result["slope"] - 2.0) < 1e-6
        assert abs(result["intercept"] - 5.0) < 1e-2
        assert abs(result["r_squared"] - 1.0) < 1e-6

    def test_flat_data_slope_zero(self):
        """Constant y should yield slope=0 and r_squared=0."""
        xs = list(range(10))
        ys = [42.0] * 10
        result = _linear_regression(xs, ys)
        assert result["slope"] == 0
        assert result["r_squared"] == 0

    def test_negative_slope(self):
        """y = -3x + 100 should give slope≈-3."""
        xs = [float(i) for i in range(20)]
        ys = [-3 * x + 100 for x in xs]
        result = _linear_regression(xs, ys)
        assert abs(result["slope"] - (-3.0)) < 1e-5
        assert abs(result["r_squared"] - 1.0) < 1e-6

    def test_insufficient_data_single_point(self):
        """Single point must not crash and should return slope=0."""
        result = _linear_regression([5.0], [10.0])
        assert result["slope"] == 0
        assert result["r_squared"] == 0

    def test_two_points(self):
        """Two points on y=x should give slope=1, r_squared=1."""
        result = _linear_regression([0.0, 1.0], [0.0, 1.0])
        assert abs(result["slope"] - 1.0) < 1e-9
        assert abs(result["r_squared"] - 1.0) < 1e-9

    def test_noisy_data_r_squared_between_zero_and_one(self):
        """Noisy data should have 0 < r_squared < 1."""
        xs = [float(i) for i in range(50)]
        # Trend + noise
        ys = [x + ((-1) ** i) * 5 for i, x in enumerate(xs)]
        result = _linear_regression(xs, ys)
        assert 0 < result["r_squared"] < 1


# ---------------------------------------------------------------------------
# _detect_seasonality
# ---------------------------------------------------------------------------

class TestDetectSeasonality:
    def _make_sinusoidal_24h(self, n_points: int = 1440, step: int = 300):
        """Generate n_points of a 24-h sinusoidal signal at 5-min steps.

        1440 points = 5 full 24-hour cycles at 5-min resolution, giving
        enough pairs (1152) for the autocorrelation denominator to be
        well-estimated (corr ≈ 0.8, well above the 0.3 threshold).
        """
        period_s = 24 * 3600
        t0 = 1_700_000_000
        xs = [t0 + i * step for i in range(n_points)]
        # Amplitude 10, mean 50
        ys = [50 + 10 * math.sin(2 * math.pi * (t - t0) / period_s) for t in xs]
        return xs, ys

    def test_detects_24h_pattern(self):
        """Strong 24-h sinusoidal signal should be detected."""
        xs, ys = self._make_sinusoidal_24h(n_points=1440)
        result = _detect_seasonality(xs, ys)
        assert result is not None
        assert result["period_hours"] == 24
        assert result["correlation"] > 0.3
        assert result["amplitude"] > 0

    def test_flat_data_returns_none(self):
        """Flat data has no seasonality."""
        xs = list(range(200))
        ys = [5.0] * 200
        result = _detect_seasonality(xs, ys)
        assert result is None

    def test_too_few_points_returns_none(self):
        """Fewer than 48 points should always return None."""
        xs = list(range(30))
        ys = [float(i % 10) for i in range(30)]
        result = _detect_seasonality(xs, ys)
        assert result is None

    def test_random_noise_unlikely_to_trigger(self):
        """Low-variance noise (var < 0.01) should return None."""
        import random
        random.seed(42)
        xs = list(range(200))
        ys = [1.0 + random.uniform(-0.001, 0.001) for _ in range(200)]
        result = _detect_seasonality(xs, ys)
        assert result is None

    def test_returns_none_when_lag_too_large(self):
        """If only 50 points at 5-min steps, a 168h lag won't fit — no weekly pattern."""
        t0 = 1_700_000_000
        step = 300
        xs = [t0 + i * step for i in range(50)]
        # Purely daily signal but insufficient length for weekly
        period_s = 24 * 3600
        ys = [50 + 10 * math.sin(2 * math.pi * (t - t0) / period_s) for t in xs]
        result = _detect_seasonality(xs, ys)
        # May detect daily or None; must not raise
        assert result is None or result["period_hours"] == 24


# ---------------------------------------------------------------------------
# _residual_std
# ---------------------------------------------------------------------------

class TestResidualStd:
    def test_perfect_fit_zero_residuals(self):
        """Perfect linear fit should yield residual_std ≈ 0."""
        xs = [float(i) for i in range(20)]
        ys = [3 * x + 7 for x in xs]
        std = _residual_std(xs, ys, slope=3.0, intercept=7.0)
        assert std < 1e-9

    def test_known_residuals(self):
        """Residuals [1,-1,1,-1,0] around y=0 have sample stdev exactly 1.0.

        statistics.stdev uses the sample formula (divides by n-1).
        With residuals [1,-1,1,-1,0]: mean=0, sum_sq=4, n=5,
        sample_var = 4/4 = 1.0, so stdev = 1.0.
        """
        xs = [0.0, 1.0, 2.0, 3.0, 4.0]
        # Line: y = 0; residuals are the ys themselves
        ys = [1.0, -1.0, 1.0, -1.0, 0.0]
        std = _residual_std(xs, ys, slope=0.0, intercept=0.0)
        assert abs(std - 1.0) < 1e-9

    def test_single_point_returns_zero(self):
        """Cannot compute std with a single residual."""
        std = _residual_std([1.0], [2.0], slope=1.0, intercept=0.0)
        assert std == 0.0


# ---------------------------------------------------------------------------
# _project_with_confidence
# ---------------------------------------------------------------------------

class TestProjectWithConfidence:
    def _make_regression(self, slope=0.0, intercept=50.0, r_squared=0.9):
        return {"slope": slope, "intercept": intercept, "r_squared": r_squared}

    def _make_xs(self, n=100, step=300):
        t0 = 1_700_000_000
        return [t0 + i * step for i in range(n)]

    def test_intervals_widen_over_time(self):
        """The 68% band should grow wider the further out we project."""
        xs = self._make_xs(100)
        reg = self._make_regression()
        pts = _project_with_confidence(xs, reg, None, residual_std=2.0, projection_hours=10)
        widths = [p["upper_68"] - p["lower_68"] for p in pts]
        # Widths should be non-decreasing over the projection horizon
        assert all(widths[i] <= widths[i + 1] + 1e-6 for i in range(len(widths) - 1))

    def test_95_wider_than_68(self):
        """95% interval must always be wider than the 68% interval."""
        xs = self._make_xs(100)
        reg = self._make_regression()
        pts = _project_with_confidence(xs, reg, None, residual_std=3.0, projection_hours=10)
        for p in pts:
            width_68 = p["upper_68"] - p["lower_68"]
            width_95 = p["upper_95"] - p["lower_95"]
            assert width_95 > width_68

    def test_seasonal_adds_oscillation(self):
        """With seasonal component, predicted values should oscillate."""
        xs = self._make_xs(300)
        reg = self._make_regression(slope=0.0, intercept=50.0)
        seasonal = {"period_hours": 24, "correlation": 0.8, "amplitude": 5.0}
        pts = _project_with_confidence(xs, reg, seasonal, residual_std=1.0, projection_hours=48)
        preds = [p["predicted"] for p in pts]
        # With flat trend + seasonal, values should differ (oscillate around 50)
        assert max(preds) - min(preds) > 1.0

    def test_no_seasonal_flat_trend(self):
        """Flat trend, no seasonal: all predicted values should equal the intercept."""
        xs = self._make_xs(50)
        reg = self._make_regression(slope=0.0, intercept=42.0)
        pts = _project_with_confidence(xs, reg, None, residual_std=0.0, projection_hours=5)
        for p in pts:
            assert abs(p["predicted"] - 42.0) < 1e-6

    def test_output_contains_expected_keys(self):
        """Each point must have the required keys."""
        xs = self._make_xs(50)
        reg = self._make_regression()
        pts = _project_with_confidence(xs, reg, None, residual_std=1.0, projection_hours=3)
        required = {"time", "predicted", "lower_68", "upper_68", "lower_95", "upper_95"}
        for p in pts:
            assert required.issubset(p.keys())

    def test_n_points_equals_projection_hours(self):
        """Number of output points equals projection_hours (one per hour)."""
        xs = self._make_xs(50)
        reg = self._make_regression()
        pts = _project_with_confidence(xs, reg, None, residual_std=1.0, projection_hours=24)
        assert len(pts) == 24


# ---------------------------------------------------------------------------
# _combine_predictions
# ---------------------------------------------------------------------------

class TestCombinePredictions:
    def _make_result(self, slope, intercept, r_squared):
        return {
            "regression": {"slope": slope, "intercept": intercept, "r_squared": r_squared},
            "seasonal": None,
            "projection": [],
            "residual_std": 1.0,
        }

    def test_picks_highest_r_squared(self):
        """The metric with the highest R² should become the primary_metric."""
        results = {
            "cpu_percent": self._make_result(0.001, 20.0, 0.95),
            "mem_percent": self._make_result(0.0005, 30.0, 0.60),
        }
        combined = _combine_predictions(results, projection_hours=720)
        assert combined["primary_metric"] == "cpu_percent"
        assert abs(combined["r_squared"] - 0.95) < 1e-6

    def test_all_errors_returns_low_confidence(self):
        """When all metrics have errors, combined should return confidence='low'."""
        results = {
            "disk_percent": {"error": "Insufficient data"},
        }
        combined = _combine_predictions(results, projection_hours=720)
        assert combined["primary_metric"] is None
        assert combined["confidence"] == "low"
        assert combined["full_at"] is None

    def test_high_r_squared_gives_high_confidence(self):
        results = {"disk": self._make_result(0.001, 10.0, 0.85)}
        combined = _combine_predictions(results, projection_hours=720)
        assert combined["confidence"] == "high"

    def test_medium_r_squared_gives_medium_confidence(self):
        results = {"disk": self._make_result(0.001, 10.0, 0.65)}
        combined = _combine_predictions(results, projection_hours=720)
        assert combined["confidence"] == "medium"

    def test_low_r_squared_gives_low_confidence(self):
        results = {"disk": self._make_result(0.001, 10.0, 0.30)}
        combined = _combine_predictions(results, projection_hours=720)
        assert combined["confidence"] == "low"

    def test_zero_slope_no_full_at(self):
        """Non-positive slope should not produce a full_at date."""
        results = {"disk": self._make_result(0.0, 50.0, 0.90)}
        combined = _combine_predictions(results, projection_hours=720)
        assert combined["full_at"] is None

    def test_positive_slope_may_produce_full_at(self):
        """A large enough positive slope should yield a future full_at ISO string."""
        # slope such that 100% is reached ~1 year out
        now = time.time()
        t_full = now + 365 * 86400
        # slope = (100 - intercept) / t_full => intercept=0
        slope = 100 / t_full
        results = {"disk": self._make_result(slope, 0.0, 0.92)}
        combined = _combine_predictions(results, projection_hours=720)
        assert combined["full_at"] is not None
        assert "T" in combined["full_at"]  # ISO 8601 contains T

    def test_slope_per_day_calculation(self):
        """slope_per_day should be slope * 86400."""
        slope = 1e-4
        results = {"disk": self._make_result(slope, 10.0, 0.75)}
        combined = _combine_predictions(results, projection_hours=720)
        expected = round(slope * 86400, 4)
        assert abs(combined["slope_per_day"] - expected) < 1e-6


# ---------------------------------------------------------------------------
# predict_capacity (integration test with mocked db)
# ---------------------------------------------------------------------------

class TestPredictCapacity:
    def _make_points(self, n=150, slope=0.0, intercept=50.0, step=300):
        """Generate synthetic history points."""
        t0 = int(time.time()) - n * step
        return [
            {"time": t0 + i * step, "value": round(slope * (t0 + i * step) + intercept, 2)}
            for i in range(n)
        ]

    def test_single_metric_sufficient_data(self):
        """With enough data, predict_capacity should return regression + projection."""
        points = self._make_points(n=150, slope=1e-5, intercept=30.0)
        with patch("server.prediction.db") as mock_db:
            mock_db.get_history.return_value = points
            result = predict_capacity(["disk_percent"], range_hours=168, projection_hours=24)

        assert "metrics" in result
        assert "combined" in result
        assert "disk_percent" in result["metrics"]
        metric = result["metrics"]["disk_percent"]
        assert "error" not in metric
        assert "regression" in metric
        assert "projection" in metric
        assert len(metric["projection"]) == 24
        assert metric["regression"]["r_squared"] >= 0

    def test_insufficient_data_produces_error_key(self):
        """Fewer than 10 points should yield an error entry for that metric."""
        points = self._make_points(n=5)
        with patch("server.prediction.db") as mock_db:
            mock_db.get_history.return_value = points
            result = predict_capacity(["cpu_percent"])

        assert "error" in result["metrics"]["cpu_percent"]
        assert result["combined"]["primary_metric"] is None

    def test_multi_metric_picks_best_r_squared(self):
        """With two metrics, combined.primary_metric should be the better one."""
        # Good data: perfect line
        good_points = self._make_points(n=150, slope=1e-5, intercept=20.0)
        # Bad data: fewer points => error
        bad_points = self._make_points(n=5)

        def fake_get_history(metric, **kwargs):
            if metric == "disk_percent":
                return good_points
            return bad_points

        with patch("server.prediction.db") as mock_db:
            mock_db.get_history.side_effect = fake_get_history
            result = predict_capacity(["disk_percent", "inode_percent"])

        assert result["combined"]["primary_metric"] == "disk_percent"

    def test_empty_metric_list_returns_empty_metrics(self):
        """Empty metric_keys should return empty metrics dict."""
        with patch("server.prediction.db"):
            result = predict_capacity([])
        assert result["metrics"] == {}
        assert result["combined"]["primary_metric"] is None

    def test_projection_confidence_intervals_present(self):
        """Each projection point must have all five required keys."""
        points = self._make_points(n=150, slope=5e-6, intercept=40.0)
        with patch("server.prediction.db") as mock_db:
            mock_db.get_history.return_value = points
            result = predict_capacity(["mem_percent"], projection_hours=10)

        proj = result["metrics"]["mem_percent"]["projection"]
        assert len(proj) == 10
        required = {"time", "predicted", "lower_68", "upper_68", "lower_95", "upper_95"}
        for pt in proj:
            assert required.issubset(pt.keys())
