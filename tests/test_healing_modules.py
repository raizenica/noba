# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing modules: registry, rules, graph, approval, predictive,
dry-run, notifications, auto-discovery, watchdog, governor, ledger, agent-verify."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(**overrides):
    from server.healing.models import HealEvent
    defaults = dict(
        source="alert", rule_id="r1", condition="cpu_percent > 90",
        target="nginx", severity="warning",
        timestamp=time.time(), metrics={"cpu_percent": 95},
    )
    defaults.update(overrides)
    return HealEvent(**defaults)


def _make_request(**overrides):
    from server.healing.models import HealRequest
    event = _make_event()
    defaults = dict(
        correlation_key="nginx", events=[event],
        primary_target="nginx", severity="warning",
        created_at=time.time(),
    )
    defaults.update(overrides)
    return HealRequest(**defaults)


def _make_plan(**overrides):
    from server.healing.models import HealPlan
    request = _make_request()
    defaults = dict(
        request=request, action_type="restart_container",
        action_params={"container": "nginx"},
        escalation_step=0, trust_level="execute",
    )
    defaults.update(overrides)
    return HealPlan(**defaults)


def _make_outcome(**overrides):
    from server.healing.models import HealOutcome
    plan = _make_plan()
    defaults = dict(
        plan=plan, action_success=True, verified=True,
        verification_detail="resolved", duration_s=2.0,
        metrics_before={"cpu_percent": 95},
        metrics_after={"cpu_percent": 40},
    )
    defaults.update(overrides)
    return HealOutcome(**defaults)


# ===================================================================
# 1. Integration registry
# ===================================================================

class TestIntegrationRegistry:
    def test_handler_lookup_known_operation_platform(self):
        from server.healing.integration_registry import get_integration_handler
        # CF-10: TrueNAS nas_scrub no longer references the fictional REST
        # `/api/v2.0/pool/id/{pool}/scrub` endpoint — it's now an exec cell
        # calling `zpool scrub` directly, which is the real ZFS command
        # that every TrueNAS release supports regardless of REST / WebSocket
        # API version. Verifying the cell is still present and executable.
        handler = get_integration_handler("nas_scrub", "truenas")
        assert handler is not None
        assert handler["method"] == "exec"
        assert "zpool scrub" in handler["command"]

    def test_handler_lookup_missing_platform(self):
        from server.healing.integration_registry import get_integration_handler
        assert get_integration_handler("nas_scrub", "nonexistent") is None

    def test_handler_lookup_missing_operation(self):
        from server.healing.integration_registry import get_integration_handler
        assert get_integration_handler("totally_fake_op", "truenas") is None

    def test_list_operations_for_category(self):
        from server.healing.integration_registry import list_operations
        ops = list_operations("nas")
        assert "nas_scrub" in ops
        assert "nas_pool_repair" in ops

    def test_list_operations_empty_category(self):
        from server.healing.integration_registry import list_operations
        assert list_operations("nonexistent_category") == []

    def test_list_platforms_for_operation(self):
        from server.healing.integration_registry import list_platforms
        platforms = list_platforms("vm_restart")
        assert "proxmox" in platforms
        assert "vmware" in platforms

    def test_list_platforms_unknown_operation(self):
        from server.healing.integration_registry import list_platforms
        assert list_platforms("fake_op") == []

    def test_list_categories(self):
        from server.healing.integration_registry import list_categories
        cats = list_categories()
        assert "nas" in cats
        assert "hypervisor" in cats
        assert "container_runtime" in cats

    def test_register_custom_handler(self):
        from server.healing.integration_registry import (
            register_handler, get_integration_handler,
        )
        register_handler("custom_op", "custom_platform", {"method": "GET", "endpoint": "/test"})
        handler = get_integration_handler("custom_op", "custom_platform")
        assert handler is not None
        assert handler["method"] == "GET"

    def test_register_handler_overwrites(self):
        from server.healing.integration_registry import (
            register_handler, get_integration_handler,
        )
        register_handler("overwrite_op", "plat", {"version": 1})
        register_handler("overwrite_op", "plat", {"version": 2})
        assert get_integration_handler("overwrite_op", "plat")["version"] == 2

    def test_capability_discovery_across_platforms(self):
        """All NAS platforms support nas_scrub."""
        from server.healing.integration_registry import list_platforms
        platforms = list_platforms("nas_scrub")
        for expected in ("truenas", "synology", "qnap", "omv", "unraid"):
            assert expected in platforms


# ===================================================================
# 2. Default rules
# ===================================================================

