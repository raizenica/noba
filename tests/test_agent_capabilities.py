"""Tests for agent capability probing and manifest storage."""
from __future__ import annotations

import sys
import os


class TestProbeCapabilities:
    """Test the agent-side probe_capabilities function."""

    def test_probe_returns_manifest_dict(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "share", "noba-agent"))
        from commands import probe_capabilities
        result = probe_capabilities()
        assert isinstance(result, dict)
        assert "os" in result
        assert "capabilities" in result
        assert isinstance(result["capabilities"], dict)
        assert "init_system" in result
        assert "is_wsl" in result
        assert "is_container" in result
        assert "distro" in result

    def test_probe_detects_available_tools(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "share", "noba-agent"))
        from commands import probe_capabilities
        result = probe_capabilities()
        caps = result["capabilities"]
        assert isinstance(caps, dict)
        for tool_name, tool_info in caps.items():
            assert "available" in tool_info, f"{tool_name} missing 'available'"


class TestManifestStorageInReport:
    """Test that the server stores capability manifests from agent reports."""

    def test_manifest_stored_from_report(self):
        from unittest.mock import patch

        from fastapi.testclient import TestClient
        from server.app import app

        client = TestClient(app)
        headers = {"X-Agent-Key": "test-agent-key-12345"}

        body = {
            "hostname": "test-cap-host",
            "cpuPercent": 10,
            "memPercent": 20,
            "_capabilities": {
                "os": "linux", "distro": "ubuntu", "distro_version": "24.04",
                "kernel": "6.8.0", "init_system": "systemd",
                "is_wsl": False, "is_container": False,
                "capabilities": {"docker": {"available": True}},
            },
        }
        with patch(
            "server.routers.agents.read_yaml_settings",
            return_value={"agentKeys": "test-agent-key-12345"},
        ):
            r = client.post("/api/agent/report", json=body, headers=headers)
        assert r.status_code == 200
