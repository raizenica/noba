# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Integration tests for the stats router (share/noba-web/server/routers/stats.py)."""
from __future__ import annotations



# ===========================================================================
# GET /api/health
# ===========================================================================

class TestHealth:
    """Public health endpoint — no auth required."""

    def test_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "uptime_s" in data


# ===========================================================================
# GET /api/me
# ===========================================================================

class TestMe:
    """Current user info — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/me")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/me", headers=viewer_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "viewer"
        assert "permissions" in data

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/me", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"


# ===========================================================================
# GET /api/stats
# ===========================================================================

class TestStats:
    """Live stats — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/stats", headers=viewer_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/stats", headers=admin_headers)
        assert resp.status_code == 200


# ===========================================================================
# GET /api/stream (SSE)
# ===========================================================================

class TestStream:
    """SSE stream — uses _get_auth_sse (query param token fallback)."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/stream")
        assert resp.status_code == 401

    def test_bearer_header_works(self, client, admin_headers):
        # SSE is streaming; just verify initial connection succeeds
        with client.stream("GET", "/api/stream", headers=admin_headers) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            # Read first chunk then break
            for _ in resp.iter_lines():
                break

    def test_query_param_token_works(self, client, admin_token):
        """SSE auth falls back to ?token= query param."""
        with client.stream("GET", f"/api/stream?token={admin_token}") as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            for _ in resp.iter_lines():
                break

    def test_invalid_query_token_returns_401(self, client):
        resp = client.get("/api/stream?token=bogus-token-value")
        assert resp.status_code == 401


# ===========================================================================
# GET /api/alert-rules (CRUD)
# ===========================================================================

class TestAlertRulesGet:
    """List alert rules — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/alert-rules")
        assert resp.status_code == 401

    def test_viewer_can_list(self, client, viewer_headers):
        resp = client.get("/api/alert-rules", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_admin_can_list(self, client, admin_headers):
        resp = client.get("/api/alert-rules", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestAlertRulesCreate:
    """Create alert rule — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/alert-rules", json={"condition": "cpuPercent > 90"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post(
            "/api/alert-rules",
            json={"condition": "cpuPercent > 90"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post(
            "/api/alert-rules",
            json={"condition": "cpuPercent > 90"},
            headers=operator_headers,
        )
        assert resp.status_code == 403

    def test_admin_can_create(self, client, admin_headers):
        resp = client.post(
            "/api/alert-rules",
            json={"condition": "cpuPercent > 90", "severity": "critical"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "id" in data

    def test_missing_condition_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/alert-rules",
            json={"severity": "warning"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_custom_id_preserved(self, client, admin_headers):
        resp = client.post(
            "/api/alert-rules",
            json={"id": "my-custom-id", "condition": "memPercent > 80"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == "my-custom-id"

    def test_malformed_condition_rejected(self, client, admin_headers):
        resp = client.post(
            "/api/alert-rules",
            json={"condition": ">"},
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert "Invalid condition" in resp.json()["detail"]

    def test_garbage_condition_rejected(self, client, admin_headers):
        resp = client.post(
            "/api/alert-rules",
            json={"condition": "hello world"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_composite_with_bad_part_rejected(self, client, admin_headers):
        resp = client.post(
            "/api/alert-rules",
            json={"condition": "cpuPercent > 80 AND badcondition"},
            headers=admin_headers,
        )
        assert resp.status_code == 400


class TestAlertRulesUpdate:
    """Update alert rule — admin only."""

    def _create_rule(self, client, admin_headers, rule_id="upd-rule"):
        client.post(
            "/api/alert-rules",
            json={"id": rule_id, "condition": "cpuPercent > 50"},
            headers=admin_headers,
        )

    def test_no_auth_returns_401(self, client):
        resp = client.put("/api/alert-rules/some-id", json={"severity": "critical"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.put(
            "/api/alert-rules/some-id",
            json={"severity": "critical"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.put(
            "/api/alert-rules/some-id",
            json={"severity": "critical"},
            headers=operator_headers,
        )
        assert resp.status_code == 403

    def test_admin_can_update(self, client, admin_headers):
        self._create_rule(client, admin_headers, "upd-test")
        resp = client.put(
            "/api/alert-rules/upd-test",
            json={"severity": "critical"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_update_nonexistent_returns_404(self, client, admin_headers):
        resp = client.put(
            "/api/alert-rules/nonexistent-xyz",
            json={"severity": "critical"},
            headers=admin_headers,
        )
        assert resp.status_code == 404


class TestAlertRulesDelete:
    """Delete alert rule — admin only."""

    def _create_rule(self, client, admin_headers, rule_id="del-rule"):
        client.post(
            "/api/alert-rules",
            json={"id": rule_id, "condition": "cpuPercent > 50"},
            headers=admin_headers,
        )

    def test_no_auth_returns_401(self, client):
        resp = client.delete("/api/alert-rules/some-id")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.delete("/api/alert-rules/some-id", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.delete("/api/alert-rules/some-id", headers=operator_headers)
        assert resp.status_code == 403

    def test_admin_can_delete(self, client, admin_headers):
        self._create_rule(client, admin_headers, "del-test")
        resp = client.delete("/api/alert-rules/del-test", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_delete_nonexistent_returns_404(self, client, admin_headers):
        resp = client.delete("/api/alert-rules/nonexistent-xyz", headers=admin_headers)
        assert resp.status_code == 404


# ===========================================================================
# GET /api/alert-rules/test/{rule_id}
# ===========================================================================

class TestAlertRuleTest:
    """Test alert rule against current stats — admin only."""

    def _create_rule(self, client, admin_headers, rule_id="test-rule"):
        client.post(
            "/api/alert-rules",
            json={"id": rule_id, "condition": "cpuPercent > 50"},
            headers=admin_headers,
        )

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/alert-rules/test/some-id")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/alert-rules/test/some-id", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.get("/api/alert-rules/test/some-id", headers=operator_headers)
        assert resp.status_code == 403

    def test_admin_can_test_rule(self, client, admin_headers):
        self._create_rule(client, admin_headers, "eval-rule")
        resp = client.get("/api/alert-rules/test/eval-rule", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["rule_id"] == "eval-rule"
        assert "result" in data
        assert "condition" in data

    def test_nonexistent_rule_returns_404(self, client, admin_headers):
        resp = client.get("/api/alert-rules/test/nonexistent-xyz", headers=admin_headers)
        assert resp.status_code == 404


# ===========================================================================
# /api/notifications
# ===========================================================================

class TestNotifications:
    """Notification endpoints — any authenticated user (own notifications)."""

    def test_list_no_auth_returns_401(self, client):
        resp = client.get("/api/notifications")
        assert resp.status_code == 401

    def test_list_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/notifications", headers=viewer_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "notifications" in data
        assert "unread_count" in data

    def test_list_with_unread_filter(self, client, admin_headers):
        resp = client.get("/api/notifications?unread=1&limit=10", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json()["notifications"], list)

    def test_mark_read_no_auth_returns_401(self, client):
        resp = client.post("/api/notifications/1/read")
        assert resp.status_code == 401

    def test_mark_read_viewer_can_access(self, client, viewer_headers):
        # Even if notification doesn't exist, the endpoint should not error
        resp = client.post("/api/notifications/999/read", headers=viewer_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_read_all_no_auth_returns_401(self, client):
        resp = client.post("/api/notifications/read-all")
        assert resp.status_code == 401

    def test_read_all_viewer_can_access(self, client, viewer_headers):
        resp = client.post("/api/notifications/read-all", headers=viewer_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_read_all_admin_can_access(self, client, admin_headers):
        resp = client.post("/api/notifications/read-all", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ===========================================================================
# /api/dashboard
# ===========================================================================

class TestDashboard:
    """Dashboard save/load — any authenticated user (own dashboard)."""

    def test_get_no_auth_returns_401(self, client):
        resp = client.get("/api/dashboard")
        assert resp.status_code == 401

    def test_save_no_auth_returns_401(self, client):
        resp = client.post("/api/dashboard", json={"card_order": ["cpu", "mem"]})
        assert resp.status_code == 401

    def test_viewer_can_load(self, client, viewer_headers):
        resp = client.get("/api/dashboard", headers=viewer_headers)
        assert resp.status_code == 200
        # Empty dashboard returns {}
        assert isinstance(resp.json(), dict)

    def test_admin_can_save_and_load(self, client, admin_headers):
        save_resp = client.post(
            "/api/dashboard",
            json={"card_order": ["cpu", "mem", "disk"], "card_vis": {"cpu": True}},
            headers=admin_headers,
        )
        assert save_resp.status_code == 200
        assert save_resp.json()["status"] == "ok"

        load_resp = client.get("/api/dashboard", headers=admin_headers)
        assert load_resp.status_code == 200

    def test_operator_can_save(self, client, operator_headers):
        resp = client.post(
            "/api/dashboard",
            json={"card_order": ["net"]},
            headers=operator_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ===========================================================================
# GET /api/history/{metric}
# ===========================================================================

class TestHistory:
    """History endpoints — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/history/cpuPercent")
        assert resp.status_code == 401

    def test_unknown_metric_returns_400(self, client, admin_headers):
        resp = client.get("/api/history/totally_fake_metric", headers=admin_headers)
        assert resp.status_code == 400

    def test_valid_metric_returns_200(self, client, admin_headers):
        from server.config import HISTORY_METRICS
        if HISTORY_METRICS:
            metric = list(HISTORY_METRICS)[0]
            resp = client.get(f"/api/history/{metric}", headers=admin_headers)
            assert resp.status_code == 200

    def test_export_no_auth_returns_401(self, client):
        resp = client.get("/api/history/cpuPercent/export")
        assert resp.status_code == 401

    def test_export_unknown_metric_returns_400(self, client, admin_headers):
        resp = client.get("/api/history/fake_metric/export", headers=admin_headers)
        assert resp.status_code == 400

    def test_trend_no_auth_returns_401(self, client):
        resp = client.get("/api/history/cpuPercent/trend")
        assert resp.status_code == 401

    def test_trend_unknown_metric_returns_400(self, client, admin_headers):
        resp = client.get("/api/history/fake_metric/trend", headers=admin_headers)
        assert resp.status_code == 400

    def test_multi_no_auth_returns_401(self, client):
        resp = client.get("/api/history/multi?metrics=cpuPercent")
        assert resp.status_code == 401

    def test_multi_no_metrics_returns_400(self, client, admin_headers):
        resp = client.get("/api/history/multi", headers=admin_headers)
        assert resp.status_code == 400


# ===========================================================================
# GET /api/metrics/*
# ===========================================================================

class TestMetrics:
    """Metrics endpoints — any authenticated user."""

    def test_available_no_auth_returns_401(self, client):
        resp = client.get("/api/metrics/available")
        assert resp.status_code == 401

    def test_available_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/metrics/available", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_prometheus_no_auth_returns_401(self, client):
        resp = client.get("/api/metrics/prometheus")
        assert resp.status_code == 401

    def test_prometheus_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/metrics/prometheus", headers=viewer_headers)
        assert resp.status_code == 200

    def test_correlate_no_auth_returns_401(self, client):
        resp = client.get("/api/metrics/correlate?metrics=cpuPercent")
        assert resp.status_code == 401

    def test_correlate_missing_metrics_returns_400(self, client, admin_headers):
        resp = client.get("/api/metrics/correlate", headers=admin_headers)
        assert resp.status_code == 400
