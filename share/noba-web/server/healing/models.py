# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Self-healing pipeline data models."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HealEvent:
    source: str          # "alert", "prediction", "agent", "anomaly"
    rule_id: str
    condition: str
    target: str          # container name, service, hostname
    severity: str
    timestamp: float
    metrics: dict = field(default_factory=dict)


@dataclass
class HealRequest:
    correlation_key: str
    events: list[HealEvent] = field(default_factory=list)
    primary_target: str = ""
    severity: str = "warning"
    created_at: float = 0.0


@dataclass
class HealPlan:
    request: HealRequest
    action_type: str
    action_params: dict = field(default_factory=dict)
    escalation_step: int = 0
    trust_level: str = "notify"
    reason: str = ""
    skipped_actions: list = field(default_factory=list)


@dataclass
class HealOutcome:
    plan: HealPlan
    action_success: bool | None = None
    verified: bool | None = None
    verification_detail: str = ""
    duration_s: float = 0.0
    metrics_before: dict = field(default_factory=dict)
    metrics_after: dict | None = None
    approval_id: int | None = None
    # Extended audit trail: risk_level, snapshot_id, rollback_status,
    # dependency_root, suppressed_by, maintenance_window_id, instance_id
    extra: dict = field(default_factory=dict)


@dataclass
class HealSuggestion:
    category: str
    severity: str = "info"
    message: str = ""
    rule_id: str | None = None
    suggested_action: dict | None = None
    evidence: dict = field(default_factory=dict)


@dataclass
class AgentHealPolicy:
    rules: list[AgentHealRule] = field(default_factory=list)
    version: int = 0
    fallback_mode: str = "queue_for_server"


@dataclass
class AgentHealRule:
    rule_id: str
    condition: str
    action_type: str
    action_params: dict = field(default_factory=dict)
    max_retries: int = 3
    cooldown_s: int = 300
    trust_level: str = "notify"
    fallback_mode: str | None = None
