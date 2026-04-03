# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Tiered approval manager with escalation and emergency override.

Determines whether a heal action needs human approval based on:
- Risk level of the action (low / medium / high)
- Current trust governor state (notify / approve / execute)
- User staffing (admin_count, operator_count)
- Emergency override conditions
"""
from __future__ import annotations

import logging

logger = logging.getLogger("noba")

# Severity ordering for emergency override comparisons
_SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2, "critical": 3}


def determine_approval_requirement(
    action_type: str,
    risk: str,
    trust_level: str,
) -> str:
    """Determine whether a heal action requires approval.

    Returns one of:
    - "auto"        — execute immediately (low-risk + execute trust)
    - "auto_notify" — execute + send notification (medium-risk + execute trust)
    - "required"    — needs human approval (high-risk OR trust="approve")
    - "notify"      — notify only, no execution (trust="notify")
    """
    # Trust level gates take priority over risk level
    if trust_level == "notify":
        return "notify"

    if trust_level == "approve":
        return "required"

    # trust_level == "execute" — gate on risk
    if risk == "high":
        return "required"

    if risk == "medium":
        return "auto_notify"

    # low risk + execute trust
    return "auto"


def resolve_escalation_chain(
    admin_count: int,
    operator_count: int,
) -> dict:
    """Build an approval escalation chain based on available approvers.

    Returns a dict with one of:
    - {"action": "auto_deny"}                                   — no approvers at all
    - {"stages": ["admin"], "use_cooldown": True}               — single admin only
    - {"stages": ["operator"], "use_cooldown": False}           — operators, no admins
    - {"stages": ["operator", "admin"], "use_cooldown": False}  — full staff
    """
    if admin_count == 0 and operator_count == 0:
        return {"action": "auto_deny"}

    stages: list[str] = []

    if operator_count > 0:
        stages.append("operator")

    if admin_count > 0:
        stages.append("admin")

    # Single-admin safety: if only one admin and no operators, use cooldown
    # so the sole admin gets a grace period before auto-escalating
    use_cooldown = (admin_count == 1 and operator_count == 0)

    return {"stages": stages, "use_cooldown": use_cooldown}


def build_approval_context(plan, event) -> dict:
    """Build an enriched context dict for an approval request.

    Pulls risk level from the ACTION_TYPES registry; gracefully falls back
    to "unknown" if the action type is not registered.

    Args:
        plan: HealPlan dataclass instance
        event: HealEvent dataclass instance

    Returns:
        Dict suitable for storing alongside the approval record and for
        rendering in the approval UI.
    """
    from ..remediation import ACTION_TYPES

    action_def = ACTION_TYPES.get(plan.action_type, {})
    risk = action_def.get("risk", "unknown")
    reversible = action_def.get("reversible", False)
    has_rollback = action_def.get("has_rollback", False)

    # Collect evidence: event metrics + source information
    evidence: dict = {
        "source": event.source,
        "rule_id": event.rule_id,
        "condition": event.condition,
        "severity": event.severity,
        "metrics": event.metrics,
        "timestamp": event.timestamp,
    }

    # Include all correlated events if more than one
    correlated_events = plan.request.events
    if len(correlated_events) > 1:
        evidence["correlated_events"] = [
            {
                "source": e.source,
                "rule_id": e.rule_id,
                "target": e.target,
                "severity": e.severity,
                "timestamp": e.timestamp,
            }
            for e in correlated_events
        ]

    return {
        "action_type": plan.action_type,
        "action_params": plan.action_params,
        "target": plan.request.primary_target,
        "risk": risk,
        "escalation_step": plan.escalation_step,
        "trust_level": plan.trust_level,
        "reason": plan.reason,
        "skipped_actions": plan.skipped_actions,
        "evidence": evidence,
        "reversible": reversible,
        "rollback_available": has_rollback,
        "correlation_key": plan.request.correlation_key,
        "request_severity": plan.request.severity,
        "description": action_def.get("description", ""),
    }


def check_emergency_override(
    config: dict,
    severity: str,
    consecutive_failures: int,
    minutes_waiting: float,
) -> bool:
    """Determine if emergency override conditions are met.

    The override allows auto-execution of an otherwise approval-gated action
    when human responders are not reachable and conditions are severe enough.

    All conditions in config["conditions"] must be satisfied simultaneously.

    Args:
        config: Dict with "enabled" bool and optional "conditions" sub-dict.
                Conditions keys: "severity", "consecutive_failures",
                "no_response_minutes".
        severity: Current event severity string.
        consecutive_failures: Number of consecutive heal failures for this target.
        minutes_waiting: Minutes elapsed since approval was first requested.

    Returns:
        True only when enabled=True AND all configured conditions are satisfied.
    """
    if not config.get("enabled", False):
        return False

    conditions = config.get("conditions", {})
    if not conditions:
        # Enabled but no conditions specified — treat as override active
        return True

    # Check severity threshold (must be >= configured severity)
    required_severity = conditions.get("severity")
    if required_severity is not None:
        current_order = _SEVERITY_ORDER.get(severity, -1)
        required_order = _SEVERITY_ORDER.get(required_severity, 999)
        if current_order < required_order:
            return False

    # Check consecutive failure count threshold
    required_failures = conditions.get("consecutive_failures")
    if required_failures is not None:
        if consecutive_failures < required_failures:
            return False

    # Check how long approval has been waiting
    required_wait = conditions.get("no_response_minutes")
    if required_wait is not None:
        if minutes_waiting < required_wait:
            return False

    return True
