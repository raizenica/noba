# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Health score integration with healing pipeline.

Evaluates health score categories against configurable thresholds.
When a category drops below its threshold, generates heal suggestions
and optionally emits HealEvents for proactive cleanup.
"""
from __future__ import annotations

import json
import logging
import time

from .models import HealEvent

logger = logging.getLogger("noba")

# Default thresholds (score out of 10). Below this = trigger.
DEFAULT_THRESHOLDS = {
    "capacity": 4,       # disk/memory pressure
    "certificates": 5,   # certs expiring soon
    "backup": 3,         # backup freshness
    "monitoring": 6,     # agents offline
    "uptime": 5,         # SLA degradation
    "updates": 5,        # pending security updates
}

# Categories that can trigger heal events (not just suggestions)
_ACTIONABLE_CATEGORIES = {
    "capacity": {
        "condition": "capacity_score < threshold",
        "suggested_actions": ["storage_cleanup", "temp_cleanup", "log_rotate"],
    },
    "certificates": {
        "condition": "cert_health < threshold",
        "suggested_actions": ["cert_renew"],
    },
    "backup": {
        "condition": "backup_freshness < threshold",
        "suggested_actions": ["backup_verify", "trigger_backup"],
    },
}


def evaluate_health_thresholds(
    categories: dict,
    *,
    thresholds: dict[str, int] | None = None,
) -> tuple[list[dict], list[HealEvent]]:
    """Evaluate health score categories against thresholds.

    Returns (suggestions, heal_events).
    """
    effective_thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    suggestions: list[dict] = []
    events: list[HealEvent] = []
    now = time.time()

    for cat_name, cat_data in categories.items():
        score = cat_data.get("score")
        # Categories reporting score=None (unknown/failed) are intentionally
        # skipped -- we cannot trigger healing on data we do not have.
        if score is None:
            continue
        if cat_data.get("status") == "unknown":
            continue
        threshold = effective_thresholds.get(cat_name, 5)
        details = cat_data.get("details", "")

        if score >= threshold:
            continue

        # Generate suggestion
        msg = (
            f"Health score category '{cat_name}' is degraded "
            f"(score: {score}/10, threshold: {threshold}). "
        )
        if details:
            msg += f"Details: {details}. "

        actionable = _ACTIONABLE_CATEGORIES.get(cat_name, {})
        if actionable.get("suggested_actions"):
            msg += f"Suggested actions: {', '.join(actionable['suggested_actions'])}."

        suggestions.append({
            "category": f"health_{cat_name}",
            "severity": "warning" if score <= threshold // 2 else "info",
            "message": msg,
            "rule_id": f"health:{cat_name}",
            "suggested_action": json.dumps(actionable.get("suggested_actions", [])),
            "evidence": {"score": score, "threshold": threshold, "details": details},
        })

        # For very low scores in actionable categories, emit heal event
        if cat_name in _ACTIONABLE_CATEGORIES and score <= threshold // 2:
            events.append(HealEvent(
                source="health_score",
                rule_id=f"health:{cat_name}",
                condition=f"{cat_name}_score={score} (threshold={threshold})",
                target=cat_name,
                severity="warning",
                timestamp=now,
                metrics={"score": score, "threshold": threshold},
            ))

    return suggestions, events
