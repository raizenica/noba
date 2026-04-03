# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing.preflight: pre-flight validation before action execution."""
from __future__ import annotations



class TestPreFlightCheck:
    def _make_manifest(self, caps=None):
        from server.healing.capabilities import CapabilityManifest
        return CapabilityManifest.from_dict({
            "os": "linux", "distro": "ubuntu", "distro_version": "24.04",
            "kernel": "6.8.0", "init_system": "systemd",
            "is_wsl": False, "is_container": False,
            "capabilities": caps if caps is not None else {"systemctl": {"available": True}},
        })

    def test_passes_when_all_ok(self):
        from server.healing.preflight import run_preflight
        manifest = self._make_manifest({"systemctl": {"available": True}})
        handlers = [{"requires": "systemctl", "cmd": "systemctl restart {service}"}]
        result = run_preflight(
            action_type="service_restart",
            handlers=handlers,
            manifest=manifest,
            target="nginx",
        )
        assert result.passed
        assert result.resolved_handler is not None

    def test_fails_no_capability_match(self):
        from server.healing.preflight import run_preflight
        manifest = self._make_manifest({})
        handlers = [{"requires": "systemctl", "cmd": "systemctl restart {service}"}]
        result = run_preflight(
            action_type="service_restart",
            handlers=handlers,
            manifest=manifest,
            target="nginx",
        )
        assert not result.passed
        assert "no_capable_handler" in result.failure_reason

    def test_fails_degraded_capability(self):
        from server.healing.preflight import run_preflight
        manifest = self._make_manifest(
            {"systemctl": {"available": True, "state": "degraded"}},
        )
        handlers = [{"requires": "systemctl", "cmd": "systemctl restart {service}"}]
        result = run_preflight(
            action_type="service_restart",
            handlers=handlers,
            manifest=manifest,
            target="nginx",
        )
        assert not result.passed
        assert "no_capable_handler" in result.failure_reason

    def test_no_manifest_fails(self):
        from server.healing.preflight import run_preflight
        result = run_preflight(
            action_type="service_restart",
            handlers=[{"requires": "systemctl", "cmd": "..."}],
            manifest=None,
            target="nginx",
        )
        assert not result.passed
        assert "no_manifest" in result.failure_reason

    def test_maintenance_window_blocks(self):
        from server.healing.preflight import run_preflight
        manifest = self._make_manifest({"systemctl": {"available": True}})
        handlers = [{"requires": "systemctl", "cmd": "..."}]
        result = run_preflight(
            action_type="service_restart",
            handlers=handlers,
            manifest=manifest,
            target="nginx",
            in_maintenance=True,
        )
        assert not result.passed
        assert "maintenance" in result.failure_reason

    def test_result_contains_all_checks(self):
        from server.healing.preflight import run_preflight
        manifest = self._make_manifest({"systemctl": {"available": True}})
        handlers = [{"requires": "systemctl", "cmd": "..."}]
        result = run_preflight(
            action_type="service_restart",
            handlers=handlers,
            manifest=manifest,
            target="nginx",
        )
        assert isinstance(result.checks, dict)
        assert "capability_match" in result.checks