class TestDefaultRules:
    def test_get_chain_for_scenario_cpu(self):
        from server.healing.default_rules import get_chain_for_scenario
        chain = get_chain_for_scenario("cpu_critical")
        assert chain is not None
        assert chain["severity"] == "danger"
        assert len(chain["escalation_chain"]) >= 1

    def test_get_chain_missing_scenario(self):
        from server.healing.default_rules import get_chain_for_scenario
        assert get_chain_for_scenario("totally_fake") is None

    def test_get_chain_for_rule_id_cpu_crit(self):
        from server.healing.default_rules import get_chain_for_rule_id
        chain = get_chain_for_rule_id("cpu_crit_host1")
        assert chain is not None
        assert chain[0]["action"] == "process_kill"

    def test_get_chain_for_rule_id_service(self):
        from server.healing.default_rules import get_chain_for_rule_id
        chain = get_chain_for_rule_id("svc_nginx")
        assert chain is not None
        assert chain[0]["action"] == "service_reset_failed"

    def test_get_chain_for_rule_id_container(self):
        from server.healing.default_rules import get_chain_for_rule_id
        chain = get_chain_for_rule_id("container_postgres")
        assert chain is not None
        assert chain[0]["action"] == "restart_container"

    def test_get_chain_for_rule_id_no_match(self):
        from server.healing.default_rules import get_chain_for_rule_id
        assert get_chain_for_rule_id("unknown_xyz") is None

    def test_priority_ordering_disk_critical(self):
        """Disk critical chain starts with temp_cleanup (low-risk), escalates."""
        from server.healing.default_rules import get_chain_for_scenario
        chain = get_chain_for_scenario("disk_critical")
        actions = [step["action"] for step in chain["escalation_chain"]]
        assert actions[0] == "temp_cleanup"
        assert len(actions) >= 3

    def test_all_chains_have_escalation_chain(self):
        from server.healing.default_rules import DEFAULT_CHAINS
        for scenario, cfg in DEFAULT_CHAINS.items():
            assert "escalation_chain" in cfg, f"{scenario} missing escalation_chain"
            assert len(cfg["escalation_chain"]) >= 1

    def test_all_chains_have_default_autonomy(self):
        from server.healing.default_rules import DEFAULT_CHAINS
        for scenario, cfg in DEFAULT_CHAINS.items():
            assert cfg["default_autonomy"] == "notify"

    def test_dns_chain_matches_dns_rule(self):
        from server.healing.default_rules import get_chain_for_rule_id
        chain = get_chain_for_rule_id("dns_pihole_down")
        assert chain is not None
        assert chain[0]["action"] == "flush_dns"


# ===================================================================
# 3. Dependency graph
# ===================================================================

class TestDependencyGraph:
    def test_add_and_get_node(self):
        from server.healing.dependency_graph import DependencyGraph
        g = DependencyGraph()
        g.add_node("nginx", node_type="service", site="site-a")
        node = g.get_node("nginx")
        assert node is not None
        assert node.node_type == "service"
        assert node.site == "site-a"

    def test_get_missing_node(self):
        from server.healing.dependency_graph import DependencyGraph
        g = DependencyGraph()
        assert g.get_node("ghost") is None

    def test_edge_creation_depends_on(self):
        from server.healing.dependency_graph import DependencyGraph
        g = DependencyGraph()
        g.add_node("db")
        g.add_node("webapp", depends_on=["db"])
        node = g.get_node("webapp")
        assert "db" in node.depends_on

    def test_get_dependents(self):
        from server.healing.dependency_graph import DependencyGraph
        g = DependencyGraph()
        g.add_node("db")
        g.add_node("webapp", depends_on=["db"])
        g.add_node("cache", depends_on=["db"])
        dependents = g.get_dependents("db")
        names = {d.target for d in dependents}
        assert names == {"webapp", "cache"}

    def test_get_ancestors(self):
        from server.healing.dependency_graph import DependencyGraph
        g = DependencyGraph()
        g.add_node("network")
        g.add_node("db", depends_on=["network"])
        g.add_node("webapp", depends_on=["db"])
        ancestors = g.get_ancestors("webapp")
        names = {a.target for a in ancestors}
        assert names == {"db", "network"}

    def test_blast_radius_descendants(self):
        from server.healing.dependency_graph import DependencyGraph
        g = DependencyGraph()
        g.add_node("network")
        g.add_node("db", depends_on=["network"])
        g.add_node("webapp", depends_on=["db"])
        g.add_node("api", depends_on=["db"])
        descendants = g.get_all_descendants("network")
        assert descendants == {"db", "webapp", "api"}

    def test_cycle_detection_ancestors(self):
        """Cycles should not cause infinite recursion."""
        from server.healing.dependency_graph import DependencyGraph
        g = DependencyGraph()
        g.add_node("a", depends_on=["b"])
        g.add_node("b", depends_on=["a"])
        ancestors = g.get_ancestors("a")
        names = {a.target for a in ancestors}
        assert "b" in names

    def test_cycle_detection_descendants(self):
        from server.healing.dependency_graph import DependencyGraph
        g = DependencyGraph()
        g.add_node("a", depends_on=["b"])
        g.add_node("b", depends_on=["a"])
        descendants = g.get_all_descendants("a")
        assert "b" in descendants

    def test_root_cause_resolution(self):
        from server.healing.dependency_graph import DependencyGraph, resolve_root_cause
        g = DependencyGraph()
        g.add_node("network")
        g.add_node("db", depends_on=["network"])
        g.add_node("webapp", depends_on=["db"])
        root, suppressed = resolve_root_cause(g, {"network", "db", "webapp"})
        assert root == "network"
        assert suppressed == {"db", "webapp"}

    def test_root_cause_empty_set(self):
        from server.healing.dependency_graph import DependencyGraph, resolve_root_cause
        g = DependencyGraph()
        root, suppressed = resolve_root_cause(g, set())
        assert root is None
        assert suppressed == set()

    def test_root_cause_independent_failures(self):
        from server.healing.dependency_graph import DependencyGraph, resolve_root_cause
        g = DependencyGraph()
        g.add_node("dns")
        g.add_node("vpn")
        root, suppressed = resolve_root_cause(g, {"dns", "vpn"})
        assert root in ("dns", "vpn")
        assert suppressed == set()

    def test_from_config(self):
        from server.healing.dependency_graph import DependencyGraph
        cfg = [
            {"target": "db", "type": "service", "site": "site-a"},
            {"target": "app", "type": "service", "depends_on": ["db"]},
        ]
        g = DependencyGraph.from_config(cfg)
        assert g.get_node("db") is not None
        assert g.get_node("app").depends_on == ["db"]

    def test_to_dict_roundtrip(self):
        from server.healing.dependency_graph import DependencyGraph
        g = DependencyGraph()
        g.add_node("db", site="site-a")
        g.add_node("app", depends_on=["db"])
        data = g.to_dict()
        g2 = DependencyGraph.from_config(data)
        assert g2.get_node("db") is not None
        assert g2.get_node("app").depends_on == ["db"]

    def test_get_site_targets(self):
        from server.healing.dependency_graph import DependencyGraph
        g = DependencyGraph()
        g.add_node("a", site="site-a")
        g.add_node("b", site="site-b")
        g.add_node("c", site="site-a")
        targets = g.get_site_targets("site-a")
        names = {t.target for t in targets}
        assert names == {"a", "c"}


