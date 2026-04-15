# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Trust governor: graduated trust with promotion and demotion."""
from __future__ import annotations

import logging
import threading
import time

from ..constants import GOVERNOR_BREAKER_OUTCOME_LIMIT, GOVERNOR_PROMOTION_OUTCOME_LIMIT

logger = logging.getLogger("noba")

_ALL_LEVELS = ["observation", "dry_run", "notify", "approve", "execute"]
_LEVEL_ORDER = {lvl: i for i, lvl in enumerate(_ALL_LEVELS)}
_LEVEL_BELOW = {
    "execute": "approve",
    "approve": "notify",
    "notify": "dry_run",
    "dry_run": "observation",
    "observation": "observation",
}

CIRCUIT_BREAKER_THRESHOLD = 3
CIRCUIT_BREAKER_WINDOW_S = 3600

_lock = threading.Lock()


def effective_trust(rule_id: str, source: str, db) -> str:
    """Resolve the actual trust level for a rule, considering source caps."""
    state = db.get_trust_state(rule_id)
    if not state:
        return "notify"
    level = state["current_level"]
    if source in ("prediction", "anomaly", "health_score"):
        demoted = _LEVEL_BELOW.get(level, "notify")
        # Prediction/anomaly sources cap at minimum "notify" — never go into canary levels
        if _LEVEL_ORDER.get(demoted, 0) < _LEVEL_ORDER.get("notify", 2):
            demoted = "notify"
        level = demoted
    return level


def check_circuit_breaker(rule_id: str, db) -> bool:
    """Check if circuit breaker should trip. Returns True if tripped (demoted)."""
    cutoff = int(time.time()) - CIRCUIT_BREAKER_WINDOW_S
    outcomes = db.get_heal_outcomes(rule_id=rule_id, limit=GOVERNOR_BREAKER_OUTCOME_LIMIT)
    recent_failures = [
        o for o in outcomes
        if o["created_at"] >= cutoff
        and o["action_success"] is not None
        and o["verified"] == 0
    ]
    if len(recent_failures) >= CIRCUIT_BREAKER_THRESHOLD:
        with _lock:
            state = db.get_trust_state(rule_id)
            if state and state["current_level"] != "notify":
                db.upsert_trust_state(rule_id, "notify", state["ceiling"])
                logger.warning(
                    "Circuit breaker tripped for rule %s — demoted to notify",
                    rule_id,
                )
                return True
    return False


def evaluate_promotions(db) -> list[dict]:
    """Check all rules for promotion eligibility. Returns list of suggestions."""
    suggestions: list[dict] = []
    states = db.list_trust_states()
    now = int(time.time())
    min_executions = 10
    min_success_rate = 85.0
    min_age_s = 168 * 3600  # 7 days

    for state in states:
        rule_id = state["rule_id"]
        current = state["current_level"]
        ceiling = state["ceiling"]

        if _LEVEL_ORDER.get(current, 0) >= _LEVEL_ORDER.get(ceiling, 0):
            continue  # already at ceiling

        last_change = state.get("promoted_at") or state.get("demoted_at") or state.get("last_evaluated") or 0
        if now - last_change < min_age_s:
            continue  # too soon

        outcomes = db.get_heal_outcomes(rule_id=rule_id, limit=GOVERNOR_PROMOTION_OUTCOME_LIMIT)
        at_current = [o for o in outcomes if o["trust_level"] == current]
        if len(at_current) < min_executions:
            continue

        if current == "notify":
            # For notify->approve: just need enough trigger count
            next_level = "approve"
        elif current == "approve":
            # For approve->execute: need verified success rate
            with_action = [o for o in at_current if o["action_success"] is not None]
            if len(with_action) < min_executions:
                continue
            verified = sum(1 for o in with_action if o["verified"] == 1)
            rate = (verified / len(with_action)) * 100
            if rate < min_success_rate:
                continue
            next_level = "execute"
        else:
            continue

        suggestions.append({
            "category": "trust_promotion",
            "severity": "info",
            "message": f"Rule '{rule_id}' eligible for promotion: {current} -> {next_level}",
            "rule_id": rule_id,
            "suggested_action": {"promote_to": next_level},
            "evidence": {"total_outcomes": len(at_current)},
        })

    return suggestions
