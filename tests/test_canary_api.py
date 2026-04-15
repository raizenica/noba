# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for canary rollout and validation API endpoints."""
from __future__ import annotations


class TestDryRunAPI:
    def test_dry_run_no_auth(self, client):
        r = client.post("/api/healing/dry-run", json={
            "event": {"source": "test", "target": "plex", "condition": "status == down"},
        })
        assert r.status_code == 401

    def test_dry_run_returns_simulation(self, client, admin_headers):
        r = client.post("/api/healing/dry-run", json={
            "event": {
                "source": "test", "rule_id": "test-rule",
                "condition": "cpu > 95", "target": "host1",
                "severity": "warning", "metrics": {"cpu_percent": 97},
            },
        }, headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert "would_correlate" in data
        assert "dependency_analysis" in data


class TestChaosAPI:
    def test_list_scenarios_no_auth(self, client):
        r = client.get("/api/healing/chaos/scenarios")
        assert r.status_code == 401

    def test_list_scenarios_returns_list(self, client, admin_headers):
        r = client.get("/api/healing/chaos/scenarios", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 5

    def test_run_scenario_dry_run(self, client, admin_headers):
        r = client.post("/api/healing/chaos/run", json={
            "scenario": "container_crash_recovery",
            "dry_run": True,
        }, headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert data.get("dry_run") is True

    def test_run_unknown_scenario(self, client, admin_headers):
        r = client.post("/api/healing/chaos/run", json={
            "scenario": "nonexistent",
            "dry_run": True,
        }, headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "error"


class TestHealthAPI:
    def test_health_no_auth(self, client):
        r = client.get("/api/healing/health")
        assert r.status_code == 401

    def test_health_returns_summary(self, client, admin_headers):
        r = client.get("/api/healing/health", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
