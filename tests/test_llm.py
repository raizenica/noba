# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the LLM module: client init, context builder, action extraction, and API endpoints."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from server.llm import LLMClient, build_ops_context, extract_actions


# ── Action pattern extraction ─────────────────────────────────────────────────

class TestExtractActions:
    def test_single_action(self):
        text = "Try restarting the service. [ACTION:restart_service:web01:nginx]"
        actions = extract_actions(text)
        assert len(actions) == 1
        assert actions[0]["cmd"] == "restart_service"
        assert actions[0]["hostname"] == "web01"
        assert actions[0]["params"] == "nginx"

    def test_multiple_actions(self):
        text = (
            "First [ACTION:exec:node1:uptime] and then "
            "[ACTION:restart_service:node2:docker]"
        )
        actions = extract_actions(text)
        assert len(actions) == 2
        assert actions[0]["cmd"] == "exec"
        assert actions[1]["hostname"] == "node2"

    def test_no_actions(self):
        assert extract_actions("No actions here") == []

    def test_action_without_params(self):
        text = "[ACTION:ping:server01]"
        actions = extract_actions(text)
        assert len(actions) == 1
        assert actions[0]["cmd"] == "ping"
        assert actions[0]["hostname"] == "server01"
        assert actions[0]["params"] == ""

    def test_action_with_spaces(self):
        text = "[ACTION: exec : host1 : ls -la ]"
        actions = extract_actions(text)
        assert len(actions) == 1
        assert actions[0]["cmd"] == "exec"
        assert actions[0]["hostname"] == "host1"
        assert actions[0]["params"] == "ls -la"


# ── LLMClient initialization ─────────────────────────────────────────────────

class TestLLMClientInit:
    def test_anthropic_defaults(self):
        client = LLMClient({"llmProvider": "anthropic", "llmEnabled": True, "llmApiKey": "sk-test"})
        assert client.provider == "anthropic"
        assert "claude" in client.model
        assert client.enabled is True
        assert client.api_key == "sk-test"
        assert client.max_tokens == 4096
        assert client.temperature == 0.3

    def test_openai_defaults(self):
        client = LLMClient({"llmProvider": "openai", "llmEnabled": True, "llmApiKey": "sk-test"})
        assert client.provider == "openai"
        assert client.model == "gpt-4o"

    def test_ollama_defaults(self):
        client = LLMClient({"llmProvider": "ollama", "llmEnabled": True})
        assert client.provider == "ollama"
        assert client.model == "llama3"
        assert client.api_key == ""

    def test_custom_provider(self):
        client = LLMClient({
            "llmProvider": "custom",
            "llmModel": "my-model",
            "llmBaseUrl": "http://localhost:8080",
            "llmMaxTokens": 2048,
            "llmTemperature": 0.7,
            "llmEnabled": True,
        })
        assert client.provider == "custom"
        assert client.model == "my-model"
        assert client.base_url == "http://localhost:8080"
        assert client.max_tokens == 2048
        assert client.temperature == 0.7

    def test_disabled_by_default(self):
        client = LLMClient({})
        assert client.enabled is False

    def test_empty_config_defaults(self):
        client = LLMClient({})
        assert client.provider == "anthropic"
        assert client.temperature == 0.3
        assert client.max_tokens == 4096


# ── Context builder ───────────────────────────────────────────────────────────

