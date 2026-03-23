"""Tests for healing notification enrichment."""
from __future__ import annotations



def _make_outcome(action_type="restart_container", target="frigate",
                  success=True, verified=True, duration=12.3,
                  detail="mem_percent dropped to 34%"):
    from server.healing.models import HealEvent, HealRequest, HealPlan, HealOutcome
    event = HealEvent(
        source="alert", rule_id="mem-high", condition="mem_percent > 85",
        target=target, severity="warning", timestamp=0,
        metrics={"mem_percent": 92},
    )
    request = HealRequest(
        correlation_key=f"{target}:mem", events=[event],
        primary_target=target, severity="warning", created_at=0,
    )
    plan = HealPlan(
        request=request, action_type=action_type,
        action_params={"container": target}, escalation_step=0,
        trust_level="execute", reason="First step in chain",
        skipped_actions=[],
    )
    return HealOutcome(
        plan=plan, action_success=success, verified=verified,
        verification_detail=detail, duration_s=duration,
        metrics_before={"mem_percent": 92},
        metrics_after={"mem_percent": 34} if verified else None,
    )


class TestFormatHealNotification:
    def test_success_notification_has_key_fields(self):
        from server.healing.notifications import format_heal_notification
        outcome = _make_outcome()
        msg = format_heal_notification(outcome)
        assert "restart_container" in msg
        assert "frigate" in msg
        assert "mem_percent > 85" in msg
        assert "Verified" in msg or "verified" in msg.lower()
        assert "12.3" in msg

    def test_failure_notification_shows_next_step(self):
        from server.healing.notifications import format_heal_notification
        outcome = _make_outcome(verified=False, detail="mem_percent still 89%")
        msg = format_heal_notification(outcome)
        assert "frigate" in msg
        assert "not verified" in msg.lower() or "failed" in msg.lower()

    def test_notification_includes_trigger_info(self):
        from server.healing.notifications import format_heal_notification
        outcome = _make_outcome()
        msg = format_heal_notification(outcome)
        assert "mem_percent > 85" in msg  # trigger condition
        assert "alert" in msg.lower()  # source

    def test_notification_includes_risk_level(self):
        from server.healing.notifications import format_heal_notification
        outcome = _make_outcome()
        msg = format_heal_notification(outcome)
        # restart_container is low risk
        assert "low" in msg.lower() or "risk" in msg.lower()

    def test_approval_notification_format(self):
        from server.healing.notifications import format_approval_notification
        from server.healing.models import HealEvent, HealRequest, HealPlan
        event = HealEvent(
            source="alert", rule_id="cpu-high", condition="cpu_percent > 95",
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
        msg = format_approval_notification(plan)
        assert "host_reboot" in msg
        assert "proxmox-1" in msg
        assert "APPROVAL" in msg or "approval" in msg.lower()
        assert "cpu_percent > 95" in msg

    def test_digest_format(self):
        from server.healing.notifications import format_digest
        outcomes = [
            _make_outcome(target="plex"),
            _make_outcome(target="frigate"),
            _make_outcome(action_type="clear_cache", target="system", detail="cache cleared"),
        ]
        msg = format_digest(outcomes, period="1 hour")
        assert "3" in msg or "three" in msg.lower()  # count
        assert "plex" in msg
        assert "frigate" in msg
