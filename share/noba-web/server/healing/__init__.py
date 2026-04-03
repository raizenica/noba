# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Self-healing pipeline."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time

from .connectivity_monitor import ConnectivityMonitor
from .correlation import HealCorrelator
from .dependency_graph import DependencyGraph
from .executor import HealExecutor
from .governor import check_circuit_breaker, effective_trust
from .maintenance import MaintenanceManager
from .models import HealEvent, HealOutcome, HealPlan
from .planner import HealPlanner

logger = logging.getLogger("noba")


def dispatch_notifications(
    severity: str, message: str,
    notif_cfg: dict | None = None, channels: list | None = None,
) -> None:
    """Dispatch notifications via the alerts module."""
    try:
        from ..alerts import dispatch_notifications as _dispatch
        from ..yaml_config import read_yaml_settings
        cfg = read_yaml_settings()
        nc = notif_cfg or cfg.get("notifications", {})
        _dispatch(severity, message, nc, channels)
    except Exception as exc:
        logger.error("Heal notification failed: %s", exc)


class HealPipeline:
    """Main pipeline orchestrator. Non-blocking, thread-safe."""

    def __init__(self, db, rules_cfg: dict, settle_times: dict | None = None) -> None:
        self._db = db
        self._rules_cfg = rules_cfg  # {rule_id: {escalation_chain: [...]}}
        self._correlator = HealCorrelator()
        self._planner = HealPlanner()
        self._executor = HealExecutor(settle_times=settle_times)
        self._dep_graph: DependencyGraph | None = None
        self._connectivity = ConnectivityMonitor()
        self._maintenance = self._init_maintenance(db)
        # Dependency-graph signal: "this target is broken" — TTL-based, refreshed
        # on every incoming event. Used by root-cause suppression checks.
        self._active_alerts: dict[str, float] = {}  # target -> expiry timestamp
        self._active_alerts_lock = threading.Lock()
        self._alert_ttl = 300.0  # 5 minutes — ages out when events stop arriving
        # Execution lifecycle: "we are actively healing this target" — precise
        # add-on-execute, remove-on-outcome. Prevents duplicate heals.
        self._active_heals: set[str] = set()
        self._active_heals_lock = threading.Lock()
        self.on_outcome = None  # optional callback for testing

    @staticmethod
    def _init_maintenance(db) -> MaintenanceManager:
        """Create a MaintenanceManager backed by the DB or an in-memory fallback."""
        try:
            conn = db._get_conn()
            lock = db._lock
            if not isinstance(conn, sqlite3.Connection):
                raise TypeError("not a real connection")
        except (AttributeError, TypeError):
            # Tests / mock DB — use a private in-memory SQLite
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute(
                "CREATE TABLE IF NOT EXISTS heal_maintenance_windows ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  target TEXT NOT NULL,"
                "  cron_expr TEXT,"
                "  duration_s INTEGER NOT NULL,"
                "  reason TEXT,"
                "  action TEXT NOT NULL DEFAULT 'suppress',"
                "  active INTEGER NOT NULL DEFAULT 1,"
                "  created_by TEXT,"
                "  created_at INTEGER NOT NULL,"
                "  expires_at INTEGER"
                ")",
            )
            conn.commit()
            lock = threading.Lock()
        return MaintenanceManager(conn, lock)

    def update_rule_config(self, rule_id: str, config: dict) -> None:
        """Update or add a rule's config (thread-safe)."""
        self._rules_cfg[rule_id] = config

    def load_dependency_graph(self, config: list[dict]) -> None:
        """Load dependency graph from YAML config."""
        self._dep_graph = DependencyGraph.from_config(config)
        logger.info("Dependency graph loaded: %d nodes", len(self._dep_graph.all_nodes()))

    def _refresh_alert(self, target: str) -> None:
        """Mark a target as actively failing, extending its TTL."""
        now = time.time()
        with self._active_alerts_lock:
            self._active_alerts[target] = now + self._alert_ttl
            # Sweep expired entries opportunistically
            expired = [t for t, exp in self._active_alerts.items() if exp <= now]
            for t in expired:
                del self._active_alerts[t]

    def _is_alerting(self, target: str) -> bool:
        """Check if a target is currently in the active-alerts set (not expired)."""
        with self._active_alerts_lock:
            exp = self._active_alerts.get(target)
            return exp is not None and exp > time.time()

    def handle_heal_event(self, event: HealEvent) -> None:
        """Non-blocking pipeline entry point. Safe to call from any thread."""
        # Refresh alert TTL on every event — even if absorbed by correlator.
        # This keeps the dependency-graph signal alive as long as events arrive.
        self._refresh_alert(event.target)

        request = self._correlator.correlate(event)
        if request is None:
            return  # absorbed

        # Site isolation check
        if self._dep_graph:
            node = self._dep_graph.get_node(event.target)
            if node and node.site and self._connectivity.should_suppress_healing(node.site):
                logger.info(
                    "Healing suppressed for %s — site %s is connectivity-suspect",
                    event.target, node.site,
                )
                return

            # Root cause check: if any ancestor of this target is also actively
            # failing, this target's failure is likely a downstream symptom — suppress
            if node and node.depends_on:
                with self._active_alerts_lock:
                    now = time.time()
                    current_alerts = {t for t, exp in self._active_alerts.items() if exp > now}

                # Check if any ancestor is failing
                ancestors = self._dep_graph.get_ancestors(event.target)
                failing_ancestors = [a for a in ancestors if a.target in current_alerts]

                if failing_ancestors:
                    # Check if the failing ancestor is external (unhealable)
                    root_ancestor = failing_ancestors[-1]  # highest
                    if root_ancestor.node_type == "external":
                        logger.info(
                            "Healing suppressed for %s — root cause %s is external (unhealable)",
                            event.target, root_ancestor.target,
                        )
                        return

                    # Root cause is a healable service/infra — suppress downstream
                    logger.info(
                        "Healing suppressed for %s — upstream dependency %s is also failing",
                        event.target, failing_ancestors[0].target,
                    )
                    return

        # Maintenance window check
        maint_action = self._maintenance.get_maintenance_action(event.target)
        if maint_action:
            if maint_action in ("suppress", "suppress_all"):
                logger.info("Healing suppressed for %s — in maintenance window", event.target)
                return
            if maint_action == "notify_only":
                # Will be forced to notify path below
                pass

        rule_cfg = self._rules_cfg.get(event.rule_id, {})
        chain = rule_cfg.get("escalation_chain", [
            {"action": "restart_container", "params": {}, "verify_timeout": 30},
        ])

        trust = effective_trust(event.rule_id, event.source, self._db)

        # Maintenance notify_only override
        if maint_action == "notify_only":
            trust = "notify"

        # Check circuit breaker
        if check_circuit_breaker(event.rule_id, self._db):
            trust = "notify"

        # Canary: observation mode — log and return, no event emitted
        if trust == "observation":
            logger.info(
                "Canary observation for rule %s target %s — would have fired",
                event.rule_id, event.target,
            )
            return

        # Canary: dry_run mode — simulate without execution, record as suggestion
        if trust == "dry_run":
            from .dry_run import simulate_heal_event
            sim = simulate_heal_event(event, db=self._db, rules_cfg=self._rules_cfg)
            logger.info(
                "Canary dry-run for rule %s target %s — simulation: %s",
                event.rule_id, event.target, sim.get("would_select", {}),
            )
            try:
                self._db.insert_heal_suggestion(
                    category="canary_dry_run",
                    severity=event.severity,
                    message=f"Dry-run simulation for {event.rule_id} on {event.target}",
                    rule_id=event.rule_id,
                    suggested_action=json.dumps(sim.get("would_select", {})),
                    evidence=sim,
                )
            except Exception as exc:
                logger.debug("Could not record dry-run suggestion: %s", exc)
            return

        plan = self._planner.select_action(request, chain, self._db, effective_trust=trust)
        if plan is None:
            return  # escalation in progress or chain exhausted

        if plan.trust_level == "notify":
            self._handle_notify(plan, event)
        elif plan.trust_level == "approve":
            self._handle_approve(plan, event)
        else:
            self._handle_execute(plan, chain)

    def _handle_notify(self, plan: HealPlan, event: HealEvent) -> None:
        from . import ledger
        outcome = HealOutcome(
            plan=plan, action_success=None, verified=None,
            verification_detail="notify only", duration_s=0,
            metrics_before=event.metrics,
        )
        ledger.record(outcome, self._db)
        dispatch_notifications(plan.request.severity, plan.reason)
        if self.on_outcome:
            self.on_outcome(outcome)
        self._planner.clear_escalation(plan.request.correlation_key)

    def _handle_approve(self, plan: HealPlan, event: HealEvent) -> None:
        from . import ledger
        approval_id = None
        try:
            approval_id = self._db.insert_approval(
                automation_id=event.rule_id,
                trigger=f"heal:{plan.request.correlation_key}",
                trigger_source="healing_pipeline",
                action_type=plan.action_type,
                action_params=plan.action_params,
                target=plan.request.primary_target,
                requested_by=f"heal:{event.source}",
            )
        except Exception as exc:
            logger.error("Heal approval insert failed: %s", exc)

        outcome = HealOutcome(
            plan=plan, action_success=None, verified=None,
            verification_detail="queued for approval", duration_s=0,
            metrics_before=event.metrics, approval_id=approval_id,
        )
        ledger.record(outcome, self._db)
        dispatch_notifications(
            plan.request.severity,
            f"[APPROVAL NEEDED] {plan.reason}",
        )
        if self.on_outcome:
            self.on_outcome(outcome)
        self._planner.clear_escalation(plan.request.correlation_key)

    def _handle_execute(self, plan: HealPlan, chain: list[dict]) -> None:
        from . import ledger
        target = plan.request.primary_target

        with self._active_heals_lock:
            self._active_heals.add(target)

        def on_complete(outcome: HealOutcome) -> None:
            ledger.record(outcome, self._db)
            if self.on_outcome:
                self.on_outcome(outcome)

            if outcome.verified:
                with self._active_heals_lock:
                    self._active_heals.discard(target)
                # Clear the alert signal — target recovered
                with self._active_alerts_lock:
                    self._active_alerts.pop(target, None)
                self._planner.clear_escalation(plan.request.correlation_key)
                return

            # Escalation
            trust = effective_trust(
                plan.request.events[0].rule_id if plan.request.events else "",
                plan.request.events[0].source if plan.request.events else "alert",
                self._db,
            )
            next_plan = self._planner.advance(outcome, chain, self._db, effective_trust=trust)
            if next_plan:
                self._executor.execute(next_plan, on_complete=on_complete)
            else:
                # Escalation chain exhausted — clean up execution tracker
                with self._active_heals_lock:
                    self._active_heals.discard(target)

        self._executor.execute(plan, on_complete=on_complete)


_singleton: HealPipeline | None = None
_singleton_lock = threading.Lock()


def create_pipeline(db, rules_cfg: dict, settle_times: dict | None = None) -> HealPipeline:
    """Factory function for creating a pipeline instance (used in tests)."""
    return HealPipeline(db, rules_cfg, settle_times=settle_times)


def get_pipeline() -> HealPipeline:
    """Get or create the module-level singleton pipeline.

    Uses the shared DB instance from deps. Correlation and escalation state
    persist across calls — this is critical for correct behavior.
    """
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                from ..db import db as _db
                _singleton = HealPipeline(_db, {})
    return _singleton
