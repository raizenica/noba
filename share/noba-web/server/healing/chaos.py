# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Chaos testing framework for controlled fault injection.

Defines scenarios that intentionally break things and validates the
healing pipeline responds correctly. Can run in dry-run (simulation)
or live mode.

Scenarios are declarative: inject a fault, define expected outcomes.
The runner executes the injection, waits for the pipeline to respond,
and validates expectations.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger("noba")


@dataclass
class ChaosScenario:
    """A chaos test scenario."""

    name: str
    description: str
    inject: dict
    expectations: list[dict] = field(default_factory=list)
    teardown: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> ChaosScenario:
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            inject=d.get("inject", {}),
            expectations=d.get("expect", []),
            teardown=d.get("teardown", {}),
        )


# Built-in scenarios from the spec
BUILT_IN_SCENARIOS = [
    {
        "name": "container_crash_recovery",
        "description": "Stop a container, verify auto-restart and verification",
        "inject": {"action": "stop_container", "target": "test-container"},
        "expect": [
            {"check": "heal_triggered", "value": True},
            {"check": "action_taken", "value": "restart_container"},
            {"check": "verified", "value": True},
        ],
    },
    {
        "name": "dependency_cascade_suppression",
        "description": "Stop upstream dependency, verify downstream healing suppressed",
        "inject": {"action": "stop_container", "target": "upstream-dep"},
        "expect": [
            {"check": "heal_triggered_for", "value": "upstream-dep"},
            {"check": "downstream_suppressed", "value": True},
            {"check": "root_cause_identified", "value": "upstream-dep"},
        ],
    },
    {
        "name": "escalation_chain_walk",
        "description": "Service resists healing, walks full escalation chain",
        "inject": {"action": "corrupt_service", "target": "test-service"},
        "expect": [
            {"check": "escalation_steps", "value": 3},
            {"check": "final_action", "value": "approval_requested"},
        ],
    },
    {
        "name": "site_connectivity_isolation",
        "description": "Block site connectivity, verify no false heals",
        "inject": {"action": "block_site", "target": "site-a"},
        "expect": [
            {"check": "site_suspect", "value": True},
            {"check": "heals_at_site", "value": 0},
        ],
    },
    {
        "name": "heal_storm_circuit_breaker",
        "description": "Rapid repeated failures trigger circuit breaker",
        "inject": {"action": "flap_service", "target": "test-service", "cycles": 10},
        "expect": [
            {"check": "circuit_breaker_tripped", "value": True},
            {"check": "trust_demoted", "value": True},
        ],
    },
    {
        "name": "stale_metrics_guard",
        "description": "Stale collector data blocks healing",
        "inject": {"action": "pause_collector", "duration": 120},
        "expect": [
            {"check": "heals_triggered", "value": 0},
            {"check": "staleness_detected", "value": True},
        ],
    },
    {
        "name": "capability_mismatch",
        "description": "Missing capability aborts action gracefully",
        "inject": {"action": "remove_capability", "target": "docker"},
        "expect": [
            {"check": "preflight_failed", "value": True},
            {"check": "action_aborted", "value": True},
        ],
    },
    {
        "name": "maintenance_window_suppression",
        "description": "Healing suppressed during maintenance window",
        "inject": {"action": "enter_maintenance", "target": "all"},
        "expect": [
            {"check": "heals_suppressed", "value": True},
        ],
    },
    {
        "name": "approval_timeout",
        "description": "High-risk action with no approval auto-denies",
        "inject": {"action": "trigger_high_risk", "target": "test-host"},
        "expect": [
            {"check": "approval_requested", "value": True},
            {"check": "auto_denied", "value": True},
        ],
    },
    {
        "name": "rollback_on_failure",
        "description": "Failed verification triggers rollback for reversible action",
        "inject": {"action": "scale_and_fail", "target": "test-app"},
        "expect": [
            {"check": "rollback_triggered", "value": True},
            {"check": "state_restored", "value": True},
        ],
    },
    {
        "name": "power_flicker_debounce",
        "description": "Rapid connectivity flaps don't cause heal storm",
        "inject": {"action": "flap_connectivity", "target": "site-a", "cycles": 5},
        "expect": [
            {"check": "site_suspect", "value": True},
            {"check": "heals_at_site", "value": 0},
        ],
    },
    {
        "name": "manual_fix_race",
        "description": "Operator fixes manually while auto-heal in progress",
        "inject": {"action": "trigger_and_fix", "target": "test-service"},
        "expect": [
            {"check": "resolved_externally", "value": True},
            {"check": "no_duplicate_action", "value": True},
        ],
    },
]