# ===================================================================
# 4. Approval manager
# ===================================================================

class TestApprovalManager:
    def test_auto_approval_low_risk_execute(self):
        from server.healing.approval_manager import determine_approval_requirement
        assert determine_approval_requirement("restart_container", "low", "execute") == "auto"

    def test_auto_notify_medium_risk_execute(self):
        from server.healing.approval_manager import determine_approval_requirement
        assert determine_approval_requirement("restart_container", "medium", "execute") == "auto_notify"

    def test_required_high_risk_execute(self):
        from server.healing.approval_manager import determine_approval_requirement
        assert determine_approval_requirement("restart_container", "high", "execute") == "required"

    def test_required_approve_trust(self):
        from server.healing.approval_manager import determine_approval_requirement
        assert determine_approval_requirement("restart_container", "low", "approve") == "required"

    def test_notify_only_trust(self):
        from server.healing.approval_manager import determine_approval_requirement
        assert determine_approval_requirement("restart_container", "low", "notify") == "notify"

    def test_escalation_chain_no_approvers(self):
        from server.healing.approval_manager import resolve_escalation_chain
        result = resolve_escalation_chain(admin_count=0, operator_count=0)
        assert result == {"action": "auto_deny"}

    def test_escalation_chain_single_admin(self):
        from server.healing.approval_manager import resolve_escalation_chain
        result = resolve_escalation_chain(admin_count=1, operator_count=0)
        assert result["stages"] == ["admin"]
        assert result["use_cooldown"] is True

    def test_escalation_chain_full_staff(self):
        from server.healing.approval_manager import resolve_escalation_chain
        result = resolve_escalation_chain(admin_count=2, operator_count=3)
        assert result["stages"] == ["operator", "admin"]
        assert result["use_cooldown"] is False

    def test_escalation_chain_operators_only(self):
        from server.healing.approval_manager import resolve_escalation_chain
        result = resolve_escalation_chain(admin_count=0, operator_count=2)
        assert result["stages"] == ["operator"]
        assert result["use_cooldown"] is False

    def test_emergency_override_disabled(self):
        from server.healing.approval_manager import check_emergency_override
        assert check_emergency_override(
            {"enabled": False}, "critical", 5, 30.0,
        ) is False

    def test_emergency_override_all_conditions_met(self):
        from server.healing.approval_manager import check_emergency_override
        config = {
            "enabled": True,
            "conditions": {
                "severity": "critical",
                "consecutive_failures": 3,
                "no_response_minutes": 15,
            },
        }
        assert check_emergency_override(config, "critical", 5, 30.0) is True

    def test_emergency_override_severity_too_low(self):
        from server.healing.approval_manager import check_emergency_override
        config = {
            "enabled": True,
            "conditions": {"severity": "critical"},
        }
        assert check_emergency_override(config, "warning", 5, 30.0) is False

    def test_emergency_override_insufficient_failures(self):
        from server.healing.approval_manager import check_emergency_override
        config = {
            "enabled": True,
            "conditions": {"consecutive_failures": 5},
        }
        assert check_emergency_override(config, "critical", 2, 30.0) is False

    def test_emergency_override_insufficient_wait(self):
        from server.healing.approval_manager import check_emergency_override
        config = {
            "enabled": True,
            "conditions": {"no_response_minutes": 30},
        }
        assert check_emergency_override(config, "critical", 5, 10.0) is False

    def test_emergency_override_enabled_no_conditions(self):
        from server.healing.approval_manager import check_emergency_override
        config = {"enabled": True, "conditions": {}}
        assert check_emergency_override(config, "info", 0, 0.0) is True

    @patch("server.remediation.ACTION_TYPES", {
        "restart_container": {"risk": "low", "reversible": True, "has_rollback": True, "description": "Restart container"},
    })
    def test_build_approval_context(self):
        from server.healing.approval_manager import build_approval_context
        plan = _make_plan(reason="escalation step 1")
        event = _make_event()
        ctx = build_approval_context(plan, event)
        assert ctx["action_type"] == "restart_container"
        assert ctx["risk"] == "low"
        assert ctx["reversible"] is True
        assert ctx["rollback_available"] is True
        assert ctx["evidence"]["source"] == "alert"
        assert ctx["target"] == "nginx"


