# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing.approval_manager: tiered approval with escalation."""
from __future__ import annotations



class TestDetermineApproval:
    def test_low_risk_auto_executes(self):
        from server.healing.approval_manager import determine_approval_requirement
        result = determine_approval_requirement(
            action_type="service_restart", risk="low", trust_level="execute",
        )
        assert result == "auto"

    def test_medium_risk_auto_with_notification(self):
        from server.healing.approval_manager import determine_approval_requirement
        result = determine_approval_requirement(
            action_type="cert_renew", risk="medium", trust_level="execute",
        )
        assert result == "auto_notify"

    def test_high_risk_requires_approval(self):
        from server.healing.approval_manager import determine_approval_requirement
        result = determine_approval_requirement(
            action_type="host_reboot", risk="high", trust_level="execute",
        )
        assert result == "required"

    def test_trust_level_approve_requires_approval_regardless(self):
        from server.healing.approval_manager import determine_approval_requirement
        result = determine_approval_requirement(
            action_type="service_restart", risk="low", trust_level="approve",
        )
        assert result == "required"

    def test_trust_level_notify_is_notify_only(self):
        from server.healing.approval_manager import determine_approval_requirement
        result = determine_approval_requirement(
            action_type="service_restart", risk="low", trust_level="notify",
        )
        assert result == "notify"


class TestAdaptiveStaffing:
    def test_no_approvers_auto_denies(self):
        from server.healing.approval_manager import resolve_escalation_chain
        chain = resolve_escalation_chain(admin_count=0, operator_count=0)
        assert chain["action"] == "auto_deny"

    def test_single_admin_no_escalation(self):
        from server.healing.approval_manager import resolve_escalation_chain
        chain = resolve_escalation_chain(admin_count=1, operator_count=0)
        assert chain["stages"] == ["admin"]
        assert chain["use_cooldown"] is True  # single-admin safety

    def test_operators_and_admins_full_chain(self):
        from server.healing.approval_manager import resolve_escalation_chain
        chain = resolve_escalation_chain(admin_count=2, operator_count=3)
        assert chain["stages"] == ["operator", "admin"]
        assert chain["use_cooldown"] is False

    def test_operators_only(self):
        from server.healing.approval_manager import resolve_escalation_chain
        chain = resolve_escalation_chain(admin_count=0, operator_count=2)
        assert chain["stages"] == ["operator"]


class TestApprovalContext:
    def test_context_has_required_fields(self):
        from server.healing.approval_manager import build_approval_context
        from server.healing.models import HealEvent, HealRequest, HealPlan

        event = HealEvent(
            source="alert", rule_id="cpu-high", condition="cpu > 95",
            target="proxmox-1", severity="critical", timestamp=0,
            metrics={"cpu_percent": 98},
        )
        request = HealRequest(
            correlation_key="proxmox-1:cpu", events=[event],
            primary_target="proxmox-1", severity="critical", created_at=0,
        )
        plan = HealPlan(
            request=request, action_type="host_reboot",
            action_params={"hostname": "proxmox-1"}, escalation_step=3,
            trust_level="approve", reason="escalation step 4",
            skipped_actions=["restart_container", "service_restart"],
        )

        ctx = build_approval_context(plan, event)
        assert ctx["action_type"] == "host_reboot"
        assert ctx["target"] == "proxmox-1"
        assert ctx["risk"] == "high"
        assert ctx["escalation_step"] == 3
        assert "evidence" in ctx
        assert "skipped_actions" in ctx


class TestEmergencyOverride:
    def test_override_triggers_when_conditions_met(self):
        from server.healing.approval_manager import check_emergency_override
        config = {
            "enabled": True,
            "conditions": {
                "severity": "critical",
                "consecutive_failures": 5,
                "no_response_minutes": 15,
            },
        }
        result = check_emergency_override(
            config=config, severity="critical",
            consecutive_failures=6, minutes_waiting=20,
        )
        assert result is True

    def test_override_disabled(self):
        from server.healing.approval_manager import check_emergency_override
        config = {"enabled": False}
        result = check_emergency_override(
            config=config, severity="critical",
            consecutive_failures=10, minutes_waiting=60,
        )
        assert result is False

    def test_override_conditions_not_met(self):
        from server.healing.approval_manager import check_emergency_override
        config = {
            "enabled": True,
            "conditions": {
                "severity": "critical",
                "consecutive_failures": 5,
                "no_response_minutes": 15,
            },
        }
        result = check_emergency_override(
            config=config, severity="warning",  # not critical
            consecutive_failures=6, minutes_waiting=20,
        )
        assert result is False
