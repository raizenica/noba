# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing planner: escalation chains, adaptive scoring."""
from __future__ import annotations

import time
from unittest.mock import MagicMock


def _make_request(target="nginx"):
    from server.healing.models import HealEvent, HealRequest
    event = HealEvent(
        source="alert", rule_id="cpu_high",
        condition="cpu_percent > 90", target=target,
        severity="warning", timestamp=time.time(),
        metrics={"cpu_percent": 95},
    )
    return HealRequest(
        correlation_key=target, events=[event],
        primary_target=target, severity="warning",
        created_at=time.time(),
    )


def _chain():
    return [
        {"action": "restart_container", "params": {"container": "nginx"}, "verify_timeout": 30},
        {"action": "scale_container", "params": {"container": "nginx", "mem_limit": "4g"}, "verify_timeout": 30},
    ]


class TestSelectAction:
    def test_selects_first_step(self):
        from server.healing.planner import HealPlanner
        db = MagicMock()
        db.get_heal_success_rate = MagicMock(return_value=80.0)
        db.get_trust_state = MagicMock(return_value={"current_level": "execute", "ceiling": "execute"})
        planner = HealPlanner()
        plan = planner.select_action(
            _make_request(), _chain(), db,
            effective_trust="execute",
        )
        assert plan.action_type == "restart_container"
        assert plan.escalation_step == 0

    def test_skips_low_effectiveness_action(self):
        from server.healing.planner import HealPlanner
        db = MagicMock()
        # First action has 10% success rate (below 30% threshold)
        db.get_heal_success_rate = MagicMock(side_effect=[10.0, 80.0])
        planner = HealPlanner()
        plan = planner.select_action(
            _make_request(), _chain(), db,
            effective_trust="execute",
        )
        assert plan.action_type == "scale_container"
        assert plan.escalation_step == 1
        assert len(plan.skipped_actions) == 1


class TestAdvance:
    def test_advances_step(self):
        from server.healing.planner import HealPlanner
        from server.healing.models import HealOutcome
        db = MagicMock()
        db.get_heal_success_rate = MagicMock(return_value=80.0)
        planner = HealPlanner()
        plan = planner.select_action(
            _make_request(), _chain(), db,
            effective_trust="execute",
        )
        outcome = HealOutcome(
            plan=plan, action_success=True, verified=False,
            verification_detail="still failing", duration_s=15.0,
        )
        next_plan = planner.advance(outcome, _chain(), db, effective_trust="execute")
        assert next_plan is not None
        assert next_plan.escalation_step == 1
        assert next_plan.action_type == "scale_container"

    def test_returns_none_when_exhausted(self):
        from server.healing.planner import HealPlanner
        from server.healing.models import HealOutcome, HealPlan
        planner = HealPlanner()
        plan = HealPlan(
            request=_make_request(), action_type="scale_container",
            action_params={}, escalation_step=1, trust_level="execute",
        )
        outcome = HealOutcome(
            plan=plan, action_success=True, verified=False,
        )
        next_plan = planner.advance(outcome, _chain(), db=MagicMock(), effective_trust="execute")
        assert next_plan is None


class TestEscalationGuard:
    def test_rejects_duplicate_escalation(self):
        from server.healing.planner import HealPlanner
        db = MagicMock()
        db.get_heal_success_rate = MagicMock(return_value=80.0)
        planner = HealPlanner()
        planner.select_action(
            _make_request("nginx"), _chain(), db,
            effective_trust="execute",
        )
        # Same target while escalation is in progress
        plan2 = planner.select_action(
            _make_request("nginx"), _chain(), db,
            effective_trust="execute",
        )
        assert plan2 is None

    def test_max_depth_enforced(self):
        from server.healing.planner import MAX_ESCALATION_DEPTH
        assert MAX_ESCALATION_DEPTH == 6