# ===================================================================
# 5. Predictive
# ===================================================================

class TestPredictive:
    def test_is_data_stale_true(self):
        from server.healing.predictive import is_data_stale
        old = time.time() - 20
        assert is_data_stale(old, collect_interval=5.0) is True

    def test_is_data_stale_false(self):
        from server.healing.predictive import is_data_stale
        recent = time.time() - 1
        assert is_data_stale(recent, collect_interval=5.0) is False

    @patch("server.healing.predictive._run_prediction")
    def test_evaluate_predictions_within_24h(self, mock_pred):
        from server.healing.predictive import evaluate_predictions
        from datetime import datetime, timedelta
        future = (datetime.now() + timedelta(hours=12)).isoformat()
        mock_pred.return_value = {
            "metrics": {},
            "combined": {
                "full_at": future,
                "primary_metric": "disk_percent",
                "confidence": "high",
                "slope_per_day": 5.0,
            },
        }
        events = evaluate_predictions(metric_groups={"disk": ["disk_percent"]})
        assert len(events) == 1
        assert events[0].severity == "warning"
        assert events[0].source == "prediction"

    @patch("server.healing.predictive._run_prediction")
    def test_evaluate_predictions_within_72h(self, mock_pred):
        from server.healing.predictive import evaluate_predictions
        from datetime import datetime, timedelta
        future = (datetime.now() + timedelta(hours=48)).isoformat()
        mock_pred.return_value = {
            "metrics": {},
            "combined": {
                "full_at": future,
                "primary_metric": "disk_percent",
                "confidence": "medium",
                "slope_per_day": 2.0,
            },
        }
        events = evaluate_predictions(metric_groups={"disk": ["disk_percent"]})
        assert len(events) == 1
        assert events[0].severity == "info"

    @patch("server.healing.predictive._run_prediction")
    def test_evaluate_predictions_beyond_horizon(self, mock_pred):
        from server.healing.predictive import evaluate_predictions
        from datetime import datetime, timedelta
        far_future = (datetime.now() + timedelta(hours=200)).isoformat()
        mock_pred.return_value = {
            "metrics": {},
            "combined": {"full_at": far_future},
        }
        events = evaluate_predictions(metric_groups={"disk": ["disk_percent"]})
        assert len(events) == 0

    @patch("server.healing.predictive._run_prediction")
    def test_evaluate_predictions_no_full_at(self, mock_pred):
        from server.healing.predictive import evaluate_predictions
        mock_pred.return_value = {"metrics": {}, "combined": {"full_at": None}}
        events = evaluate_predictions(metric_groups={"disk": ["disk_percent"]})
        assert len(events) == 0

    @patch("server.healing.predictive._check_anomalies")
    def test_evaluate_anomalies_cpu(self, mock_anomalies):
        from server.healing.predictive import evaluate_anomalies
        mock_anomalies.return_value = [
            {"msg": "Anomaly: CPU at 98%", "level": "warning"},
        ]
        events = evaluate_anomalies()
        assert len(events) == 1
        assert events[0].source == "anomaly"
        assert "cpu_percent" in events[0].target

    @patch("server.healing.predictive._check_anomalies")
    def test_evaluate_anomalies_empty(self, mock_anomalies):
        from server.healing.predictive import evaluate_anomalies
        mock_anomalies.return_value = []
        assert evaluate_anomalies() == []

    @patch("server.healing.predictive.evaluate_anomalies")
    @patch("server.healing.predictive.evaluate_predictions")
    def test_run_predictive_cycle_stale_data(self, mock_pred, mock_anom):
        from server.healing.predictive import run_predictive_cycle
        stale_time = time.time() - 60
        events = run_predictive_cycle(last_collect_time=stale_time, collect_interval=5.0)
        assert events == []
        mock_pred.assert_not_called()
        mock_anom.assert_not_called()

    @patch("server.healing.predictive.evaluate_anomalies", return_value=[])
    @patch("server.healing.predictive.evaluate_predictions", return_value=[])
    def test_run_predictive_cycle_fresh_data(self, mock_pred, mock_anom):
        from server.healing.predictive import run_predictive_cycle
        fresh_time = time.time() - 1
        events = run_predictive_cycle(last_collect_time=fresh_time, collect_interval=5.0)
        assert events == []
        mock_pred.assert_called_once()
        mock_anom.assert_called_once()


# ===================================================================
# 6. Dry run
# ===================================================================

