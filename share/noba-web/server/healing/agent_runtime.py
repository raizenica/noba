# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Agent heal runtime: policy distribution and report ingestion."""
from __future__ import annotations

import hashlib
import json
import logging

logger = logging.getLogger("noba")

_LOW_RISK_TYPES = frozenset({"restart_container", "restart_service", "clear_cache", "flush_dns"})


def build_agent_policy(hostname: str, rules_cfg: dict, db) -> dict:
    """Build a lightweight heal policy for a specific agent."""
    agent_rules: list[dict] = []

    for rule_id, cfg in rules_cfg.items():
        chain = cfg.get("escalation_chain", [])
        for step in chain:
            action = step.get("action", "")
            if action not in _LOW_RISK_TYPES:
                continue
            state = db.get_trust_state(rule_id)
            trust = state["current_level"] if state else "notify"
            agent_rules.append({
                "rule_id": rule_id,
                "condition": cfg.get("condition", ""),
                "action_type": action,
                "action_params": step.get("params", {}),
                "max_retries": 3,
                "cooldown_s": 300,
                "trust_level": trust,
                "fallback_mode": None,
            })

    version = hashlib.sha256(
        json.dumps(agent_rules, sort_keys=True).encode()
    ).hexdigest()[:12]

    return {
        "rules": agent_rules,
        "version": version,
        "fallback_mode": "queue_for_server",
    }


def ingest_agent_heal_reports(hostname: str, reports: list[dict], db) -> None:
    """Process heal outcomes reported by agents and feed into ledger."""
    for report in reports:
        try:
            db.insert_heal_outcome(
                correlation_key=f"agent:{hostname}:{report.get('rule_id', '')}",
                rule_id=report.get("rule_id", ""),
                condition=report.get("condition", ""),
                target=hostname,
                action_type=report.get("action_type", ""),
                action_params=report.get("action_params", {}),
                escalation_step=0,
                action_success=report.get("success", False),
                verified=report.get("verified", False),
                duration_s=report.get("duration_s", 0),
                metrics_before=report.get("metrics_before", {}),
                metrics_after=report.get("metrics_after", {}),
                trust_level=report.get("trust_level", "execute"),
                source="agent",
                approval_id=None,
            )
        except Exception as exc:
            logger.error("Failed to ingest agent heal report from %s: %s", hostname, exc)
