# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Pre-flight checks before heal action execution.

Every action must pass pre-flight before it runs:
1. Capability match -- handler exists for this host's capabilities
2. Not in maintenance -- target is not in a maintenance window
3. Manifest exists -- we have a capability manifest for this host

Pre-flight is cheap and fast. It prevents wasted execution and
accidental damage from mismatched capabilities.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .capabilities import CapabilityManifest, resolve_handler

logger = logging.getLogger("noba")


@dataclass
class PreFlightResult:
    """Result of pre-flight validation."""

    passed: bool = False
    failure_reason: str = ""
    resolved_handler: dict | None = None
    checks: dict = field(default_factory=dict)


def run_preflight(
    *,
    action_type: str,
    handlers: list[dict],
    manifest: CapabilityManifest | None,
    target: str,
    in_maintenance: bool = False,
) -> PreFlightResult:
    """Run all pre-flight checks for an action. Returns PreFlightResult."""
    result = PreFlightResult()
    result.checks = {}

    # Check 1: manifest exists
    if manifest is None:
        result.checks["manifest"] = "missing"
        result.failure_reason = "no_manifest"
        logger.warning("Pre-flight FAIL [%s@%s]: no capability manifest", action_type, target)
        return result
    result.checks["manifest"] = "ok"

    # Check 2: maintenance window
    if in_maintenance:
        result.checks["maintenance"] = "blocked"
        result.failure_reason = "maintenance"
        logger.info("Pre-flight FAIL [%s@%s]: target in maintenance window", action_type, target)
        return result
    result.checks["maintenance"] = "ok"

    # Check 3: capability match
    handler = resolve_handler(handlers, manifest)
    if handler is None:
        result.checks["capability_match"] = "no match"
        result.failure_reason = "no_capable_handler"
        caps = list(manifest.capabilities.keys())
        logger.warning(
            "Pre-flight FAIL [%s@%s]: no handler matches capabilities %s",
            action_type, target, caps,
        )
        return result
    result.checks["capability_match"] = handler.get("requires", "")
    result.resolved_handler = handler

    # All passed
    result.passed = True
    return result