class TestDryRun:
    @patch("server.healing.dry_run.HealPlanner")
    @patch("server.healing.dry_run.HealCorrelator")
    def test_simulate_maintenance_suppression(self, mock_corr_cls, mock_planner_cls):
        from server.healing.dry_run import simulate_heal_event
        event = _make_event()
        result = simulate_heal_event(event, in_maintenance=True)
        assert result["suppressed"] is True
        assert "maintenance" in result["suppression_reason"].lower()

    @patch("server.healing.dry_run.HealPlanner")
    @patch("server.healing.dry_run.HealCorrelator")
    def test_simulate_no_correlation(self, mock_corr_cls, mock_planner_cls):
        from server.healing.dry_run import simulate_heal_event
        mock_corr_cls.return_value.correlate.return_value = None
        event = _make_event()
        result = simulate_heal_event(event)
        assert result["would_correlate"] is False

    @patch("server.healing.snapshots.is_reversible", return_value=False)
    @patch("server.remediation.ACTION_TYPES", {"restart_container": {"risk": "low"}})
    @patch("server.remediation.FALLBACK_CHAINS", {})
    @patch("server.healing.dry_run.effective_trust", return_value="execute")
    @patch("server.healing.dry_run.HealPlanner")
    @patch("server.healing.dry_run.HealCorrelator")
    def test_simulate_produces_action_selection(
        self, mock_corr_cls, mock_planner_cls, *_mocks,
    ):
        from server.healing.dry_run import simulate_heal_event
        request = _make_request()
        mock_corr_cls.return_value.correlate.return_value = request
        plan = _make_plan()
        mock_planner_cls.return_value.select_action.return_value = plan
        event = _make_event()
        result = simulate_heal_event(event)
        assert result["would_correlate"] is True
        assert result["would_select"]["action"] == "restart_container"

    def test_simulate_result_has_required_keys(self):
        """Even a maintenance-suppressed result has all expected keys."""
        from server.healing.dry_run import simulate_heal_event
        event = _make_event()
        result = simulate_heal_event(event, in_maintenance=True)
        for key in ("event", "timestamp", "suppressed", "suppression_reason",
                     "would_correlate", "dependency_analysis", "would_select",
                     "pre_flight", "rollback_plan"):
            assert key in result, f"Missing key: {key}"


# ===================================================================
# 7. Notifications
# ===================================================================

class TestNotifications:
    @patch("server.remediation.ACTION_TYPES", {
        "restart_container": {"risk": "low"},
    })
    @patch("server.healing.snapshots.is_reversible", return_value=True)
    def test_format_heal_notification_verified(self, mock_rev):
        from server.healing.notifications import format_heal_notification
        outcome = _make_outcome()
        msg = format_heal_notification(outcome)
        assert "[OK]" in msg
        assert "Verified" in msg
        assert "restart_container" in msg
        assert "nginx" in msg

    @patch("server.remediation.ACTION_TYPES", {
        "restart_container": {"risk": "low"},
    })
    @patch("server.healing.snapshots.is_reversible", return_value=False)
    def test_format_heal_notification_failed(self, mock_rev):
        from server.healing.notifications import format_heal_notification
        outcome = _make_outcome(action_success=False, verified=False)
        msg = format_heal_notification(outcome)
        assert "[FAIL]" in msg
        assert "Action failed" in msg

    @patch("server.remediation.ACTION_TYPES", {
        "restart_container": {"risk": "low"},
    })
    @patch("server.healing.snapshots.is_reversible", return_value=False)
    def test_format_heal_notification_unverified(self, mock_rev):
        from server.healing.notifications import format_heal_notification
        outcome = _make_outcome(action_success=True, verified=False)
        msg = format_heal_notification(outcome)
        assert "[WARN]" in msg
        assert "condition persists" in msg

    @patch("server.remediation.ACTION_TYPES", {
        "restart_container": {"risk": "high"},
    })
    @patch("server.healing.snapshots.is_reversible", return_value=False)
    def test_format_approval_notification(self, mock_rev):
        from server.healing.notifications import format_approval_notification
        plan = _make_plan(reason="escalation needed")
        msg = format_approval_notification(plan)
        assert "[APPROVAL NEEDED]" in msg
        assert "restart_container" in msg
        assert "nginx" in msg

    def test_format_digest_empty(self):
        from server.healing.notifications import format_digest
        msg = format_digest([], period="1 hour")
        assert "No healing actions" in msg

    def test_format_digest_with_outcomes(self):
        from server.healing.notifications import format_digest
        o1 = _make_outcome(verified=True, action_success=True)
        o2 = _make_outcome(verified=False, action_success=False)
        msg = format_digest([o1, o2], period="1 hour")
        assert "2 action(s)" in msg
        assert "Verified: 1" in msg
        assert "Failed: 1" in msg

    def test_format_metrics_compact(self):
        from server.healing.notifications import _format_metrics
        result = _format_metrics({"cpu": 95.123, "mem": 80})
        assert "cpu=95.1" in result
        assert "mem=80" in result

    def test_format_metrics_empty(self):
        from server.healing.notifications import _format_metrics
        assert _format_metrics({}) == "{}"


# ===================================================================
# 8. Auto discovery
# ===================================================================

