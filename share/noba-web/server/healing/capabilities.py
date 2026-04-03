# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Capability manifest model and handler resolution.

Capability-based dispatch: never trust OS labels, verify what tools
are actually available on each host. Each action has fallback chains
that match against the capability manifest.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("noba")


@dataclass
class CapabilityManifest:
    """Agent capability manifest — what tools and subsystems are available."""

    os: str = "unknown"
    distro: str = "unknown"
    distro_version: str = ""
    kernel: str = ""
    init_system: str = "unknown"
    is_wsl: bool = False
    is_container: bool = False
    capabilities: dict = field(default_factory=dict)

    def has_capability(self, name: str, *, allow_degraded: bool = False) -> bool:
        """Check if a capability is available (not degraded unless allowed)."""
        cap = self.capabilities.get(name)
        if not cap or not isinstance(cap, dict):
            return False
        if not cap.get("available", False):
            return False
        if cap.get("state") == "degraded" and not allow_degraded:
            return False
        return True

    def mark_degraded(self, name: str) -> None:
        """Mark a capability as degraded after a pre-flight failure."""
        cap = self.capabilities.get(name)
        if cap and isinstance(cap, dict):
            cap["state"] = "degraded"

    @classmethod
    def from_dict(cls, data: dict) -> CapabilityManifest:
        return cls(
            os=data.get("os", "unknown"),
            distro=data.get("distro", "unknown"),
            distro_version=data.get("distro_version", ""),
            kernel=data.get("kernel", ""),
            init_system=data.get("init_system", "unknown"),
            is_wsl=data.get("is_wsl", False),
            is_container=data.get("is_container", False),
            capabilities=data.get("capabilities", {}),
        )

    def to_dict(self) -> dict:
        return {
            "os": self.os,
            "distro": self.distro,
            "distro_version": self.distro_version,
            "kernel": self.kernel,
            "init_system": self.init_system,
            "is_wsl": self.is_wsl,
            "is_container": self.is_container,
            "capabilities": self.capabilities,
        }


def resolve_handler(
    handlers: list[dict], manifest: CapabilityManifest,
) -> dict | None:
    """Find the first handler whose required capability is available.

    Each handler is {"requires": "tool_name", "cmd": "command template"}.
    Returns the first matching handler dict, or None if no match.
    """
    for handler in handlers:
        required = handler.get("requires", "")
        if manifest.has_capability(required):
            return handler
    return None
