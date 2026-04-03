# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Integration tests for the intelligence router (share/noba-web/server/routers/intelligence.py)."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_status_incident(client, admin_headers, title="War Room Incident"):
    """Create a status page incident and return its id (needed for war room routes)."""
    resp = client.post(
        "/api/status/incidents/create",
        json={"title": title, "severity": "minor", "message": "test"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _seed_alert(rule_id="cpu_high", severity="warning", message="CPU usage high"):
    """Insert an alert directly into the DB and return its id."""
    from server.deps import db
    conn = db._get_conn()
    with db._lock:
        c = conn.execute(
            "INSERT INTO alert_history (rule_id, timestamp, severity, message) VALUES (?,?,?,?)",
            (rule_id, int(time.time()), severity, message),
        )
        conn.commit()
    return c.lastrowid


def _seed_incident(severity="warning", source="test", title="Test Incident"):
    """Insert an incident directly into the DB and return its id."""
    from server.deps import db
    return db.insert_incident(severity, source, title, "test details")


def _make_async_mock_llm(response="AI response text"):
    """Build an async-capable mock LLM client."""
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(return_value=response)
    return mock_llm


# ===========================================================================
# GET /api/incidents
# ===========================================================================

class TestListIncidents:
    """GET /api/incidents — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/incidents")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/incidents", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/incidents", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/incidents", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_list(self, client, admin_headers):
        resp = client.get("/api/incidents", headers=admin_headers)
        assert isinstance(resp.json(), list)

    def test_returns_seeded_incident(self, client, admin_headers):
        inc_id = _seed_incident(title="Seeded Incident")
        resp = client.get("/api/incidents", headers=admin_headers)
        assert resp.status_code == 200
        ids = [i["id"] for i in resp.json()]
        assert inc_id in ids

    def test_hours_param_accepted(self, client, admin_headers):
        resp = client.get("/api/incidents?hours=48", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_hours_capped_at_168(self, client, admin_headers):
        # Should not error even with very large value — capped to 168
        resp = client.get("/api/incidents?hours=9999", headers=admin_headers)
        assert resp.status_code == 200


# ===========================================================================
# POST /api/incidents/{id}/resolve
# ===========================================================================

class TestResolveIncident:
    """POST /api/incidents/{id}/resolve — operator+ required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/incidents/1/resolve")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/incidents/1/resolve", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_can_resolve(self, client, operator_headers):
        inc_id = _seed_incident(title="To Resolve")
        resp = client.post(f"/api/incidents/{inc_id}/resolve", headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_admin_can_resolve(self, client, admin_headers):
        inc_id = _seed_incident(title="To Resolve Admin")
        resp = client.post(f"/api/incidents/{inc_id}/resolve", headers=admin_headers)
        assert resp.status_code == 200

    def test_resolve_nonexistent_id_still_ok(self, client, admin_headers):
        # resolve_incident does an UPDATE — no 404 since the DB method doesn't check rows
        resp = client.post("/api/incidents/99999/resolve", headers=admin_headers)
        assert resp.status_code == 200


# ===========================================================================
# GET /api/incidents/{id}/messages   (War Room)
# ===========================================================================

class TestGetIncidentMessages:
    """GET /api/incidents/{id}/messages — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/incidents/1/messages")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers, admin_headers):
        inc_id = _create_status_incident(client, admin_headers)
        resp = client.get(f"/api/incidents/{inc_id}/messages", headers=viewer_headers)
        assert resp.status_code == 200

    def test_returns_404_for_unknown_incident(self, client, admin_headers):
        resp = client.get("/api/incidents/99999/messages", headers=admin_headers)
        assert resp.status_code == 404

    def test_returns_messages_structure(self, client, admin_headers):
        inc_id = _create_status_incident(client, admin_headers)
        resp = client.get(f"/api/incidents/{inc_id}/messages", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["incident_id"] == inc_id
        assert "messages" in data
        assert isinstance(data["messages"], list)

    def test_messages_appear_after_post(self, client, admin_headers, operator_headers):
        inc_id = _create_status_incident(client, admin_headers)
        client.post(
            f"/api/incidents/{inc_id}/messages",
            json={"message": "Hello war room"},
            headers=operator_headers,
        )
        resp = client.get(f"/api/incidents/{inc_id}/messages", headers=admin_headers)
        msgs = resp.json()["messages"]
        assert any(m["message"] == "Hello war room" for m in msgs)


# ===========================================================================
# POST /api/incidents/{id}/messages   (War Room)
# ===========================================================================

class TestPostIncidentMessage:
    """POST /api/incidents/{id}/messages — operator+ required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/incidents/1/messages", json={"message": "hi"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post(
            "/api/incidents/1/messages",
            json={"message": "hi"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_returns_404_for_unknown_incident(self, client, operator_headers):
        resp = client.post(
            "/api/incidents/99999/messages",
            json={"message": "hello"},
            headers=operator_headers,
        )
        assert resp.status_code == 404

    def test_empty_message_returns_400(self, client, operator_headers, admin_headers):
        inc_id = _create_status_incident(client, admin_headers)
        resp = client.post(
            f"/api/incidents/{inc_id}/messages",
            json={"message": ""},
            headers=operator_headers,
        )
        assert resp.status_code == 400

    def test_invalid_msg_type_returns_400(self, client, operator_headers, admin_headers):
        inc_id = _create_status_incident(client, admin_headers)
        resp = client.post(
            f"/api/incidents/{inc_id}/messages",
            json={"message": "test", "msg_type": "invalid_type"},
            headers=operator_headers,
        )
        assert resp.status_code == 400

    def test_operator_can_post_comment(self, client, operator_headers, admin_headers):
        inc_id = _create_status_incident(client, admin_headers)
        resp = client.post(
            f"/api/incidents/{inc_id}/messages",
            json={"message": "Investigating now", "msg_type": "comment"},
            headers=operator_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "id" in data

    def test_admin_can_post_note(self, client, admin_headers):
        inc_id = _create_status_incident(client, admin_headers)
        resp = client.post(
            f"/api/incidents/{inc_id}/messages",
            json={"message": "Admin note", "msg_type": "note"},
            headers=admin_headers,
        )
        assert resp.status_code == 200

    def test_valid_msg_types_accepted(self, client, operator_headers, admin_headers):
        inc_id = _create_status_incident(client, admin_headers)
        for msg_type in ("comment", "system", "action", "note"):
            resp = client.post(
                f"/api/incidents/{inc_id}/messages",
                json={"message": f"A {msg_type} message", "msg_type": msg_type},
                headers=operator_headers,
            )
            assert resp.status_code == 200, f"msg_type={msg_type} failed: {resp.text}"


# ===========================================================================
# PUT /api/incidents/{id}/assign   (War Room)
# ===========================================================================

class TestAssignIncident:
    """PUT /api/incidents/{id}/assign — operator+ required."""

    def test_no_auth_returns_401(self, client):
        resp = client.put("/api/incidents/1/assign", json={"assigned_to": "alice"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.put(
            "/api/incidents/1/assign",
            json={"assigned_to": "alice"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_returns_404_for_unknown_incident(self, client, operator_headers):
        resp = client.put(
            "/api/incidents/99999/assign",
            json={"assigned_to": "alice"},
            headers=operator_headers,
        )
        assert resp.status_code == 404

    def test_missing_assigned_to_returns_400(self, client, operator_headers, admin_headers):
        inc_id = _create_status_incident(client, admin_headers)
        resp = client.put(
            f"/api/incidents/{inc_id}/assign",
            json={"assigned_to": ""},
            headers=operator_headers,
        )
        assert resp.status_code == 400

    def test_operator_can_assign(self, client, operator_headers, admin_headers):
        inc_id = _create_status_incident(client, admin_headers)
        resp = client.put(
            f"/api/incidents/{inc_id}/assign",
            json={"assigned_to": "alice"},
            headers=operator_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["assigned_to"] == "alice"

    def test_admin_can_assign(self, client, admin_headers):
        inc_id = _create_status_incident(client, admin_headers)
        resp = client.put(
            f"/api/incidents/{inc_id}/assign",
            json={"assigned_to": "bob"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["assigned_to"] == "bob"

    def test_assign_posts_system_message(self, client, operator_headers, admin_headers):
        inc_id = _create_status_incident(client, admin_headers)
        client.put(
            f"/api/incidents/{inc_id}/assign",
            json={"assigned_to": "charlie"},
            headers=operator_headers,
        )
        msgs_resp = client.get(f"/api/incidents/{inc_id}/messages", headers=admin_headers)
        msgs = msgs_resp.json()["messages"]
        assert any("charlie" in m["message"] for m in msgs)


# ===========================================================================
# GET /api/dependencies
# ===========================================================================

class TestListDependencies:
    """GET /api/dependencies — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/dependencies")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/dependencies", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/dependencies", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/dependencies", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_graph_structure(self, client, admin_headers):
        resp = client.get("/api/dependencies", headers=admin_headers)
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data
        assert "dependencies" in data

    def test_created_dependency_appears_in_graph(self, client, admin_headers):
        client.post(
            "/api/dependencies",
            json={"source": "service-a", "target": "service-b", "type": "requires"},
            headers=admin_headers,
        )
        resp = client.get("/api/dependencies", headers=admin_headers)
        data = resp.json()
        node_ids = [n["id"] for n in data["nodes"]]
        assert "service-a" in node_ids
        assert "service-b" in node_ids
        edge_pairs = [(e["source"], e["target"]) for e in data["edges"]]
        assert ("service-a", "service-b") in edge_pairs


# ===========================================================================
# POST /api/dependencies
# ===========================================================================

class TestCreateDependency:
    """POST /api/dependencies — admin required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/dependencies", json={"source": "a", "target": "b"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post(
            "/api/dependencies",
            json={"source": "a", "target": "b"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post(
            "/api/dependencies",
            json={"source": "a", "target": "b"},
            headers=operator_headers,
        )
        assert resp.status_code == 403

    def test_missing_source_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/dependencies",
            json={"source": "", "target": "b"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_missing_target_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/dependencies",
            json={"source": "a", "target": ""},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_self_dependency_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/dependencies",
            json={"source": "self-svc", "target": "self-svc"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_invalid_type_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/dependencies",
            json={"source": "a", "target": "b", "type": "bad_type"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_admin_creates_requires_dependency(self, client, admin_headers):
        resp = client.post(
            "/api/dependencies",
            json={"source": "web", "target": "database", "type": "requires"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "id" in data

    def test_admin_creates_optional_dependency(self, client, admin_headers):
        resp = client.post(
            "/api/dependencies",
            json={"source": "api", "target": "cache", "type": "optional"},
            headers=admin_headers,
        )
        assert resp.status_code == 200

    def test_admin_creates_network_dependency(self, client, admin_headers):
        resp = client.post(
            "/api/dependencies",
            json={"source": "proxy", "target": "upstream", "type": "network"},
            headers=admin_headers,
        )
        assert resp.status_code == 200


# ===========================================================================
# DELETE /api/dependencies/{dep_id}
# ===========================================================================

class TestDeleteDependency:
    """DELETE /api/dependencies/{dep_id} — admin required."""

    def test_no_auth_returns_401(self, client):
        resp = client.delete("/api/dependencies/1")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.delete("/api/dependencies/1", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.delete("/api/dependencies/1", headers=operator_headers)
        assert resp.status_code == 403

    def test_delete_nonexistent_returns_404(self, client, admin_headers):
        resp = client.delete("/api/dependencies/99999", headers=admin_headers)
        assert resp.status_code == 404

    def test_admin_can_delete(self, client, admin_headers):
        create_resp = client.post(
            "/api/dependencies",
            json={"source": "del-src", "target": "del-tgt", "type": "requires"},
            headers=admin_headers,
        )
        dep_id = create_resp.json()["id"]
        resp = client.delete(f"/api/dependencies/{dep_id}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_deleted_dependency_not_in_list(self, client, admin_headers):
        create_resp = client.post(
            "/api/dependencies",
            json={"source": "gone-src", "target": "gone-tgt", "type": "requires"},
            headers=admin_headers,
        )
        dep_id = create_resp.json()["id"]
        client.delete(f"/api/dependencies/{dep_id}", headers=admin_headers)
        list_resp = client.get("/api/dependencies", headers=admin_headers)
        dep_ids = [e["id"] for e in list_resp.json()["edges"]]
        assert dep_id not in dep_ids


# ===========================================================================
# GET /api/dependencies/impact/{service}
# ===========================================================================

class TestImpactAnalysis:
    """GET /api/dependencies/impact/{service} — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/dependencies/impact/myservice")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/dependencies/impact/myservice", headers=viewer_headers)
        assert resp.status_code == 200

    def test_returns_structure(self, client, admin_headers):
        resp = client.get("/api/dependencies/impact/myservice", headers=admin_headers)
        data = resp.json()
        assert "service" in data
        assert "affected" in data
        assert "count" in data

    def test_empty_result_for_unknown_service(self, client, admin_headers):
        resp = client.get(
            "/api/dependencies/impact/totally-unknown-svc-xyz", headers=admin_headers
        )
        data = resp.json()
        assert data["count"] == 0
        assert data["affected"] == []

    def test_impact_traversal_two_hops(self, client, admin_headers):
        # db: svc-a -> svc-b -> svc-c; impact of svc-a should include svc-b and svc-c
        client.post(
            "/api/dependencies",
            json={"source": "svc-b", "target": "svc-a", "type": "requires"},
            headers=admin_headers,
        )
        client.post(
            "/api/dependencies",
            json={"source": "svc-c", "target": "svc-b", "type": "requires"},
            headers=admin_headers,
        )
        resp = client.get("/api/dependencies/impact/svc-a", headers=admin_headers)
        data = resp.json()
        assert "svc-b" in data["affected"]
        assert data["count"] >= 1


# ===========================================================================
# POST /api/dependencies/discover/{hostname}
# ===========================================================================

class TestDiscoverServices:
    """POST /api/dependencies/discover/{hostname} — operator required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/dependencies/discover/myhost")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post(
            "/api/dependencies/discover/myhost", headers=viewer_headers
        )
        assert resp.status_code == 403

    def test_operator_can_access(self, client, operator_headers):
        resp = client.post(
            "/api/dependencies/discover/myhost", headers=operator_headers
        )
        assert resp.status_code == 200

    def test_admin_queues_command_for_unknown_host(self, client, admin_headers):
        resp = client.post(
            "/api/dependencies/discover/unknown-host", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert "id" in data

    def test_command_added_to_agent_queue(self, client, admin_headers):
        from server.agent_store import _agent_commands, _agent_cmd_lock
        resp = client.post(
            "/api/dependencies/discover/queue-test-host", headers=admin_headers
        )
        assert resp.status_code == 200
        cmd_id = resp.json()["id"]
        with _agent_cmd_lock:
            queued = _agent_commands.get("queue-test-host", [])
        assert any(c["id"] == cmd_id for c in queued)


# ===========================================================================
# GET /api/baselines
# ===========================================================================

class TestListBaselines:
    """GET /api/baselines — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/baselines")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/baselines", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/baselines", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/baselines", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_list(self, client, admin_headers):
        resp = client.get("/api/baselines", headers=admin_headers)
        assert isinstance(resp.json(), list)

    def test_created_baseline_appears(self, client, admin_headers):
        client.post(
            "/api/baselines",
            json={"path": "/etc/hosts", "expected_hash": "abc123"},
            headers=admin_headers,
        )
        resp = client.get("/api/baselines", headers=admin_headers)
        paths = [b["path"] for b in resp.json()]
        assert "/etc/hosts" in paths


# ===========================================================================
# POST /api/baselines
# ===========================================================================

class TestCreateBaseline:
    """POST /api/baselines — admin required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post(
            "/api/baselines",
            json={"path": "/etc/hosts", "expected_hash": "abc"},
        )
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post(
            "/api/baselines",
            json={"path": "/etc/hosts", "expected_hash": "abc"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post(
            "/api/baselines",
            json={"path": "/etc/hosts", "expected_hash": "abc"},
            headers=operator_headers,
        )
        assert resp.status_code == 403

    def test_missing_path_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/baselines",
            json={"path": "", "expected_hash": "abc"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_missing_hash_returns_400(self, client, admin_headers):
        resp = client.post(
            "/api/baselines",
            json={"path": "/etc/hosts", "expected_hash": ""},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_admin_creates_baseline(self, client, admin_headers):
        resp = client.post(
            "/api/baselines",
            json={"path": "/etc/resolv.conf", "expected_hash": "deadbeef"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "id" in data

    def test_agent_group_optional(self, client, admin_headers):
        resp = client.post(
            "/api/baselines",
            json={
                "path": "/etc/passwd",
                "expected_hash": "cafebabe",
                "agent_group": "prod",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200


# ===========================================================================
# DELETE /api/baselines/{id}
# ===========================================================================

class TestDeleteBaseline:
    """DELETE /api/baselines/{id} — admin required."""

    def test_no_auth_returns_401(self, client):
        resp = client.delete("/api/baselines/1")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.delete("/api/baselines/1", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.delete("/api/baselines/1", headers=operator_headers)
        assert resp.status_code == 403

    def test_delete_nonexistent_returns_404(self, client, admin_headers):
        resp = client.delete("/api/baselines/99999", headers=admin_headers)
        assert resp.status_code == 404

    def test_admin_can_delete(self, client, admin_headers):
        create_resp = client.post(
            "/api/baselines",
            json={"path": "/tmp/to-delete", "expected_hash": "aabbcc"},
            headers=admin_headers,
        )
        bid = create_resp.json()["id"]
        resp = client.delete(f"/api/baselines/{bid}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_deleted_baseline_not_in_list(self, client, admin_headers):
        create_resp = client.post(
            "/api/baselines",
            json={"path": "/tmp/gone", "expected_hash": "112233"},
            headers=admin_headers,
        )
        bid = create_resp.json()["id"]
        client.delete(f"/api/baselines/{bid}", headers=admin_headers)
        list_resp = client.get("/api/baselines", headers=admin_headers)
        ids = [b["id"] for b in list_resp.json()]
        assert bid not in ids


# ===========================================================================
# POST /api/baselines/{id}/set-from/{hostname}
# ===========================================================================

class TestBaselineSetFromAgent:
    """POST /api/baselines/{id}/set-from/{hostname} — admin required, polls agent."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/baselines/1/set-from/myhost")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/baselines/1/set-from/myhost", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post(
            "/api/baselines/1/set-from/myhost", headers=operator_headers
        )
        assert resp.status_code == 403

    def test_unknown_baseline_returns_404(self, client, admin_headers):
        resp = client.post(
            "/api/baselines/99999/set-from/myhost", headers=admin_headers
        )
        assert resp.status_code == 404

    def test_agent_timeout_returns_504(self, client, admin_headers):
        """When the agent never responds the endpoint should return 504."""
        import asyncio as _asyncio
        create_resp = client.post(
            "/api/baselines",
            json={"path": "/etc/noba.conf", "expected_hash": "oldhash"},
            headers=admin_headers,
        )
        bid = create_resp.json()["id"]

        # Make time.time advance past the 15-second deadline immediately after the
        # first call (which sets the deadline), so the while-loop exits right away.
        real_time = time.time
        call_count = [0]

        def fast_time():
            call_count[0] += 1
            if call_count[0] > 1:
                return real_time() + 30  # past deadline
            return real_time()

        with patch("server.routers.intelligence.time") as mock_time, \
             patch.object(_asyncio, "sleep", new_callable=AsyncMock):
            mock_time.time = fast_time
            resp = client.post(
                f"/api/baselines/{bid}/set-from/somehost", headers=admin_headers
            )
        assert resp.status_code == 504

    def test_agent_result_injected_updates_baseline(self, client, admin_headers):
        """Inject an agent result directly into _agent_cmd_results so the poll succeeds."""
        import asyncio as _asyncio
        from server.agent_store import _agent_cmd_results, _agent_cmd_lock
        from server.deps import db as real_db

        create_resp = client.post(
            "/api/baselines",
            json={"path": "/etc/shadow", "expected_hash": "initial"},
            headers=admin_headers,
        )
        bid = create_resp.json()["id"]

        injected: list[dict] = []
        # Save the original unpatched method to avoid recursion
        _original_record_command = real_db.record_command

        def capture_cmd_id(cmd_id, hostname, cmd_type, params, queued_by):
            # Pre-populate the results store so the poll loop finds the result immediately
            entry = {"id": cmd_id, "status": "ok", "checksum": "newhashvalue1234"}
            injected.append(entry)
            with _agent_cmd_lock:
                _agent_cmd_results.setdefault("agent-host", []).append(entry)
            _original_record_command(cmd_id, "agent-host", cmd_type, params, queued_by)

        with patch.object(real_db, "record_command", side_effect=capture_cmd_id), \
             patch.object(_asyncio, "sleep", new_callable=AsyncMock):
            resp = client.post(
                f"/api/baselines/{bid}/set-from/agent-host", headers=admin_headers
            )

        assert resp.status_code == 200
        assert resp.json()["expected_hash"] == "newhashvalue1234"



# ===========================================================================
# POST /api/baselines/check
# ===========================================================================

class TestTriggerDriftCheck:
    """POST /api/baselines/check — operator+ required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/baselines/check")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/baselines/check", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_triggers_check(self, client, operator_headers):
        import server.scheduler  # ensure module is loaded so patching works
        with patch.object(server.scheduler.drift_checker, "run_check_now"):
            resp = client.post("/api/baselines/check", headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "message" in data

    def test_admin_triggers_check(self, client, admin_headers):
        import server.scheduler
        with patch.object(server.scheduler.drift_checker, "run_check_now"):
            resp = client.post("/api/baselines/check", headers=admin_headers)
        assert resp.status_code == 200


# ===========================================================================
# GET /api/baselines/{id}/results
# ===========================================================================

class TestBaselineResults:
    """GET /api/baselines/{id}/results — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/baselines/1/results")
        assert resp.status_code == 401

    def test_returns_404_for_unknown_baseline(self, client, admin_headers):
        resp = client.get("/api/baselines/99999/results", headers=admin_headers)
        assert resp.status_code == 404

    def test_viewer_can_access(self, client, viewer_headers, admin_headers):
        create_resp = client.post(
            "/api/baselines",
            json={"path": "/etc/motd", "expected_hash": "xxyyzz"},
            headers=admin_headers,
        )
        bid = create_resp.json()["id"]
        resp = client.get(f"/api/baselines/{bid}/results", headers=viewer_headers)
        assert resp.status_code == 200

    def test_returns_structure(self, client, admin_headers):
        create_resp = client.post(
            "/api/baselines",
            json={"path": "/etc/fstab", "expected_hash": "112233"},
            headers=admin_headers,
        )
        bid = create_resp.json()["id"]
        resp = client.get(f"/api/baselines/{bid}/results", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "baseline" in data
        assert "results" in data
        assert isinstance(data["results"], list)
        assert data["baseline"]["path"] == "/etc/fstab"


# ===========================================================================
# GET /api/ai/status
# ===========================================================================

class TestAiStatus:
    """GET /api/ai/status — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/ai/status")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/ai/status", headers=viewer_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/ai/status", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_enabled_field(self, client, admin_headers):
        resp = client.get("/api/ai/status", headers=admin_headers)
        data = resp.json()
        assert "enabled" in data
        assert "provider" in data
        assert "model" in data

    def test_llm_disabled_by_default(self, client, admin_headers):
        # The test environment has no LLM configured — enabled should be False
        with patch(
            "server.routers.intelligence.read_yaml_settings",
            return_value={"llmEnabled": False},
        ):
            resp = client.get("/api/ai/status", headers=admin_headers)
        assert resp.json()["enabled"] is False


# ===========================================================================
# POST /api/ai/chat
# ===========================================================================

class TestAiChat:
    """POST /api/ai/chat — operator+ required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/ai/chat", json={"message": "hello"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post(
            "/api/ai/chat", json={"message": "hello"}, headers=viewer_headers
        )
        assert resp.status_code == 403

    def test_llm_not_configured_returns_503(self, client, operator_headers):
        with patch(
            "server.routers.intelligence._get_llm_client", return_value=None
        ):
            resp = client.post(
                "/api/ai/chat", json={"message": "hello"}, headers=operator_headers
            )
        assert resp.status_code == 503

    def test_empty_message_returns_400(self, client, operator_headers):
        mock_llm = _make_async_mock_llm()
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm), \
             patch("server.routers.intelligence._build_ai_context", return_value="ctx"), \
             patch("server.llm.extract_actions", return_value=[]):
            resp = client.post(
                "/api/ai/chat", json={"message": ""}, headers=operator_headers
            )
        assert resp.status_code == 400

    def test_operator_gets_ai_response(self, client, operator_headers):
        mock_llm = _make_async_mock_llm("Hello from AI")
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm), \
             patch("server.routers.intelligence._build_ai_context", return_value="ctx"), \
             patch("server.llm.extract_actions", return_value=[]):
            resp = client.post(
                "/api/ai/chat", json={"message": "Hello"}, headers=operator_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["response"] == "Hello from AI"
        assert "actions" in data

    def test_admin_gets_ai_response(self, client, admin_headers):
        mock_llm = _make_async_mock_llm("Admin response")
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm), \
             patch("server.routers.intelligence._build_ai_context", return_value="ctx"), \
             patch("server.llm.extract_actions", return_value=[]):
            resp = client.post(
                "/api/ai/chat", json={"message": "Status?"}, headers=admin_headers
            )
        assert resp.status_code == 200

    def test_history_is_included_in_request(self, client, operator_headers):
        mock_llm = _make_async_mock_llm("Contextual reply")
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm), \
             patch("server.routers.intelligence._build_ai_context", return_value="ctx"), \
             patch("server.llm.extract_actions", return_value=[]):
            resp = client.post(
                "/api/ai/chat",
                json={
                    "message": "Follow-up question",
                    "history": [
                        {"role": "user", "content": "Hello"},
                        {"role": "assistant", "content": "Hi there"},
                    ],
                },
                headers=operator_headers,
            )
        assert resp.status_code == 200
        # Verify chat was called with history messages + new message
        call_args = mock_llm.chat.call_args
        messages_passed = call_args[0][0]
        assert len(messages_passed) == 3  # 2 history + 1 new

    def test_llm_exception_returns_502(self, client, operator_headers):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=RuntimeError("LLM down"))
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm), \
             patch("server.routers.intelligence._build_ai_context", return_value="ctx"), \
             patch("server.llm.extract_actions", return_value=[]):
            resp = client.post(
                "/api/ai/chat", json={"message": "Hello"}, headers=operator_headers
            )
        assert resp.status_code == 502


# ===========================================================================
# POST /api/ai/analyze-alert/{alert_id}
# ===========================================================================

class TestAiAnalyzeAlert:
    """POST /api/ai/analyze-alert/{alert_id} — operator+ required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/ai/analyze-alert/1")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/ai/analyze-alert/1", headers=viewer_headers)
        assert resp.status_code == 403

    def test_llm_not_configured_returns_503(self, client, operator_headers):
        with patch("server.routers.intelligence._get_llm_client", return_value=None):
            resp = client.post("/api/ai/analyze-alert/1", headers=operator_headers)
        assert resp.status_code == 503

    def test_unknown_alert_returns_404(self, client, operator_headers):
        mock_llm = _make_async_mock_llm()
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm), \
             patch("server.routers.intelligence._build_ai_context", return_value="ctx"), \
             patch("server.llm.extract_actions", return_value=[]):
            resp = client.post(
                "/api/ai/analyze-alert/99999", headers=operator_headers
            )
        assert resp.status_code == 404

    def test_operator_can_analyze_alert(self, client, operator_headers):
        alert_id = _seed_alert(rule_id="mem_high", severity="critical", message="OOM")
        mock_llm = _make_async_mock_llm("Check memory usage")
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm), \
             patch("server.routers.intelligence._build_ai_context", return_value="ctx"), \
             patch("server.llm.extract_actions", return_value=[]):
            resp = client.post(
                f"/api/ai/analyze-alert/{alert_id}", headers=operator_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["response"] == "Check memory usage"
        assert "actions" in data

    def test_admin_can_analyze_alert(self, client, admin_headers):
        alert_id = _seed_alert(rule_id="disk_full", severity="warning", message="Disk 95%")
        mock_llm = _make_async_mock_llm("Free disk space")
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm), \
             patch("server.routers.intelligence._build_ai_context", return_value="ctx"), \
             patch("server.llm.extract_actions", return_value=[]):
            resp = client.post(
                f"/api/ai/analyze-alert/{alert_id}", headers=admin_headers
            )
        assert resp.status_code == 200


# ===========================================================================
# POST /api/ai/analyze-logs
# ===========================================================================

class TestAiAnalyzeLogs:
    """POST /api/ai/analyze-logs — operator+ required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/ai/analyze-logs", json={"logs": "some log"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post(
            "/api/ai/analyze-logs", json={"logs": "some log"}, headers=viewer_headers
        )
        assert resp.status_code == 403

    def test_llm_not_configured_returns_503(self, client, operator_headers):
        with patch("server.routers.intelligence._get_llm_client", return_value=None):
            resp = client.post(
                "/api/ai/analyze-logs",
                json={"logs": "some log"},
                headers=operator_headers,
            )
        assert resp.status_code == 503

    def test_empty_logs_returns_400(self, client, operator_headers):
        mock_llm = _make_async_mock_llm()
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm), \
             patch("server.routers.intelligence._build_ai_context", return_value="ctx"), \
             patch("server.llm.extract_actions", return_value=[]):
            resp = client.post(
                "/api/ai/analyze-logs", json={"logs": ""}, headers=operator_headers
            )
        assert resp.status_code == 400

    def test_operator_can_analyze_logs(self, client, operator_headers):
        log_text = "2024-01-01 ERROR: connection refused\n2024-01-01 WARN: retry 3/3"
        mock_llm = _make_async_mock_llm("Connection issue detected")
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm), \
             patch("server.routers.intelligence._build_ai_context", return_value="ctx"), \
             patch("server.llm.extract_actions", return_value=[]):
            resp = client.post(
                "/api/ai/analyze-logs",
                json={"logs": log_text},
                headers=operator_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["response"] == "Connection issue detected"
        assert "actions" in data

    def test_logs_truncated_at_8000_chars(self, client, operator_headers):
        long_log = "X" * 9000
        mock_llm = _make_async_mock_llm("Truncated")
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm), \
             patch("server.routers.intelligence._build_ai_context", return_value="ctx"), \
             patch("server.llm.extract_actions", return_value=[]):
            resp = client.post(
                "/api/ai/analyze-logs",
                json={"logs": long_log},
                headers=operator_headers,
            )
        assert resp.status_code == 200
        # Verify the prompt sent to LLM was truncated (log portion ≤ 8000 + "truncated" suffix)
        call_args = mock_llm.chat.call_args
        prompt_content = call_args[0][0][0]["content"]
        assert "(truncated)" in prompt_content

    def test_admin_can_analyze_logs(self, client, admin_headers):
        mock_llm = _make_async_mock_llm("All good")
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm), \
             patch("server.routers.intelligence._build_ai_context", return_value="ctx"), \
             patch("server.llm.extract_actions", return_value=[]):
            resp = client.post(
                "/api/ai/analyze-logs",
                json={"logs": "INFO: healthy"},
                headers=admin_headers,
            )
        assert resp.status_code == 200


# ===========================================================================
# POST /api/ai/summarize-incident/{incident_id}
# ===========================================================================

class TestAiSummarizeIncident:
    """POST /api/ai/summarize-incident/{incident_id} — operator+ required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/ai/summarize-incident/1")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/ai/summarize-incident/1", headers=viewer_headers)
        assert resp.status_code == 403

    def test_llm_not_configured_returns_503(self, client, operator_headers):
        with patch("server.routers.intelligence._get_llm_client", return_value=None):
            resp = client.post(
                "/api/ai/summarize-incident/1", headers=operator_headers
            )
        assert resp.status_code == 503

    def test_unknown_incident_returns_404(self, client, operator_headers):
        mock_llm = _make_async_mock_llm()
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm), \
             patch("server.routers.intelligence._build_ai_context", return_value="ctx"), \
             patch("server.llm.extract_actions", return_value=[]):
            resp = client.post(
                "/api/ai/summarize-incident/99999", headers=operator_headers
            )
        assert resp.status_code == 404

    def test_operator_can_summarize_incident(self, client, operator_headers):
        inc_id = _seed_incident(severity="critical", title="Database Failure")
        mock_llm = _make_async_mock_llm("Database went down due to OOM")
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm), \
             patch("server.routers.intelligence._build_ai_context", return_value="ctx"), \
             patch("server.llm.extract_actions", return_value=[]):
            resp = client.post(
                f"/api/ai/summarize-incident/{inc_id}", headers=operator_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["response"] == "Database went down due to OOM"
        assert "actions" in data

    def test_admin_can_summarize_incident(self, client, admin_headers):
        inc_id = _seed_incident(severity="warning", title="Network Flap")
        mock_llm = _make_async_mock_llm("Network interface reset")
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm), \
             patch("server.routers.intelligence._build_ai_context", return_value="ctx"), \
             patch("server.llm.extract_actions", return_value=[]):
            resp = client.post(
                f"/api/ai/summarize-incident/{inc_id}", headers=admin_headers
            )
        assert resp.status_code == 200

    def test_extract_actions_called_with_response(self, client, operator_headers):
        inc_id = _seed_incident(title="Action Test")
        ai_text = "Fix: [ACTION:restart:myhost:{}]"
        mock_llm = _make_async_mock_llm(ai_text)
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm), \
             patch("server.routers.intelligence._build_ai_context", return_value="ctx"), \
             patch(
                 "server.llm.extract_actions",
                 return_value=[{"cmd": "restart", "host": "myhost"}],
             ) as mock_extract:
            resp = client.post(
                f"/api/ai/summarize-incident/{inc_id}", headers=operator_headers
            )
        assert resp.status_code == 200
        mock_extract.assert_called_once_with(ai_text)
        assert resp.json()["actions"] == [{"cmd": "restart", "host": "myhost"}]


# ===========================================================================
# POST /api/ai/test
# ===========================================================================

class TestAiTest:
    """POST /api/ai/test — admin required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/ai/test")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/ai/test", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/ai/test", headers=operator_headers)
        assert resp.status_code == 403

    def test_llm_not_configured_returns_503(self, client, admin_headers):
        with patch("server.routers.intelligence._get_llm_client", return_value=None):
            resp = client.post("/api/ai/test", headers=admin_headers)
        assert resp.status_code == 503

    def test_admin_gets_ok_response(self, client, admin_headers):
        mock_llm = _make_async_mock_llm("  NOBA AI connection successful.  ")
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm):
            resp = client.post("/api/ai/test", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "NOBA AI connection successful" in data["response"]

    def test_llm_exception_returns_502(self, client, admin_headers):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=ConnectionError("timeout"))
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm):
            resp = client.post("/api/ai/test", headers=admin_headers)
        assert resp.status_code == 502

    def test_response_is_stripped(self, client, admin_headers):
        mock_llm = _make_async_mock_llm("   trimmed response   ")
        with patch("server.routers.intelligence._get_llm_client", return_value=mock_llm):
            resp = client.post("/api/ai/test", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["response"] == "trimmed response"