class TestBuildOpsContext:
    def _mock_db(self, alerts=None, incidents=None):
        db = MagicMock()
        db.get_alert_history.return_value = alerts or []
        db.get_incidents.return_value = incidents or []
        return db

    def test_basic_context_structure(self):
        db = self._mock_db()
        ctx = build_ops_context(lambda: {}, db, {})
        assert "NOBA Ops Assistant" in ctx
        assert "Fleet:" in ctx
        assert "Active Alerts:" in ctx
        assert "Recent Incidents" in ctx
        assert "[ACTION:" in ctx  # Instructions mention ACTION pattern

    def test_agents_listed(self):
        now = time.time()
        agents = {
            "web01": {"_received": now, "cpu_percent": 45, "mem_percent": 60, "disks": [{"percent": 70}]},
            "db01": {"_received": now - 300, "cpu_percent": 80, "mem_percent": 90, "disks": []},
        }
        db = self._mock_db()
        ctx = build_ops_context(lambda: {}, db, agents, agent_max_age=120)
        assert "web01" in ctx
        assert "1 agents online" in ctx
        assert "1 offline" in ctx
        assert "CPU 45.0%" in ctx  # average from online agent

    def test_alerts_included(self):
        alerts = [
            {"id": 1, "rule_id": "high_cpu", "severity": "danger", "message": "CPU > 90%", "resolved_at": None},
            {"id": 2, "rule_id": "disk_full", "severity": "warning", "message": "Disk 95%", "resolved_at": 12345},
        ]
        db = self._mock_db(alerts=alerts)
        ctx = build_ops_context(lambda: {}, db, {})
        assert "1" in ctx  # 1 unresolved
        assert "CPU > 90%" in ctx
        # Resolved alert should not appear in active
        assert "Disk 95%" not in ctx or "resolved" in ctx.lower()

    def test_incidents_included(self):
        incidents = [
            {"id": 1, "severity": "danger", "title": "Server down", "resolved_at": None},
        ]
        db = self._mock_db(incidents=incidents)
        ctx = build_ops_context(lambda: {}, db, {})
        assert "Server down" in ctx
        assert "open" in ctx


# ── LLMClient.chat (disabled) ─────────────────────────────────────────────────

class TestLLMClientChat:
    @pytest.mark.asyncio
    async def test_disabled_returns_message(self):
        client = LLMClient({"llmEnabled": False})
        result = await client.chat([{"role": "user", "content": "hello"}])
        assert "not enabled" in result.lower()

    @pytest.mark.asyncio
    async def test_anthropic_missing_key(self):
        client = LLMClient({"llmProvider": "anthropic", "llmEnabled": True, "llmApiKey": ""})
        result = await client.chat([{"role": "user", "content": "hello"}])
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_openai_missing_key(self):
        client = LLMClient({"llmProvider": "openai", "llmEnabled": True, "llmApiKey": ""})
        result = await client.chat([{"role": "user", "content": "hello"}])
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_custom_missing_url(self):
        client = LLMClient({"llmProvider": "custom", "llmEnabled": True, "llmBaseUrl": ""})
        result = await client.chat([{"role": "user", "content": "hello"}])
        assert "not configured" in result.lower()


# ── API endpoint tests (with mocked LLM) ─────────────────────────────────────

class TestAIEndpoints:
    """Test the FastAPI AI endpoints via TestClient with mocked LLM calls."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from server.app import app
        from fastapi.testclient import TestClient
        self.client = TestClient(app, raise_server_exceptions=False)
        # Login to get a token
        resp = self.client.post("/api/login", json={"username": "admin", "password": "Admin1234!"})
        if resp.status_code == 200:
            self.token = resp.json().get("token", "")
        else:
            self.token = ""
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_ai_status_returns_config(self):
        resp = self.client.get("/api/ai/status", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert "provider" in data
        assert "model" in data

    def test_ai_chat_503_when_not_configured(self):
        resp = self.client.post("/api/ai/chat",
                                json={"message": "hello"},
                                headers=self.headers)
        assert resp.status_code == 503

    def test_ai_analyze_alert_503_when_not_configured(self):
        resp = self.client.post("/api/ai/analyze-alert/1", headers=self.headers)
        assert resp.status_code == 503

    def test_ai_analyze_logs_503_when_not_configured(self):
        resp = self.client.post("/api/ai/analyze-logs",
                                json={"logs": "error log here"},
                                headers=self.headers)
        assert resp.status_code == 503

    def test_ai_summarize_incident_503_when_not_configured(self):
        resp = self.client.post("/api/ai/summarize-incident/1", headers=self.headers)
        assert resp.status_code == 503

    def test_ai_test_503_when_not_configured(self):
        resp = self.client.post("/api/ai/test", headers=self.headers)
        assert resp.status_code == 503

    def test_ai_chat_empty_message_rejected(self):
        """Even if LLM were configured, empty message returns 400 or 503."""
        resp = self.client.post("/api/ai/chat",
                                json={"message": ""},
                                headers=self.headers)
        # 503 because LLM not configured (checked first)
        assert resp.status_code in (400, 503)

    def test_ai_status_unauthenticated(self):
        resp = self.client.get("/api/ai/status")
        assert resp.status_code == 401
