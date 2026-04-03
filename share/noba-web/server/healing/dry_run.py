# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Dry-run pipeline simulation.

Runs the full healing pipeline logic without executing any action.
Returns a detailed report of what WOULD happen if a real heal event
were processed. Used for testing, debugging, and operator confidence.
"""
from __future__ import annotations

import logging
import time

from .correlation import HealCorrelator
from .governor import effective_trust
from .models import HealEvent
from .planner import HealPlanner

logger = logging.getLogger("noba")


def simulate_heal_event(
    event: HealEvent,
    *,
    db=None,
    rules_cfg: dict | None = None,
    dep_graph=None,
    in_maintenance: bool = False,
) -> dict:
    """Simulate a heal event through the pipeline without executing.

    Returns a detailed dict describing what would happen.
    """
    result: dict = {
        "event": {
            "source": event.source,
            "rule_id": event.rule_id,
            "condition": event.condition,
            "target": event.target,
            "severity": event.severity,
            "metrics": event.metrics,
        },
        "timestamp": time.time(),
        "suppressed": False,
        "suppression_reason": "",
    }

    # Maintenance check — short-circuit before any pipeline work
    if in_maintenance:
        result["suppressed"] = True
        result["suppression_reason"] = "Target in maintenance window"
        result["would_correlate"] = False
        result["dependency_analysis"] = {}
        result["would_select"] = {}
        result["pre_flight"] = {}
        result["rollback_plan"] = ""
        return result

    # Correlation — use a temporary correlator so real pipeline state is
    # not polluted by the simulation
    temp_correlator = HealCorrelator()
    request = temp_correlator.correlate(event)
    result["would_correlate"] = request is not None
    result["correlation_key"] = request.correlation_key if request else None

    if not request:
        result["dependency_analysis"] = {}
        result["would_select"] = {}
        result["pre_flight"] = {}
        result["rollback_plan"] = ""
        return result

    # Dependency analysis
    dep_info: dict = {"root_cause": event.target, "suppressed": []}
    if dep_graph is not None:
        from .dependency_graph import resolve_root_cause
        root, suppressed_set = resolve_root_cause(dep_graph, failing_targets={event.target})
        dep_info = {"root_cause": root, "suppressed": sorted(suppressed_set)}
        if event.target in suppressed_set:
            result["suppressed"] = True
            result["suppression_reason"] = f"Downstream of root cause: {root}"
    result["dependency_analysis"] = dep_info

    # Trust resolution
    cfg = (rules_cfg or {}).get(event.rule_id, {})
    chain: list[dict] = cfg.get("escalation_chain", [
        {"action": "restart_container", "params": {}, "verify_timeout": 30},
    ])

    trust = "execute"
    if db is not None:
        trust = effective_trust(event.rule_id, event.source, db)
    result["trust_level"] = trust

    # Plan selection — fresh planner so escalation state is isolated
    planner = HealPlanner()
    plan = planner.select_action(request, chain, db, effective_trust=trust)

    if plan is not None:
        result["would_select"] = {
            "action": plan.action_type,
            "action_type": plan.action_type,
            "action_params": plan.action_params,
            "step": plan.escalation_step,
            "trust_level": plan.trust_level,
            "reason": plan.reason,
        }

        # Pre-flight check
        from .preflight import run_preflight
        from ..remediation import FALLBACK_CHAINS

        fallback_handlers = FALLBACK_CHAINS.get(plan.action_type)
        if fallback_handlers:
            manifest = None
            if db is not None:
                try:
                    import json
                    from .capabilities import CapabilityManifest
                    row = db.get_capability_manifest(event.target)
                    if row:
                        manifest = CapabilityManifest.from_dict(json.loads(row["manifest"]))
                except Exception:
                    pass

            pfr = run_preflight(
                action_type=plan.action_type,
                handlers=fallback_handlers,
                manifest=manifest,
                target=event.target,
                in_maintenance=in_maintenance,
            )
            result["pre_flight"] = {
                "passed": pfr.passed,
                "failure_reason": pfr.failure_reason,
                "checks": pfr.checks,
                "resolved_handler": pfr.resolved_handler,
            }
        else:
            result["pre_flight"] = {
                "passed": True,
                "failure_reason": "",
                "checks": {"note": "No fallback chain — API-based action"},
            }

        # Rollback plan
        from .snapshots import is_reversible
        from ..remediation import ACTION_TYPES

        defn = ACTION_TYPES.get(plan.action_type, {})
        if is_reversible(plan.action_type):
            reverse = defn.get("reverse_action", plan.action_type)
            result["rollback_plan"] = f"Reversible — reverse action: {reverse}"
        else:
            result["rollback_plan"] = "Irreversible — no rollback available"
    else:
        result["would_select"] = {"note": "No action selected (chain exhausted or in progress)"}
        result["pre_flight"] = {}
        result["rollback_plan"] = ""

    return result