def check_expectation(expectation: dict, *, actual: dict) -> dict:
    """Validate a single expectation against actual results."""
    check = expectation.get("check", "")
    expected = expectation.get("value")
    actual_val = actual.get(check)

    passed = actual_val == expected
    return {
        "check": check,
        "expected": expected,
        "actual": actual_val,
        "passed": passed,
    }


def _evaluate_expectation(check: str, target: str):
    """Evaluate a chaos test expectation against current system state."""
    try:
        from ..deps import db as _db
        if check == "heal_triggered":
            recent = _db.list_heal_ledger(limit=5)
            return any(e.get("target") == target for e in recent)
        elif check == "action_taken":
            recent = _db.list_heal_ledger(limit=5)
            for e in recent:
                if e.get("target") == target:
                    return e.get("action_type", "")
            return ""
        elif check == "verified":
            recent = _db.list_heal_ledger(limit=5)
            for e in recent:
                if e.get("target") == target:
                    return e.get("outcome") == "verified"
            return False
        elif check == "heal_triggered_for":
            recent = _db.list_heal_ledger(limit=10)
            return any(e.get("target") == target for e in recent)
        elif check == "downstream_suppressed":
            recent = _db.list_heal_ledger(limit=10)
            return any(e.get("outcome") == "suppressed" for e in recent)
        elif check == "root_cause_identified":
            recent = _db.list_heal_ledger(limit=10)
            for e in recent:
                if e.get("root_cause"):
                    return e["root_cause"]
            return None
    except Exception as exc:
        logger.debug("Chaos expectation check failed: %s", exc)
    return None


class ChaosRunner:
    """Runs chaos test scenarios."""

    def __init__(self) -> None:
        self._scenarios = {s["name"]: ChaosScenario.from_dict(s) for s in BUILT_IN_SCENARIOS}

    def list_scenarios(self) -> list[dict]:
        """List all available scenarios."""
        return [
            {"name": s.name, "description": s.description, "inject": s.inject}
            for s in self._scenarios.values()
        ]

    def register_scenario(self, scenario_dict: dict) -> None:
        """Register a custom scenario."""
        s = ChaosScenario.from_dict(scenario_dict)
        self._scenarios[s.name] = s

    def run_scenario(self, name: str, *, dry_run: bool = True) -> dict:
        """Run a chaos scenario. In dry_run mode, simulates without injection."""
        scenario = self._scenarios.get(name)
        if not scenario:
            return {"name": name, "status": "error", "message": f"Scenario not found: {name}"}

        result: dict = {
            "name": scenario.name,
            "description": scenario.description,
            "dry_run": dry_run,
            "started_at": time.time(),
            "inject": scenario.inject,
            "expectations": [],
            "status": "completed",
        }

        if dry_run:
            # In dry-run, we simulate expected outcomes without injection
            for exp in scenario.expectations:
                result["expectations"].append(
                    {
                        "check": exp.get("check"),
                        "expected": exp.get("value"),
                        "actual": "[dry-run: not executed]",
                        "passed": None,  # unknown in dry-run
                    }
                )
            result["status"] = "dry_run_complete"
        else:
            # Live mode: execute the injection and validate expectations
            inject = scenario.inject
            action = inject.get("action", "")
            target = inject.get("target", "")

            try:
                from ..remediation import execute_action
                inject_result = execute_action(
                    action, inject,
                    triggered_by="chaos_test", trigger_type="chaos",
                    target=target,
                )
                result["inject_result"] = inject_result
                logger.info("Chaos inject %s on %s: %s", action, target, inject_result.get("success"))

                # Wait for healing pipeline to respond
                settle = inject.get("settle_seconds", 30)
                time.sleep(settle)

                # Validate expectations against current state
                for exp in scenario.expectations:
                    check = exp.get("check")
                    expected = exp.get("value")
                    actual = _evaluate_expectation(check, target)
                    passed = actual == expected
                    result["expectations"].append({
                        "check": check,
                        "expected": expected,
                        "actual": actual,
                        "passed": passed,
                    })

                all_passed = all(e["passed"] for e in result["expectations"] if e["passed"] is not None)
                result["status"] = "passed" if all_passed else "failed"

            except Exception as exc:
                logger.error("Chaos live injection failed: %s", exc)
                result["status"] = "error"
                result["error"] = "Chaos injection execution failed"

            # Teardown: restore original state if defined
            if scenario.teardown:
                try:
                    teardown_action = scenario.teardown.get("action", "")
                    if teardown_action:
                        execute_action(
                            teardown_action, scenario.teardown,
                            triggered_by="chaos_teardown", trigger_type="chaos",
                            target=scenario.teardown.get("target", target),
                        )
                except Exception as exc:
                    logger.error("Chaos teardown failed: %s", exc)

        result["completed_at"] = time.time()
        result["duration_s"] = round(result["completed_at"] - result["started_at"], 3)
        return result
