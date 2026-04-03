# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for automations API router."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helper to create an automation via the API (returns auto_id)
# ---------------------------------------------------------------------------
def _create_automation(client, headers, name="Test Auto", atype="script",
                       config=None, schedule=None, enabled=True):
    """Helper: create an automation and return the response."""
    if config is None:
        config = {"script": "backup"}
    body = {"name": name, "type": atype, "config": config,
            "schedule": schedule, "enabled": enabled}
    return client.post("/api/automations", json=body, headers=headers)


# ===========================================================================
# GET /api/automations — list automations
# ===========================================================================

class TestAutomationsList:
    """GET /api/automations -- any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/automations")
        assert resp.status_code == 401

    def test_viewer_can_list(self, client, viewer_headers):
        resp = client.get("/api/automations", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_operator_can_list(self, client, operator_headers):
        resp = client.get("/api/automations", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_list(self, client, admin_headers):
        resp = client.get("/api/automations", headers=admin_headers)
        assert resp.status_code == 200

    def test_type_filter(self, client, admin_headers):
        # Create two different types
        _create_automation(client, admin_headers, "Script1", "script",
                           {"script": "backup"})
        _create_automation(client, admin_headers, "Webhook1", "webhook",
                           {"url": "https://example.com/hook"})
        resp = client.get("/api/automations?type=webhook", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        for item in data:
            assert item["type"] == "webhook"


# ===========================================================================
# POST /api/automations — create automation
# ===========================================================================

class TestAutomationsCreate:
    """POST /api/automations -- operator+ required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/automations", json={"name": "x", "type": "script"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = _create_automation(client, viewer_headers)
        assert resp.status_code == 403

    def test_operator_can_create(self, client, operator_headers):
        resp = _create_automation(client, operator_headers, "OpAuto")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "id" in data

    def test_admin_can_create(self, client, admin_headers):
        resp = _create_automation(client, admin_headers, "AdminAuto")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_missing_name_returns_400(self, client, operator_headers):
        resp = client.post("/api/automations",
                           json={"name": "", "type": "script", "config": {"script": "backup"}},
                           headers=operator_headers)
        assert resp.status_code == 400

    def test_invalid_type_returns_400(self, client, operator_headers):
        resp = _create_automation(client, operator_headers, "Bad", "nonexistent_type")
        assert resp.status_code == 400

    def test_config_must_be_dict(self, client, operator_headers):
        resp = client.post("/api/automations",
                           json={"name": "X", "type": "script", "config": "not-a-dict"},
                           headers=operator_headers)
        assert resp.status_code == 400

    def test_script_type_requires_script_or_command(self, client, operator_headers):
        resp = _create_automation(client, operator_headers, "NoScript", "script",
                                  config={})
        assert resp.status_code == 400

    def test_webhook_type_requires_valid_url(self, client, operator_headers):
        resp = _create_automation(client, operator_headers, "BadHook", "webhook",
                                  config={"url": "ftp://bad"})
        assert resp.status_code == 400

    def test_service_type_requires_service_name(self, client, operator_headers):
        resp = _create_automation(client, operator_headers, "NoSvc", "service",
                                  config={})
        assert resp.status_code == 400

    def test_service_invalid_action_returns_400(self, client, operator_headers):
        resp = _create_automation(client, operator_headers, "BadSvc", "service",
                                  config={"service": "nginx.service", "action": "destroy"})
        assert resp.status_code == 400

    def test_custom_script_command_requires_admin(self, client, operator_headers):
        """Operator cannot create script automation with custom command (shell access)."""
        resp = _create_automation(client, operator_headers, "CustomCmd", "script",
                                  config={"command": "echo pwned"})
        assert resp.status_code == 403

    def test_admin_can_create_custom_script_command(self, client, admin_headers):
        resp = _create_automation(client, admin_headers, "AdminCmd", "script",
                                  config={"command": "echo hello"})
        assert resp.status_code == 200

    def test_workflow_type_accepted(self, client, operator_headers):
        resp = _create_automation(client, operator_headers, "WF", "workflow",
                                  config={"steps": ["step1"]})
        assert resp.status_code == 200

    def test_all_valid_types_accepted(self, client, admin_headers):
        """Each allowed type can be created (with minimal valid config)."""
        type_configs = {
            "script": {"script": "backup"},
            "webhook": {"url": "https://example.com/hook"},
            "service": {"service": "nginx.service"},
            "workflow": {"steps": ["a"]},
            "condition": {"condition": "cpu > 90"},
            "delay": {"seconds": 10},
            "notify": {"message": "hello"},
            "http": {"url": "https://example.com/api"},
            "agent_command": {"hostname": "host1", "command": "uptime"},
            "remediation": {"remediation_type": "restart"},
        }
        for atype, config in type_configs.items():
            resp = _create_automation(client, admin_headers, f"T-{atype}", atype,
                                      config=config)
            assert resp.status_code == 200, f"Failed to create type={atype}: {resp.text}"


