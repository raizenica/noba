"""Noba -- Enriched healing notifications.

Formats heal outcomes into rich notification messages with full context:
trigger, evidence, action, result, rollback status, duration, and ledger link.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("noba")


def format_heal_notification(outcome) -> str:
    """Format a heal outcome into an enriched notification message."""
    plan = outcome.plan
    event = plan.request.events[0] if plan.request.events else None

    # Determine risk level
    risk = "unknown"
    try:
        from ..remediation import ACTION_TYPES
        defn = ACTION_TYPES.get(plan.action_type, {})
        risk = defn.get("risk", "unknown")
    except Exception:
        pass

    # Build status line
    if outcome.verified:
        status = "Verified"
        icon = "[OK]"
    elif outcome.action_success is False:
        status = "Action failed"
        icon = "[FAIL]"
    elif outcome.action_success and not outcome.verified:
        status = "Not verified — condition persists"
        icon = "[WARN]"
    else:
        status = "Unknown"
        icon = "[?]"

    lines = [
        f"{icon} HEAL: {plan.action_type}(\"{plan.request.primary_target}\")",
        "",
        f"Trigger:  {event.condition if event else 'unknown'}",
        f"Source:   {event.source if event else 'unknown'} rule \"{event.rule_id if event else ''}\"",
        f"Risk:     {risk}",
        f"Action:   {plan.action_type} (step {plan.escalation_step + 1})",
        f"Trust:    {plan.trust_level}",
        f"Duration: {outcome.duration_s}s",
        f"Result:   {status}",
    ]

    if outcome.verification_detail:
        lines.append(f"Detail:   {outcome.verification_detail}")

    # Metrics before/after
    if outcome.metrics_before:
        lines.append(f"Before:   {_format_metrics(outcome.metrics_before)}")
    if outcome.metrics_after:
        lines.append(f"After:    {_format_metrics(outcome.metrics_after)}")

    # Rollback info
    try:
        from .snapshots import is_reversible
        if is_reversible(plan.action_type):
            lines.append("Rollback: Available (snapshot saved)")
        else:
            lines.append("Rollback: Not available (irreversible)")
    except Exception:
        pass

    if plan.skipped_actions:
        lines.append(f"Skipped:  {', '.join(plan.skipped_actions)}")

    return "\n".join(lines)


def format_approval_notification(plan) -> str:
    """Format an approval request notification."""
    event = plan.request.events[0] if plan.request.events else None

    risk = "unknown"
    try:
        from ..remediation import ACTION_TYPES
        defn = ACTION_TYPES.get(plan.action_type, {})
        risk = defn.get("risk", "unknown")
    except Exception:
        pass

    lines = [
        f"[APPROVAL NEEDED] {plan.action_type}(\"{plan.request.primary_target}\")",
        "",
        f"Action:     {plan.action_type}",
        f"Target:     {plan.request.primary_target}",
        f"Risk:       {risk.upper()}",
        f"Triggered:  {event.condition if event else 'unknown'}",
        f"Source:     {event.source if event else 'unknown'} rule \"{event.rule_id if event else ''}\"",
        f"Escalation: Step {plan.escalation_step + 1}",
        f"Reason:     {plan.reason}",
    ]

    if event and event.metrics:
        lines.append(f"Evidence:   {_format_metrics(event.metrics)}")

    if plan.skipped_actions:
        lines.append(f"Prior:      {', '.join(plan.skipped_actions)} (failed)")

    try:
        from .snapshots import is_reversible
        reversible = is_reversible(plan.action_type)
        lines.append(f"Rollback:   {'Available' if reversible else 'IRREVERSIBLE'}")
    except Exception:
        pass

    return "\n".join(lines)


def format_digest(outcomes: list, period: str = "1 hour") -> str:
    """Format a batch of outcomes into a digest notification."""
    if not outcomes:
        return f"No healing actions in the last {period}."

    verified = sum(1 for o in outcomes if o.verified)
    failed = sum(1 for o in outcomes if o.action_success is False)
    total = len(outcomes)

    targets: set[str] = set()
    actions: dict[str, int] = {}
    for o in outcomes:
        targets.add(o.plan.request.primary_target)
        act = o.plan.action_type
        actions[act] = actions.get(act, 0) + 1

    lines = [
        f"Healing digest ({period}): {total} action(s)",
        f"  Verified: {verified}, Failed: {failed}, Other: {total - verified - failed}",
        f"  Targets: {', '.join(sorted(targets))}",
        f"  Actions: {', '.join(f'{v}x {k}' for k, v in sorted(actions.items()))}",
    ]

    return "\n".join(lines)


def _format_metrics(metrics: dict) -> str:
    """Format a metrics dict into a compact string."""
    if not metrics:
        return "{}"
    parts = []
    for k, v in sorted(metrics.items()):
        if isinstance(v, float):
            parts.append(f"{k}={v:.1f}")
        else:
            parts.append(f"{k}={v}")
    return ", ".join(parts[:5])  # limit to 5 key metrics