class TestAutoDiscovery:
    def test_detect_co_failures_basic(self):
        from server.healing.auto_discovery import detect_co_failures
        now = int(time.time())
        outcomes = []
        for i in range(5):
            outcomes.append({"target": "db", "created_at": now + i * 10})
            outcomes.append({"target": "webapp", "created_at": now + i * 10 + 5})
        results = detect_co_failures(outcomes, window_s=120, min_co_occurrences=3)
        assert len(results) >= 1
        targets = results[0]["targets"]
        assert "db" in targets
        assert "webapp" in targets

    def test_detect_co_failures_below_threshold(self):
        from server.healing.auto_discovery import detect_co_failures
        now = int(time.time())
        outcomes = [
            {"target": "db", "created_at": now},
            {"target": "webapp", "created_at": now + 5},
        ]
        results = detect_co_failures(outcomes, window_s=120, min_co_occurrences=3)
        assert len(results) == 0

    def test_detect_co_failures_outside_window(self):
        from server.healing.auto_discovery import detect_co_failures
        now = int(time.time())
        outcomes = []
        for i in range(5):
            outcomes.append({"target": "db", "created_at": now + i * 1000})
            outcomes.append({"target": "webapp", "created_at": now + i * 1000 + 500})
        results = detect_co_failures(outcomes, window_s=120, min_co_occurrences=3)
        assert len(results) == 0

    def test_generate_dependency_suggestions(self):
        from server.healing.auto_discovery import generate_dependency_suggestions
        co_failures = [
            {"targets": ["db", "webapp"], "count": 5, "percentage": 83.3},
        ]
        suggestions = generate_dependency_suggestions(co_failures)
        assert len(suggestions) == 1
        assert suggestions[0]["category"] == "dependency_candidate"
        assert "db" in suggestions[0]["message"]
        assert "webapp" in suggestions[0]["message"]

    def test_run_auto_discovery_integration(self):
        from server.healing.auto_discovery import run_auto_discovery
        mock_db = MagicMock()
        now = int(time.time())
        outcomes = []
        for i in range(5):
            outcomes.append({"target": "db", "created_at": now + i * 10})
            outcomes.append({"target": "webapp", "created_at": now + i * 10 + 5})
        mock_db.get_heal_outcomes.return_value = outcomes
        count = run_auto_discovery(mock_db)
        assert count >= 1
        assert mock_db.insert_heal_suggestion.called

    def test_run_auto_discovery_handles_exception(self):
        from server.healing.auto_discovery import run_auto_discovery
        mock_db = MagicMock()
        mock_db.get_heal_outcomes.side_effect = RuntimeError("db fail")
        count = run_auto_discovery(mock_db)
        assert count == 0

    def test_detect_co_failures_empty_outcomes(self):
        from server.healing.auto_discovery import detect_co_failures
        assert detect_co_failures([]) == []


# ===================================================================
# 9. Watchdog
# ===================================================================

class TestWatchdog:
    def test_register_and_heartbeat(self):
        from server.healing.watchdog import ComponentWatchdog
        wd = ComponentWatchdog()
        wd.register("collector", interval=5.0)
        wd.heartbeat("collector")
        status = wd.get_status("collector")
        assert status is not None
        assert status["healthy"] is True

    def test_stale_component_detected(self):
        from server.healing.watchdog import ComponentWatchdog
        wd = ComponentWatchdog()
        wd.register("collector", interval=0.01, tolerance=1)
        # Simulate time passing by manipulating last_heartbeat
        with wd._lock:
            wd._components["collector"]["last_heartbeat"] = time.time() - 10
        results = wd.check_all()
        assert results["collector"] is False

    def test_healthy_component(self):
        from server.healing.watchdog import ComponentWatchdog
        wd = ComponentWatchdog()
        wd.register("collector", interval=60.0, tolerance=3)
        wd.heartbeat("collector")
        results = wd.check_all()
        assert results["collector"] is True

    def test_degraded_mode_threshold(self):
        from server.healing.watchdog import ComponentWatchdog
        wd = ComponentWatchdog()
        for i in range(4):
            wd.register(f"comp_{i}", interval=0.01, tolerance=1)
            with wd._lock:
                wd._components[f"comp_{i}"]["last_heartbeat"] = time.time() - 10
        wd.check_all()
        assert wd.is_degraded() is True

    def test_not_degraded_below_threshold(self):
        from server.healing.watchdog import ComponentWatchdog
        wd = ComponentWatchdog()
        wd.register("healthy1", interval=60.0, tolerance=3)
        wd.register("healthy2", interval=60.0, tolerance=3)
        wd.heartbeat("healthy1")
        wd.heartbeat("healthy2")
        wd.check_all()
        assert wd.is_degraded() is False

    def test_on_failure_callback(self):
        from server.healing.watchdog import ComponentWatchdog
        wd = ComponentWatchdog()
        called = []
        wd.register("collector", interval=0.01, tolerance=1, on_failure=lambda name: called.append(name))
        with wd._lock:
            wd._components["collector"]["last_heartbeat"] = time.time() - 10
        wd.check_all()
        assert "collector" in called

    def test_list_components(self):
        from server.healing.watchdog import ComponentWatchdog
        wd = ComponentWatchdog()
        wd.register("a", interval=5.0)
        wd.register("b", interval=5.0)
        assert sorted(wd.list_components()) == ["a", "b"]

    def test_get_health_summary(self):
        from server.healing.watchdog import ComponentWatchdog
        wd = ComponentWatchdog()
        wd.register("a", interval=60.0)
        wd.heartbeat("a")
        wd.check_all()
        summary = wd.get_health_summary()
        assert "a" in summary
        assert summary["a"]["healthy"] is True
        assert "degraded" in summary

    def test_heartbeat_resets_failure_count(self):
        from server.healing.watchdog import ComponentWatchdog
        wd = ComponentWatchdog()
        wd.register("comp", interval=0.01, tolerance=1)
        with wd._lock:
            wd._components["comp"]["last_heartbeat"] = time.time() - 10
        wd.check_all()
        status = wd.get_status("comp")
        assert status["failure_count"] == 1
        wd.heartbeat("comp")
        status = wd.get_status("comp")
        assert status["failure_count"] == 0

    def test_get_status_unknown_component(self):
        from server.healing.watchdog import ComponentWatchdog
        wd = ComponentWatchdog()
        assert wd.get_status("ghost") is None

    def test_heartbeat_unknown_component_noop(self):
        from server.healing.watchdog import ComponentWatchdog
        wd = ComponentWatchdog()
        wd.heartbeat("ghost")  # should not raise


