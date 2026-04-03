# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Heal planner: escalation chains with adaptive scoring."""
from __future__ import annotations

import logging
import threading

from .models import HealOutcome, HealPlan, HealRequest

logger = logging.getLogger("noba")

MAX_ESCALATION_DEPTH = 6
_MIN_EFFECTIVENESS = 30.0  # skip actions below this success rate


class HealPlanner:
    """Select heal actions with escalation chain support and adaptive scoring."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_escalations: dict[str, int] = {}  # correlation_key -> current step

    def select_action(
        self, request: HealRequest, chain: list[dict], db,
        effective_trust: str,
    ) -> HealPlan | None:
        key = request.correlation_key

        with self._lock:
            if key in self._active_escalations:
                logger.debug("Planner: escalation already in progress for %s", key)
                return None
            self._active_escalations[key] = 0

        return self._pick_step(request, chain, db, effective_trust, start_step=0)

    def advance(
        self, outcome: HealOutcome, chain: list[dict], db,
        effective_trust: str,
    ) -> HealPlan | None:
        key = outcome.plan.request.correlation_key
        next_step = outcome.plan.escalation_step + 1

        if next_step >= len(chain) or next_step >= MAX_ESCALATION_DEPTH:
            self._clear_escalation(key)
            logger.info("Planner: escalation chain exhausted for %s", key)
            return None

        with self._lock:
            self._active_escalations[key] = next_step

        plan = self._pick_step(
            outcome.plan.request, chain, db, effective_trust,
            start_step=next_step,
        )
        if plan is None:
            self._clear_escalation(key)
        return plan

    def clear_escalation(self, key: str) -> None:
        """Public method to clear escalation state (e.g., on success)."""
        self._clear_escalation(key)

    def _clear_escalation(self, key: str) -> None:
        with self._lock:
            self._active_escalations.pop(key, None)

    def _pick_step(
        self, request: HealRequest, chain: list[dict], db,
        effective_trust: str, start_step: int,
    ) -> HealPlan | None:
        skipped: list[dict] = []

        for step_idx in range(start_step, min(len(chain), MAX_ESCALATION_DEPTH)):
            step = chain[step_idx]
            action_type = step["action"]
            condition = request.events[0].condition if request.events else ""

            # Adaptive scoring: skip low-effectiveness actions
            rate = db.get_heal_success_rate(action_type, condition, target=request.primary_target)
            if rate > 0 and rate < _MIN_EFFECTIVENESS:
                skipped.append({"action": action_type, "success_rate": rate, "step": step_idx})
                logger.info(
                    "Planner: skipping %s (%.1f%% success rate) for %s",
                    action_type, rate, request.correlation_key,
                )
                continue

            reason_parts = [f"Selected {action_type} (step {step_idx + 1}/{len(chain)})"]
            if skipped:
                skip_strs = [f"{s['action']} ({s['success_rate']:.0f}%)" for s in skipped]
                reason_parts.append(f"Skipped: {', '.join(skip_strs)}")

            return HealPlan(
                request=request,
                action_type=action_type,
                action_params=step.get("params", {}),
                escalation_step=step_idx,
                trust_level=effective_trust,
                reason=". ".join(reason_parts),
                skipped_actions=skipped,
            )

        # All steps skipped or exhausted
        return None
