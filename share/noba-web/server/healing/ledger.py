# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Heal ledger: record outcomes and generate suggestions."""
from __future__ import annotations

import logging

from ..constants import LEDGER_SUGGESTION_OUTCOME_LIMIT
from .models import HealOutcome

logger = logging.getLogger("noba")

_RECURRING_THRESHOLD = 10  # triggers in 30 days
_LOW_EFFECTIVENESS_THRESHOLD = 30.0  # percent


def record(outcome: HealOutcome, db) -> int:
    """Record a HealOutcome to the DB."""
    plan = outcome.plan
    event = plan.request.events[0] if plan.request.events else None
    # Extract recognised extended audit trail fields from outcome.extra
    _extended_keys = {
        "risk_level", "snapshot_id", "rollback_status",
        "dependency_root", "suppressed_by", "maintenance_window_id",
        "instance_id",
    }
    extra_kwargs = {k: v for k, v in outcome.extra.items() if k in _extended_keys}
    return db.insert_heal_outcome(
        correlation_key=plan.request.correlation_key,
        rule_id=event.rule_id if event else "",
        condition=event.condition if event else "",
        target=plan.request.primary_target,
        action_type=plan.action_type,
        action_params=plan.action_params,
        escalation_step=plan.escalation_step,
        action_success=outcome.action_success,
        verified=outcome.verified if outcome.verified is not None else False,
        duration_s=outcome.duration_s,
        metrics_before=outcome.metrics_before,
        metrics_after=outcome.metrics_after,
        trust_level=plan.trust_level,
        source=event.source if event else "unknown",
        approval_id=outcome.approval_id,
        **extra_kwargs,
    )


def generate_suggestions(db) -> list[dict]:
    """Analyze ledger data and produce actionable suggestions."""
    suggestions: list[dict] = []
    outcomes = db.get_heal_outcomes(limit=LEDGER_SUGGESTION_OUTCOME_LIMIT)

    # Group by rule_id + target
    groups: dict[str, list[dict]] = {}
    for o in outcomes:
        key = f"{o['rule_id']}:{o['target']}"
        groups.setdefault(key, []).append(o)

    for key, items in groups.items():
        rule_id = items[0]["rule_id"]
        target = items[0]["target"]
        executed = [i for i in items if i["action_success"] is not None]

        # Recurring issue detection
        if len(executed) >= _RECURRING_THRESHOLD:
            suggestions.append({
                "category": "recurring_issue",
                "severity": "warning",
                "message": (
                    f"Target '{target}' healed {len(executed)} times for "
                    f"rule '{rule_id}'. Consider investigating root cause."
                ),
                "rule_id": rule_id,
            })

        # Low effectiveness detection
        if executed:
            verified = sum(1 for i in executed if i["verified"] == 1)
            rate = (verified / len(executed)) * 100
            if rate < _LOW_EFFECTIVENESS_THRESHOLD and len(executed) >= 5:
                action = items[0]["action_type"]
                suggestions.append({
                    "category": "low_effectiveness",
                    "severity": "warning",
                    "message": (
                        f"Action '{action}' has {rate:.0f}% success rate for "
                        f"rule '{rule_id}' on '{target}'."
                    ),
                    "rule_id": rule_id,
                })

    # Persist suggestions
    for s in suggestions:
        db.insert_heal_suggestion(**s)

    return suggestions