# ===================================================================
# 10. Governor
# ===================================================================

class TestGovernor:
    def test_effective_trust_normal_source(self):
        from server.healing.governor import effective_trust
        mock_db = MagicMock()
        mock_db.get_trust_state.return_value = {"current_level": "execute"}
        assert effective_trust("r1", "alert", mock_db) == "execute"

    def test_effective_trust_prediction_source_demoted(self):
        from server.healing.governor import effective_trust
        mock_db = MagicMock()
        mock_db.get_trust_state.return_value = {"current_level": "execute"}
        result = effective_trust("r1", "prediction", mock_db)
        assert result == "approve"

    def test_effective_trust_prediction_at_notify_stays_notify(self):
        from server.healing.governor import effective_trust
        mock_db = MagicMock()
        mock_db.get_trust_state.return_value = {"current_level": "notify"}
        result = effective_trust("r1", "prediction", mock_db)
        assert result == "notify"

    def test_effective_trust_no_state_returns_notify(self):
        from server.healing.governor import effective_trust
        mock_db = MagicMock()
        mock_db.get_trust_state.return_value = None
        assert effective_trust("r1", "alert", mock_db) == "notify"

    def test_circuit_breaker_trips_on_failures(self):
        from server.healing.governor import check_circuit_breaker
        mock_db = MagicMock()
        now = int(time.time())
        mock_db.get_heal_outcomes.return_value = [
            {"created_at": now - 100, "action_success": True, "verified": 0},
            {"created_at": now - 200, "action_success": True, "verified": 0},
            {"created_at": now - 300, "action_success": True, "verified": 0},
        ]
        mock_db.get_trust_state.return_value = {"current_level": "execute", "ceiling": "execute"}
        result = check_circuit_breaker("r1", mock_db)
        assert result is True
        mock_db.upsert_trust_state.assert_called_once()

    def test_circuit_breaker_no_trip_insufficient_failures(self):
        from server.healing.governor import check_circuit_breaker
        mock_db = MagicMock()
        now = int(time.time())
        mock_db.get_heal_outcomes.return_value = [
            {"created_at": now - 100, "action_success": True, "verified": 0},
        ]
        result = check_circuit_breaker("r1", mock_db)
        assert result is False

    def test_circuit_breaker_already_at_notify(self):
        from server.healing.governor import check_circuit_breaker
        mock_db = MagicMock()
        now = int(time.time())
        mock_db.get_heal_outcomes.return_value = [
            {"created_at": now - 100, "action_success": True, "verified": 0},
            {"created_at": now - 200, "action_success": True, "verified": 0},
            {"created_at": now - 300, "action_success": True, "verified": 0},
        ]
        mock_db.get_trust_state.return_value = {"current_level": "notify", "ceiling": "execute"}
        result = check_circuit_breaker("r1", mock_db)
        assert result is False

    def test_evaluate_promotions_eligible(self):
        from server.healing.governor import evaluate_promotions
        mock_db = MagicMock()
        mock_db.list_trust_states.return_value = [
            {"rule_id": "r1", "current_level": "notify", "ceiling": "execute",
             "promoted_at": 0, "demoted_at": 0, "last_evaluated": 0},
        ]
        mock_db.get_heal_outcomes.return_value = [
            {"trust_level": "notify", "action_success": True, "verified": 1}
            for _ in range(15)
        ]
        suggestions = evaluate_promotions(mock_db)
        assert len(suggestions) == 1
        assert suggestions[0]["category"] == "trust_promotion"

    def test_evaluate_promotions_too_few_outcomes(self):
        from server.healing.governor import evaluate_promotions
        mock_db = MagicMock()
        mock_db.list_trust_states.return_value = [
            {"rule_id": "r1", "current_level": "notify", "ceiling": "execute",
             "promoted_at": 0, "demoted_at": 0, "last_evaluated": 0},
        ]
        mock_db.get_heal_outcomes.return_value = [
            {"trust_level": "notify", "action_success": True, "verified": 1}
            for _ in range(3)
        ]
        suggestions = evaluate_promotions(mock_db)
        assert len(suggestions) == 0

    def test_effective_trust_anomaly_source_demoted(self):
        from server.healing.governor import effective_trust
        mock_db = MagicMock()
        mock_db.get_trust_state.return_value = {"current_level": "execute"}
        result = effective_trust("r1", "anomaly", mock_db)
        assert result == "approve"


# ===================================================================
# 11. Ledger
# ===================================================================

