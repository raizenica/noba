# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing.capabilities: manifest model and dispatch resolution."""
from __future__ import annotations


class TestCapabilityManifest:
    def test_from_dict_basic(self):
        from server.healing.capabilities import CapabilityManifest
        data = {
            "os": "linux", "distro": "ubuntu", "distro_version": "24.04",
            "kernel": "6.8.0", "init_system": "systemd",
            "is_wsl": False, "is_container": False,
            "capabilities": {
                "docker": {"available": True, "version": "27.1"},
                "systemctl": {"available": True},
                "apt": {"available": True},
            },
        }
        m = CapabilityManifest.from_dict(data)
        assert m.os == "linux"
        assert m.distro == "ubuntu"
        assert m.init_system == "systemd"
        assert m.has_capability("docker")
        assert m.has_capability("systemctl")
        assert not m.has_capability("podman")

    def test_has_capability_degraded(self):
        from server.healing.capabilities import CapabilityManifest
        data = {
            "os": "linux", "distro": "ubuntu", "distro_version": "24.04",
            "kernel": "6.8.0", "init_system": "systemd",
            "is_wsl": False, "is_container": False,
            "capabilities": {
                "docker": {"available": True, "version": "27.1", "state": "degraded"},
            },
        }
        m = CapabilityManifest.from_dict(data)
        assert not m.has_capability("docker")
        assert m.has_capability("docker", allow_degraded=True)

    def test_empty_capabilities(self):
        from server.healing.capabilities import CapabilityManifest
        data = {
            "os": "windows", "distro": "windows", "distro_version": "11",
            "kernel": "10.0", "init_system": "windows_scm",
            "is_wsl": False, "is_container": False,
            "capabilities": {},
        }
        m = CapabilityManifest.from_dict(data)
        assert not m.has_capability("docker")

    def test_to_dict_roundtrip(self):
        from server.healing.capabilities import CapabilityManifest
        data = {
            "os": "linux", "distro": "ubuntu", "distro_version": "24.04",
            "kernel": "6.8.0", "init_system": "systemd",
            "is_wsl": False, "is_container": False,
            "capabilities": {"docker": {"available": True}},
        }
        m = CapabilityManifest.from_dict(data)
        roundtrip = m.to_dict()
        assert roundtrip["os"] == "linux"
        assert roundtrip["capabilities"]["docker"]["available"] is True


class TestResolveHandler:
    def test_first_matching_handler_wins(self):
        from server.healing.capabilities import CapabilityManifest, resolve_handler
        manifest = CapabilityManifest.from_dict({
            "os": "linux", "distro": "ubuntu", "distro_version": "24.04",
            "kernel": "6.8.0", "init_system": "systemd",
            "is_wsl": False, "is_container": False,
            "capabilities": {"systemctl": {"available": True}},
        })
        handlers = [
            {"requires": "systemctl", "cmd": "systemctl restart {service}"},
            {"requires": "rc-service", "cmd": "rc-service {service} restart"},
        ]
        result = resolve_handler(handlers, manifest)
        assert result is not None
        assert "systemctl" in result["cmd"]

    def test_fallback_to_second(self):
        from server.healing.capabilities import CapabilityManifest, resolve_handler
        manifest = CapabilityManifest.from_dict({
            "os": "linux", "distro": "alpine", "distro_version": "3.19",
            "kernel": "6.6.0", "init_system": "openrc",
            "is_wsl": False, "is_container": False,
            "capabilities": {"rc-service": {"available": True}},
        })
        handlers = [
            {"requires": "systemctl", "cmd": "systemctl restart {service}"},
            {"requires": "rc-service", "cmd": "rc-service {service} restart"},
        ]
        result = resolve_handler(handlers, manifest)
        assert result is not None
        assert "rc-service" in result["cmd"]

    def test_no_match_returns_none(self):
        from server.healing.capabilities import CapabilityManifest, resolve_handler
        manifest = CapabilityManifest.from_dict({
            "os": "linux", "distro": "custom", "distro_version": "1.0",
            "kernel": "5.0", "init_system": "runit",
            "is_wsl": False, "is_container": False,
            "capabilities": {},
        })
        handlers = [
            {"requires": "systemctl", "cmd": "systemctl restart {service}"},
            {"requires": "powershell", "cmd": "Restart-Service {service}"},
        ]
        result = resolve_handler(handlers, manifest)
        assert result is None

    def test_windows_handler_selected(self):
        from server.healing.capabilities import CapabilityManifest, resolve_handler
        manifest = CapabilityManifest.from_dict({
            "os": "windows", "distro": "windows", "distro_version": "11",
            "kernel": "10.0", "init_system": "windows_scm",
            "is_wsl": False, "is_container": False,
            "capabilities": {"powershell": {"available": True}},
        })
        handlers = [
            {"requires": "systemctl", "cmd": "systemctl restart {service}"},
            {"requires": "powershell", "cmd": "Restart-Service {service}"},
        ]
        result = resolve_handler(handlers, manifest)
        assert "Restart-Service" in result["cmd"]
