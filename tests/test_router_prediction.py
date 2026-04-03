# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Integration tests for prediction API endpoints.

Covers:
  GET /api/predict/capacity   (intelligence router)
  GET /api/disks/prediction   (infrastructure router)
"""
from __future__ import annotations

from unittest.mock import patch

# ---------------------------------------------------------------------------
# Shared mock payload — matches predict_capacity() return shape
# ---------------------------------------------------------------------------

_MOCK_RESULT = {
    "metrics": {
        "disk_percent": {
            "regression": {"slope": 0.0001, "intercept": 40.0, "r_squared": 0.85},
            "seasonal": None,
            "projection": [
                {"time": 1700000000, "predicted": 42.0,
                 "lower_68": 41.0, "upper_68": 43.0,
                 "lower_95": 40.0, "upper_95": 44.0}
            ],
            "residual_std": 0.5,
        }
    },
    "combined": {
        "full_at": "2026-12-01T00:00:00+00:00",
        "primary_metric": "disk_percent",
        "r_squared": 0.85,
        "confidence": "high",
        "slope_per_day": 8.64,
    },
}

_MOCK_MULTI = {
    "metrics": {
        "cpu_percent": {
            "regression": {"slope": 0.00005, "intercept": 30.0, "r_squared": 0.72},
            "seasonal": None,
            "projection": [],
            "residual_std": 1.2,
        },
        "mem_percent": {
            "regression": {"slope": 0.0002, "intercept": 55.0, "r_squared": 0.91},
            "seasonal": None,
            "projection": [],
            "residual_std": 0.8,
        },
    },
    "combined": {
        "full_at": "2026-09-15T00:00:00+00:00",
        "primary_metric": "mem_percent",
        "r_squared": 0.91,
        "confidence": "high",
        "slope_per_day": 17.28,
    },
}


# ===========================================================================
# GET /api/predict/capacity
# ===========================================================================

class TestPredictCapacity:
    """GET /api/predict/capacity — intelligence router."""

    # ── Auth ──────────────────────────────────────────────────────────────
    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/predict/capacity")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT):
            resp = client.get("/api/predict/capacity", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT):
            resp = client.get("/api/predict/capacity", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT):
            resp = client.get("/api/predict/capacity", headers=admin_headers)
        assert resp.status_code == 200

    # ── Response shape ────────────────────────────────────────────────────
    def test_returns_metrics_key(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT):
            resp = client.get("/api/predict/capacity", headers=admin_headers)
        assert "metrics" in resp.json()

    def test_returns_combined_key(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT):
            resp = client.get("/api/predict/capacity", headers=admin_headers)
        assert "combined" in resp.json()

    def test_combined_has_confidence(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT):
            resp = client.get("/api/predict/capacity", headers=admin_headers)
        assert resp.json()["combined"]["confidence"] == "high"

    def test_combined_has_primary_metric(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT):
            resp = client.get("/api/predict/capacity", headers=admin_headers)
        assert resp.json()["combined"]["primary_metric"] == "disk_percent"

    # ── Default metric ────────────────────────────────────────────────────
    def test_default_metric_is_disk_percent(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT) as mock_pc:
            client.get("/api/predict/capacity", headers=admin_headers)
        mock_pc.assert_called_once()
        call_args = mock_pc.call_args
        assert call_args[0][0] == ["disk_percent"]

    # ── Multi-metric ──────────────────────────────────────────────────────
    def test_multi_metric_param(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_MULTI) as mock_pc:
            resp = client.get(
                "/api/predict/capacity?metrics=cpu_percent,mem_percent",
                headers=admin_headers,
            )
        assert resp.status_code == 200
        mock_pc.assert_called_once()
        metrics_arg = mock_pc.call_args[0][0]
        assert "cpu_percent" in metrics_arg
        assert "mem_percent" in metrics_arg

    def test_multi_metric_response_has_both_keys(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_MULTI):
            resp = client.get(
                "/api/predict/capacity?metrics=cpu_percent,mem_percent",
                headers=admin_headers,
            )
        data = resp.json()
        assert "cpu_percent" in data["metrics"]
        assert "mem_percent" in data["metrics"]

    # ── Query param bounds ────────────────────────────────────────────────
    def test_range_capped_at_720(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT) as mock_pc:
            client.get(
                "/api/predict/capacity?range=9999",
                headers=admin_headers,
            )
        _, kwargs = mock_pc.call_args
        assert kwargs["range_hours"] <= 720

    def test_projection_capped_at_2160(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT) as mock_pc:
            client.get(
                "/api/predict/capacity?projection=99999",
                headers=admin_headers,
            )
        _, kwargs = mock_pc.call_args
        assert kwargs["projection_hours"] <= 2160

    def test_range_within_limit_passed_as_is(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT) as mock_pc:
            client.get(
                "/api/predict/capacity?range=48",
                headers=admin_headers,
            )
        _, kwargs = mock_pc.call_args
        assert kwargs["range_hours"] == 48

    def test_projection_within_limit_passed_as_is(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT) as mock_pc:
            client.get(
                "/api/predict/capacity?projection=360",
                headers=admin_headers,
            )
        _, kwargs = mock_pc.call_args
        assert kwargs["projection_hours"] == 360


# ===========================================================================
# GET /api/disks/prediction
# ===========================================================================

class TestDisksPrediction:
    """GET /api/disks/prediction — infrastructure router, normalized shape."""

    # ── Auth ──────────────────────────────────────────────────────────────
    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/disks/prediction")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT):
            resp = client.get("/api/disks/prediction", headers=viewer_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT):
            resp = client.get("/api/disks/prediction", headers=admin_headers)
        assert resp.status_code == 200

    # ── Response shape ────────────────────────────────────────────────────
    def test_returns_metrics_key(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT):
            resp = client.get("/api/disks/prediction", headers=admin_headers)
        assert "metrics" in resp.json()

    def test_returns_combined_key(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT):
            resp = client.get("/api/disks/prediction", headers=admin_headers)
        assert "combined" in resp.json()

    def test_metrics_contains_disk_percent(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT):
            resp = client.get("/api/disks/prediction", headers=admin_headers)
        assert "disk_percent" in resp.json()["metrics"]

    def test_combined_has_confidence(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT):
            resp = client.get("/api/disks/prediction", headers=admin_headers)
        assert "confidence" in resp.json()["combined"]

    def test_combined_has_full_at(self, client, admin_headers):
        with patch("server.prediction.predict_capacity", return_value=_MOCK_RESULT):
            resp = client.get("/api/disks/prediction", headers=admin_headers)
        assert "full_at" in resp.json()["combined"]

    # ── Fallback shape ────────────────────────────────────────────────────
    def test_fallback_on_predict_exception_returns_normalized_shape(
        self, client, admin_headers
    ):
        """When predict_capacity raises, the fallback must still return metrics+combined."""
        fake_trend = {
            "slope": 0.00005,
            "r_squared": 0.3,
            "projection": [],
            "full_at": None,
        }
        with patch("server.prediction.predict_capacity", side_effect=RuntimeError("no data")):
            with patch("server.deps.db") as mock_db:
                mock_db.get_trend.return_value = fake_trend
                resp = client.get("/api/disks/prediction", headers=admin_headers)
        # Even on fallback the endpoint must return 200 with correct keys
        assert resp.status_code == 200
        data = resp.json()
        assert "metrics" in data
        assert "combined" in data