class TestLedger:
    def test_record_success(self):
        from server.healing.ledger import record
        mock_db = MagicMock()
        mock_db.insert_heal_outcome.return_value = 42
        outcome = _make_outcome()
        result_id = record(outcome, mock_db)
        assert result_id == 42
        mock_db.insert_heal_outcome.assert_called_once()
        kwargs = mock_db.insert_heal_outcome.call_args.kwargs
        assert kwargs["target"] == "nginx"
        assert kwargs["action_type"] == "restart_container"
        assert kwargs["action_success"] is True
        assert kwargs["verified"] is True

    def test_record_no_events(self):
        from server.healing.ledger import record
        from server.healing.models import HealOutcome, HealRequest, HealPlan
        request = HealRequest(correlation_key="test", events=[], primary_target="host")
        plan = HealPlan(request=request, action_type="webhook", action_params={})
        outcome = HealOutcome(plan=plan, action_success=True, verified=True, duration_s=0.5)
        mock_db = MagicMock()
        mock_db.insert_heal_outcome.return_value = 1
        record(outcome, mock_db)
        kwargs = mock_db.insert_heal_outcome.call_args.kwargs
        assert kwargs["rule_id"] == ""
        assert kwargs["source"] == "unknown"

    def test_record_extra_audit_fields(self):
        from server.healing.ledger import record
        outcome = _make_outcome()
        outcome.extra = {"risk_level": "high", "snapshot_id": "snap-1", "unknown_field": "ignored"}
        mock_db = MagicMock()
        mock_db.insert_heal_outcome.return_value = 99
        record(outcome, mock_db)
        kwargs = mock_db.insert_heal_outcome.call_args.kwargs
        assert kwargs["risk_level"] == "high"
        assert kwargs["snapshot_id"] == "snap-1"
        assert "unknown_field" not in kwargs

    def test_generate_suggestions_recurring(self):
        from server.healing.ledger import generate_suggestions
        mock_db = MagicMock()
        outcomes = [
            {"rule_id": "r1", "target": "nginx", "action_type": "restart",
             "action_success": True, "verified": 1}
            for _ in range(12)
        ]
        mock_db.get_heal_outcomes.return_value = outcomes
        suggestions = generate_suggestions(mock_db)
        categories = [s["category"] for s in suggestions]
        assert "recurring_issue" in categories

    def test_generate_suggestions_low_effectiveness(self):
        from server.healing.ledger import generate_suggestions
        mock_db = MagicMock()
        outcomes = [
            {"rule_id": "r1", "target": "nginx", "action_type": "restart",
             "action_success": True, "verified": 0}
            for _ in range(10)
        ]
        mock_db.get_heal_outcomes.return_value = outcomes
        suggestions = generate_suggestions(mock_db)
        categories = [s["category"] for s in suggestions]
        assert "recurring_issue" in categories
        assert "low_effectiveness" in categories

    def test_generate_suggestions_empty_outcomes(self):
        from server.healing.ledger import generate_suggestions
        mock_db = MagicMock()
        mock_db.get_heal_outcomes.return_value = []
        suggestions = generate_suggestions(mock_db)
        assert suggestions == []

    def test_generate_suggestions_persists_to_db(self):
        from server.healing.ledger import generate_suggestions
        mock_db = MagicMock()
        outcomes = [
            {"rule_id": "r1", "target": "nginx", "action_type": "restart",
             "action_success": True, "verified": 1}
            for _ in range(12)
        ]
        mock_db.get_heal_outcomes.return_value = outcomes
        generate_suggestions(mock_db)
        assert mock_db.insert_heal_suggestion.called


# ===================================================================
# 12. Agent verify
# ===================================================================

class TestAgentVerify:
    def test_verify_agent_unreachable(self):
        from server.healing.agent_verify import verify_target_with_agent
        with patch("server.healing.agent_verify._query_agent", return_value=None):
            result = verify_target_with_agent("host1", "nginx")
        assert result.agent_reachable is False
        assert result.confirmed_down is None

    def test_verify_target_confirmed_down(self):
        from server.healing.agent_verify import verify_target_with_agent
        with patch("server.healing.agent_verify._query_agent",
                    return_value={"status": "down", "detail": "service stopped"}):
            result = verify_target_with_agent("host1", "nginx")
        assert result.agent_reachable is True
        assert result.confirmed_down is True
        assert "stopped" in result.detail

    def test_verify_target_confirmed_up(self):
        from server.healing.agent_verify import verify_target_with_agent
        with patch("server.healing.agent_verify._query_agent",
                    return_value={"status": "up", "detail": "running fine"}):
            result = verify_target_with_agent("host1", "nginx")
        assert result.agent_reachable is True
        assert result.confirmed_down is False

    def test_verify_target_unknown_status(self):
        from server.healing.agent_verify import verify_target_with_agent
        with patch("server.healing.agent_verify._query_agent",
                    return_value={"status": "unknown", "detail": "inconclusive"}):
            result = verify_target_with_agent("host1", "nginx")
        assert result.agent_reachable is True
        assert result.confirmed_down is None

    def test_verify_query_exception(self):
        from server.healing.agent_verify import verify_target_with_agent
        with patch("server.healing.agent_verify._query_agent", side_effect=RuntimeError("boom")):
            result = verify_target_with_agent("host1", "nginx")
        assert result.agent_reachable is False
        assert result.confirmed_down is None
        assert "query failed" in result.detail

    def test_verify_result_dataclass(self):
        from server.healing.agent_verify import VerifyResult
        r = VerifyResult(agent_reachable=True, confirmed_down=True, detail="test")
        assert r.agent_reachable is True
        assert r.confirmed_down is True
        assert r.detail == "test"

    def test_verify_result_defaults(self):
        from server.healing.agent_verify import VerifyResult
        r = VerifyResult()
        assert r.agent_reachable is False
        assert r.confirmed_down is None
        assert r.detail == ""