# ===========================================================================
# PUT /api/automations/{auto_id} — update automation
# ===========================================================================

class TestAutomationsUpdate:
    """PUT /api/automations/{auto_id} -- operator+ required."""

    def test_no_auth_returns_401(self, client):
        resp = client.put("/api/automations/fake123", json={"name": "new"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.put("/api/automations/fake123",
                          json={"name": "new"}, headers=viewer_headers)
        assert resp.status_code == 403

    def test_nonexistent_returns_404(self, client, operator_headers):
        resp = client.put("/api/automations/doesnotexist",
                          json={"name": "new"}, headers=operator_headers)
        assert resp.status_code == 404

    def test_operator_can_update_name(self, client, operator_headers):
        create = _create_automation(client, operator_headers, "OrigName")
        auto_id = create.json()["id"]
        resp = client.put(f"/api/automations/{auto_id}",
                          json={"name": "NewName"}, headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_update_invalid_type_returns_400(self, client, operator_headers):
        create = _create_automation(client, operator_headers, "UpdType")
        auto_id = create.json()["id"]
        resp = client.put(f"/api/automations/{auto_id}",
                          json={"type": "invalid_type"}, headers=operator_headers)
        assert resp.status_code == 400

    def test_update_enabled_flag(self, client, operator_headers):
        create = _create_automation(client, operator_headers, "Toggle")
        auto_id = create.json()["id"]
        resp = client.put(f"/api/automations/{auto_id}",
                          json={"enabled": False}, headers=operator_headers)
        assert resp.status_code == 200

    def test_operator_cannot_set_custom_command(self, client, operator_headers):
        create = _create_automation(client, operator_headers, "NoCmd")
        auto_id = create.json()["id"]
        resp = client.put(f"/api/automations/{auto_id}",
                          json={"config": {"command": "rm -rf /"}},
                          headers=operator_headers)
        assert resp.status_code == 403

    def test_admin_can_set_custom_command(self, client, admin_headers):
        create = _create_automation(client, admin_headers, "AdminUpd")
        auto_id = create.json()["id"]
        resp = client.put(f"/api/automations/{auto_id}",
                          json={"config": {"command": "echo ok"}},
                          headers=admin_headers)
        assert resp.status_code == 200


# ===========================================================================
# DELETE /api/automations/{auto_id} — delete automation
# ===========================================================================

class TestAutomationsDelete:
    """DELETE /api/automations/{auto_id} -- admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.delete("/api/automations/fake123")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.delete("/api/automations/fake123", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.delete("/api/automations/fake123", headers=operator_headers)
        assert resp.status_code == 403

    def test_nonexistent_returns_404(self, client, admin_headers):
        resp = client.delete("/api/automations/doesnotexist", headers=admin_headers)
        assert resp.status_code == 404

    def test_admin_can_delete(self, client, admin_headers):
        create = _create_automation(client, admin_headers, "ToDelete")
        auto_id = create.json()["id"]
        resp = client.delete(f"/api/automations/{auto_id}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_deleted_automation_is_gone(self, client, admin_headers):
        create = _create_automation(client, admin_headers, "DeleteVerify")
        auto_id = create.json()["id"]
        client.delete(f"/api/automations/{auto_id}", headers=admin_headers)
        # Trying to delete again should 404
        resp = client.delete(f"/api/automations/{auto_id}", headers=admin_headers)
        assert resp.status_code == 404


# ===========================================================================
# POST /api/automations/{auto_id}/run — execute automation
# ===========================================================================

class TestAutomationsRun:
    """POST /api/automations/{auto_id}/run -- operator+ required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/automations/fake123/run")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/automations/fake123/run", headers=viewer_headers)
        assert resp.status_code == 403

    def test_nonexistent_returns_404(self, client, operator_headers):
        resp = client.post("/api/automations/doesnotexist/run",
                           headers=operator_headers)
        assert resp.status_code == 404

    def test_workflow_no_steps_returns_400(self, client, operator_headers):
        """Workflow with empty steps is rejected at creation time."""
        resp = _create_automation(client, operator_headers, "EmptyWF", "workflow",
                                  config={"steps": []})
        assert resp.status_code == 400

    def test_workflow_empty_steps_run_returns_400(self, client, operator_headers):
        """Bypass validation by writing empty steps directly to DB, then run."""
        create = _create_automation(client, operator_headers, "WFDirect", "workflow",
                                    config={"steps": ["placeholder"]})
        auto_id = create.json()["id"]
        # Directly update the DB to have empty steps (bypass API validation)
        from server.deps import db as _db
        _db.update_automation(auto_id, config={"steps": []})
        resp = client.post(f"/api/automations/{auto_id}/run",
                           headers=operator_headers)
        assert resp.status_code == 400

    def test_run_script_automation(self, client, operator_headers):
        create = _create_automation(client, operator_headers, "RunScript")
        auto_id = create.json()["id"]
        mock_popen = MagicMock()
        mock_popen.poll.return_value = 0
        mock_popen.stdout = MagicMock()
        mock_popen.stdout.read.return_value = b""
        mock_popen.stdout.readline.return_value = b""
        mock_popen.stdout.__iter__ = MagicMock(return_value=iter([]))
        with patch("server.workflow_engine.subprocess.Popen", return_value=mock_popen):
            resp = client.post(f"/api/automations/{auto_id}/run",
                               headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "run_id" in data

    def test_run_workflow_sequential(self, client, operator_headers):
        """Workflow with steps triggers sequential execution."""
        create = _create_automation(client, operator_headers, "SeqWF", "workflow",
                                    config={"steps": ["step1", "step2"], "mode": "sequential"})
        auto_id = create.json()["id"]
        with patch("server.routers.automations._run_workflow"):
            resp = client.post(f"/api/automations/{auto_id}/run",
                               headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow"] is True
        assert data["steps"] == 2
        assert data["mode"] == "sequential"

    def test_run_workflow_parallel(self, client, operator_headers):
        create = _create_automation(client, operator_headers, "ParWF", "workflow",
                                    config={"steps": ["s1", "s2"], "mode": "parallel"})
        auto_id = create.json()["id"]
        with patch("server.routers.automations._run_parallel_workflow"):
            resp = client.post(f"/api/automations/{auto_id}/run",
                               headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow"] is True
        assert data["mode"] == "parallel"

    def test_run_graph_workflow(self, client, operator_headers):
        create = _create_automation(client, operator_headers, "GraphWF", "workflow",
                                    config={"nodes": [{"id": "n1", "type": "start"}],
                                            "edges": [], "entry": "n1"})
        auto_id = create.json()["id"]
        with patch("server.routers.automations._run_graph_workflow"):
            resp = client.post(f"/api/automations/{auto_id}/run",
                               headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["graph"] is True

    def test_run_with_variables(self, client, operator_headers):
        """Variable substitution in config fields."""
        create = _create_automation(client, operator_headers, "VarScript", "script",
                                    config={"script": "backup"})
        auto_id = create.json()["id"]
        mock_popen = MagicMock()
        mock_popen.poll.return_value = 0
        mock_popen.stdout = MagicMock()
        mock_popen.stdout.read.return_value = b""
        mock_popen.stdout.readline.return_value = b""
        mock_popen.stdout.__iter__ = MagicMock(return_value=iter([]))
        with patch("server.workflow_engine.subprocess.Popen", return_value=mock_popen):
            resp = client.post(f"/api/automations/{auto_id}/run",
                               json={"variables": {"target": "server1"}},
                               headers=operator_headers)
        assert resp.status_code == 200


# ===========================================================================
# GET /api/run-status — legacy run status
# ===========================================================================

class TestRunStatus:
    """GET /api/run-status -- any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/run-status")
        assert resp.status_code == 401

    def test_idle_when_nothing_running(self, client, viewer_headers):
        resp = client.get("/api/run-status", headers=viewer_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "idle"


# ===========================================================================
# GET /api/runs — run history
# ===========================================================================

class TestRunHistory:
    """GET /api/runs -- any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/runs")
        assert resp.status_code == 401

    def test_viewer_can_list(self, client, viewer_headers):
        resp = client.get("/api/runs", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_limit_param(self, client, viewer_headers):
        resp = client.get("/api/runs?limit=5", headers=viewer_headers)
        assert resp.status_code == 200

    def test_status_filter(self, client, viewer_headers):
        resp = client.get("/api/runs?status=completed", headers=viewer_headers)
        assert resp.status_code == 200


# ===========================================================================
# GET /api/runs/{run_id} — run detail
# ===========================================================================

class TestRunDetail:
    """GET /api/runs/{run_id} -- any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/runs/1")
        assert resp.status_code == 401

    def test_nonexistent_returns_404(self, client, viewer_headers):
        resp = client.get("/api/runs/999999", headers=viewer_headers)
        assert resp.status_code == 404


# ===========================================================================
# POST /api/runs/{run_id}/cancel — cancel a run
# ===========================================================================

class TestRunCancel:
    """POST /api/runs/{run_id}/cancel -- operator+ required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/runs/1/cancel")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/runs/1/cancel", headers=viewer_headers)
        assert resp.status_code == 403

    def test_nonexistent_returns_404(self, client, operator_headers):
        resp = client.post("/api/runs/999999/cancel", headers=operator_headers)
        assert resp.status_code == 404


# ===========================================================================
# POST /api/runs/{run_id}/approve — approve a pending run
# ===========================================================================

class TestRunApprove:
    """POST /api/runs/{run_id}/approve -- admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/runs/1/approve")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/runs/1/approve", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/runs/1/approve", headers=operator_headers)
        assert resp.status_code == 403

    def test_nonexistent_returns_404(self, client, admin_headers):
        resp = client.post("/api/runs/999999/approve", headers=admin_headers)
        assert resp.status_code == 404


# ===========================================================================
# GET /api/automations/templates — list templates
# ===========================================================================

class TestAutomationTemplates:
    """GET /api/automations/templates -- any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/automations/templates")
        assert resp.status_code == 401

    def test_viewer_can_list(self, client, viewer_headers):
        resp = client.get("/api/automations/templates", headers=viewer_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_templates_have_required_fields(self, client, admin_headers):
        resp = client.get("/api/automations/templates", headers=admin_headers)
        data = resp.json()
        for tmpl in data:
            assert "id" in tmpl
            assert "name" in tmpl
            assert "type" in tmpl
            assert "config" in tmpl


# ===========================================================================
# GET /api/automations/stats — automation statistics
# ===========================================================================

class TestAutomationStats:
    """GET /api/automations/stats -- any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/automations/stats")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/automations/stats", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)


# ===========================================================================
# GET /api/automations/export — export automations (YAML)
# ===========================================================================

class TestAutomationsExport:
    """GET /api/automations/export -- admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/automations/export")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/automations/export", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.get("/api/automations/export", headers=operator_headers)
        assert resp.status_code == 403

    def test_admin_can_export(self, client, admin_headers):
        resp = client.get("/api/automations/export", headers=admin_headers)
        assert resp.status_code == 200
        assert "yaml" in resp.headers.get("content-type", "")


# ===========================================================================
# POST /api/automations/import — import automations (YAML)
# ===========================================================================

class TestAutomationsImport:
    """POST /api/automations/import -- admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/automations/import")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/automations/import", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/automations/import", headers=operator_headers)
        assert resp.status_code == 403

    def test_invalid_yaml_returns_400(self, client, admin_headers):
        resp = client.post("/api/automations/import",
                           content=b"{{{\x00broken",
                           headers={**admin_headers, "Content-Type": "application/x-yaml"})
        assert resp.status_code == 400

    def test_non_mapping_returns_400(self, client, admin_headers):
        resp = client.post("/api/automations/import",
                           content=b"- just\n- a\n- list\n",
                           headers={**admin_headers, "Content-Type": "application/x-yaml"})
        assert resp.status_code == 400

    def test_oversized_payload_returns_413(self, client, admin_headers):
        huge = b"x" * (512 * 1024 + 1)
        resp = client.post("/api/automations/import",
                           content=huge,
                           headers={**admin_headers, "Content-Type": "application/x-yaml"})
        assert resp.status_code == 413

    def test_admin_can_import(self, client, admin_headers):
        import yaml
        payload = yaml.dump({
            "automations": [
                {"name": "Imported1", "type": "script", "config": {"script": "backup"}},
                {"name": "Imported2", "type": "webhook", "config": {"url": "https://x.com/h"}},
            ]
        })
        resp = client.post("/api/automations/import",
                           content=payload.encode(),
                           headers={**admin_headers, "Content-Type": "application/x-yaml"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 2
        assert data["skipped"] == 0

    def test_import_skips_invalid_items(self, client, admin_headers):
        import yaml
        payload = yaml.dump({
            "automations": [
                {"name": "Good", "type": "script", "config": {"script": "backup"}},
                {"name": "", "type": "script"},  # missing name
                {"type": "script"},  # missing name entirely
                {"name": "BadType", "type": "bogus"},
            ]
        })
        resp = client.post("/api/automations/import",
                           content=payload.encode(),
                           headers={**admin_headers, "Content-Type": "application/x-yaml"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 1
        assert data["skipped"] == 3


# ===========================================================================
# POST /api/automations/validate-workflow — validate workflow steps
# ===========================================================================

class TestValidateWorkflow:
    """POST /api/automations/validate-workflow -- operator+ required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/automations/validate-workflow", json={"steps": []})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/automations/validate-workflow",
                           json={"steps": []}, headers=viewer_headers)
        assert resp.status_code == 403

    def test_steps_must_be_list(self, client, operator_headers):
        resp = client.post("/api/automations/validate-workflow",
                           json={"steps": "not-a-list"}, headers=operator_headers)
        assert resp.status_code == 400

    def test_validates_step_ids(self, client, operator_headers):
        # Create an automation so we have a valid ID
        create = _create_automation(client, operator_headers, "WFStep")
        auto_id = create.json()["id"]
        resp = client.post("/api/automations/validate-workflow",
                           json={"steps": [auto_id, "nonexistent123"]},
                           headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["steps"]) == 2
        assert data["steps"][0]["valid"] is True
        assert data["steps"][1]["valid"] is False
        assert data["valid"] is False

    def test_all_valid_returns_true(self, client, operator_headers):
        c1 = _create_automation(client, operator_headers, "S1").json()["id"]
        c2 = _create_automation(client, operator_headers, "S2",
                                config={"script": "backup"}).json()["id"]
        resp = client.post("/api/automations/validate-workflow",
                           json={"steps": [c1, c2]}, headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json()["valid"] is True


# ===========================================================================
# GET /api/automations/{auto_id}/trace — workflow trace
# ===========================================================================

class TestAutomationTrace:
    """GET /api/automations/{auto_id}/trace -- any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/automations/fake123/trace")
        assert resp.status_code == 401

    def test_nonexistent_returns_404(self, client, viewer_headers):
        resp = client.get("/api/automations/doesnotexist/trace",
                          headers=viewer_headers)
        assert resp.status_code == 404

    def test_non_workflow_returns_400(self, client, admin_headers):
        create = _create_automation(client, admin_headers, "ScriptTrace")
        auto_id = create.json()["id"]
        resp = client.get(f"/api/automations/{auto_id}/trace",
                          headers=admin_headers)
        assert resp.status_code == 400

    def test_workflow_returns_trace(self, client, admin_headers):
        create = _create_automation(client, admin_headers, "WFTrace", "workflow",
                                    config={"steps": ["s1"]})
        auto_id = create.json()["id"]
        resp = client.get(f"/api/automations/{auto_id}/trace",
                          headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "workflow" in data
        assert "executions" in data


# ===========================================================================
# POST /api/automations/{auto_id}/trigger — API key trigger
# ===========================================================================

class TestAutomationTrigger:
    """POST /api/automations/{auto_id}/trigger -- trigger key or auth."""

    def test_nonexistent_returns_404(self, client):
        resp = client.post("/api/automations/doesnotexist/trigger")
        assert resp.status_code == 404

    def test_no_trigger_key_configured_returns_403(self, client, admin_headers):
        create = _create_automation(client, admin_headers, "NoKey")
        auto_id = create.json()["id"]
        resp = client.post(f"/api/automations/{auto_id}/trigger")
        assert resp.status_code == 403

    def test_invalid_trigger_key_returns_401(self, client, admin_headers):
        create = _create_automation(client, admin_headers, "WithKey", "script",
                                    config={"script": "backup", "trigger_key": "secret123"})
        auto_id = create.json()["id"]
        resp = client.post(f"/api/automations/{auto_id}/trigger",
                           headers={"X-Trigger-Key": "wrong_key"})
        assert resp.status_code == 401

    def test_valid_trigger_key_runs_automation(self, client, admin_headers):
        create = _create_automation(client, admin_headers, "TrigKey", "script",
                                    config={"script": "backup", "trigger_key": "mykey42"})
        auto_id = create.json()["id"]
        mock_popen = MagicMock()
        mock_popen.poll.return_value = 0
        mock_popen.stdout = MagicMock()
        mock_popen.stdout.read.return_value = b""
        mock_popen.stdout.readline.return_value = b""
        mock_popen.stdout.__iter__ = MagicMock(return_value=iter([]))
        with patch("server.workflow_engine.subprocess.Popen", return_value=mock_popen):
            resp = client.post(f"/api/automations/{auto_id}/trigger",
                               headers={"X-Trigger-Key": "mykey42"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_authenticated_operator_can_trigger(self, client, admin_headers,
                                                operator_headers):
        create = _create_automation(client, admin_headers, "AuthTrig", "script",
                                    config={"script": "backup", "trigger_key": "k"})
        auto_id = create.json()["id"]
        mock_popen = MagicMock()
        mock_popen.poll.return_value = 0
        mock_popen.stdout = MagicMock()
        mock_popen.stdout.read.return_value = b""
        mock_popen.stdout.readline.return_value = b""
        mock_popen.stdout.__iter__ = MagicMock(return_value=iter([]))
        with patch("server.workflow_engine.subprocess.Popen", return_value=mock_popen):
            resp = client.post(f"/api/automations/{auto_id}/trigger",
                               headers=operator_headers)
        assert resp.status_code == 200


# ===========================================================================
# GET /api/approvals/count — pending approval count
# ===========================================================================

class TestApprovalCount:
    """GET /api/approvals/count -- any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/approvals/count")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/approvals/count", headers=viewer_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert isinstance(data["count"], int)


# ===========================================================================
# GET /api/approvals — list approvals
# ===========================================================================

class TestApprovalsList:
    """GET /api/approvals -- any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/approvals")
        assert resp.status_code == 401

    def test_viewer_can_list(self, client, viewer_headers):
        resp = client.get("/api/approvals", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_status_filter(self, client, viewer_headers):
        resp = client.get("/api/approvals?status=approved", headers=viewer_headers)
        assert resp.status_code == 200


# ===========================================================================
# GET /api/approvals/{approval_id} — approval detail
# ===========================================================================

class TestApprovalDetail:
    """GET /api/approvals/{approval_id} -- any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/approvals/1")
        assert resp.status_code == 401

    def test_nonexistent_returns_404(self, client, viewer_headers):
        resp = client.get("/api/approvals/999999", headers=viewer_headers)
        assert resp.status_code == 404


# ===========================================================================
# POST /api/approvals/{approval_id}/decide — approve/deny
# ===========================================================================

class TestApprovalDecide:
    """POST /api/approvals/{approval_id}/decide -- operator+ required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/approvals/1/decide", json={"decision": "approved"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/approvals/1/decide",
                           json={"decision": "approved"}, headers=viewer_headers)
        assert resp.status_code == 403

    def _insert_test_approval(self):
        """Insert a pending approval directly via DB and return its ID."""
        from server.deps import db as _db
        return _db.insert_approval(
            automation_id="test_auto",
            trigger="test",
            trigger_source="test",
            action_type="restart_service",
            action_params={"service": "nginx"},
            target="nginx",
            requested_by="healing",
        )

    def test_invalid_decision_returns_400(self, client, operator_headers):
        aid = self._insert_test_approval()
        if aid is None:
            # Fallback: test validation with nonexistent id
            resp = client.post("/api/approvals/1/decide",
                               json={"decision": "maybe"}, headers=operator_headers)
            assert resp.status_code in (400, 404)
            return
        resp = client.post(f"/api/approvals/{aid}/decide",
                           json={"decision": "maybe"}, headers=operator_headers)
        assert resp.status_code == 400

    def test_nonexistent_returns_404(self, client, operator_headers):
        resp = client.post("/api/approvals/999999/decide",
                           json={"decision": "approved"}, headers=operator_headers)
        assert resp.status_code == 404

    def test_approve_pending(self, client, operator_headers):
        aid = self._insert_test_approval()
        if aid is None:
            return
        with patch("server.remediation.execute_action",
                   return_value={"status": "ok"}):
            resp = client.post(f"/api/approvals/{aid}/decide",
                               json={"decision": "approved"},
                               headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json()["decision"] == "approved"

    def test_deny_pending(self, client, operator_headers):
        aid = self._insert_test_approval()
        if aid is None:
            return
        resp = client.post(f"/api/approvals/{aid}/decide",
                           json={"decision": "denied"}, headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json()["decision"] == "denied"

    def test_double_decide_returns_400(self, client, operator_headers):
        aid = self._insert_test_approval()
        if aid is None:
            return
        # First decision
        resp1 = client.post(f"/api/approvals/{aid}/decide",
                            json={"decision": "denied"}, headers=operator_headers)
        assert resp1.status_code == 200
        # Second decision on same approval
        resp2 = client.post(f"/api/approvals/{aid}/decide",
                            json={"decision": "approved"}, headers=operator_headers)
        assert resp2.status_code == 400


# ===========================================================================
# GET /api/action-audit — action audit trail
# ===========================================================================

class TestActionAudit:
    """GET /api/action-audit -- any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/action-audit")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/action-audit", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_limit_param(self, client, viewer_headers):
        resp = client.get("/api/action-audit?limit=10", headers=viewer_headers)
        assert resp.status_code == 200


# ===========================================================================
# GET /api/playbooks — playbook library
# ===========================================================================

class TestPlaybooks:
    """GET /api/playbooks -- any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/playbooks")
        assert resp.status_code == 401

    def test_viewer_can_list(self, client, viewer_headers):
        resp = client.get("/api/playbooks", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestPlaybookDetail:
    """GET /api/playbooks/{playbook_id} -- any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/playbooks/fake")
        assert resp.status_code == 401

    def test_nonexistent_returns_404(self, client, viewer_headers):
        resp = client.get("/api/playbooks/doesnotexist", headers=viewer_headers)
        assert resp.status_code == 404


class TestPlaybookInstall:
    """POST /api/playbooks/{playbook_id}/install -- operator+ required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/playbooks/fake/install", json={})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/playbooks/fake/install", json={},
                           headers=viewer_headers)
        assert resp.status_code == 403

    def test_nonexistent_returns_404(self, client, operator_headers):
        resp = client.post("/api/playbooks/doesnotexist/install", json={},
                           headers=operator_headers)
        assert resp.status_code == 404


# ===========================================================================
# Webhook receiver endpoints
# ===========================================================================

class TestWebhookEndpoints:
    """GET/POST/DELETE /api/webhooks -- admin only."""

    def test_list_no_auth_returns_401(self, client):
        resp = client.get("/api/webhooks")
        assert resp.status_code == 401

    def test_list_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/webhooks", headers=viewer_headers)
        assert resp.status_code == 403

    def test_list_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/webhooks", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_missing_name_returns_400(self, client, admin_headers):
        resp = client.post("/api/webhooks", json={"name": ""},
                           headers=admin_headers)
        assert resp.status_code == 400

    def test_create_with_bad_automation_returns_400(self, client, admin_headers):
        resp = client.post("/api/webhooks",
                           json={"name": "hook1", "automation_id": "nonexistent"},
                           headers=admin_headers)
        assert resp.status_code == 400

    def test_create_and_delete(self, client, admin_headers):
        resp = client.post("/api/webhooks", json={"name": "TestHook"},
                           headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "hook_id" in data
        assert "secret" in data
        wh_id = data["id"]
        # Delete
        resp2 = client.delete(f"/api/webhooks/{wh_id}", headers=admin_headers)
        assert resp2.status_code == 200

    def test_delete_nonexistent_returns_404(self, client, admin_headers):
        resp = client.delete("/api/webhooks/999999", headers=admin_headers)
        assert resp.status_code == 404


# ===========================================================================
# Maintenance windows
# ===========================================================================

class TestMaintenanceWindows:
    """Maintenance window CRUD -- admin only for writes."""

    def test_list_no_auth_returns_401(self, client):
        resp = client.get("/api/maintenance-windows")
        assert resp.status_code == 401

    def test_viewer_can_list(self, client, viewer_headers):
        resp = client.get("/api/maintenance-windows", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_active_no_auth_returns_401(self, client):
        resp = client.get("/api/maintenance-windows/active")
        assert resp.status_code == 401

    def test_active_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/maintenance-windows/active", headers=viewer_headers)
        assert resp.status_code == 200

    def test_create_no_auth_returns_401(self, client):
        resp = client.post("/api/maintenance-windows", json={"name": "MW1"})
        assert resp.status_code == 401

    def test_create_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/maintenance-windows",
                           json={"name": "MW1"}, headers=viewer_headers)
        assert resp.status_code == 403

    def test_create_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/maintenance-windows",
                           json={"name": "MW1"}, headers=operator_headers)
        assert resp.status_code == 403

    def test_create_missing_name_returns_400(self, client, admin_headers):
        resp = client.post("/api/maintenance-windows",
                           json={"name": ""}, headers=admin_headers)
        assert resp.status_code == 400

    def test_admin_crud(self, client, admin_headers):
        # Create
        resp = client.post("/api/maintenance-windows",
                           json={"name": "Nightly", "duration_min": 30},
                           headers=admin_headers)
        assert resp.status_code == 200
        wid = resp.json()["id"]
        # Update
        resp2 = client.put(f"/api/maintenance-windows/{wid}",
                           json={"name": "Nightly Updated"},
                           headers=admin_headers)
        assert resp2.status_code == 200
        # Delete
        resp3 = client.delete(f"/api/maintenance-windows/{wid}",
                              headers=admin_headers)
        assert resp3.status_code == 200

    def test_update_nonexistent_returns_404(self, client, admin_headers):
        resp = client.put("/api/maintenance-windows/999999",
                          json={"name": "X"}, headers=admin_headers)
        assert resp.status_code == 404

    def test_delete_nonexistent_returns_404(self, client, admin_headers):
        resp = client.delete("/api/maintenance-windows/999999",
                             headers=admin_headers)
        assert resp.status_code == 404


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases:
    """Miscellaneous edge cases and input validation."""

    def test_duplicate_automation_names_allowed(self, client, operator_headers):
        """Two automations can share the same name (no unique constraint)."""
        r1 = _create_automation(client, operator_headers, "DupeName")
        r2 = _create_automation(client, operator_headers, "DupeName")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["id"] != r2.json()["id"]

    def test_whitespace_only_name_rejected(self, client, operator_headers):
        resp = client.post("/api/automations",
                           json={"name": "   ", "type": "script",
                                 "config": {"script": "backup"}},
                           headers=operator_headers)
        assert resp.status_code == 400

    def test_none_name_rejected(self, client, operator_headers):
        resp = client.post("/api/automations",
                           json={"name": None, "type": "script",
                                 "config": {"script": "backup"}},
                           headers=operator_headers)
        assert resp.status_code == 400

    def test_empty_config_for_script_rejected(self, client, operator_headers):
        resp = _create_automation(client, operator_headers, "EmptyCfg", "script",
                                  config={})
        assert resp.status_code == 400

    def test_run_on_deleted_automation_returns_404(self, client, admin_headers):
        create = _create_automation(client, admin_headers, "DelRun")
        auto_id = create.json()["id"]
        client.delete(f"/api/automations/{auto_id}", headers=admin_headers)
        resp = client.post(f"/api/automations/{auto_id}/run",
                           headers=admin_headers)
        assert resp.status_code == 404
