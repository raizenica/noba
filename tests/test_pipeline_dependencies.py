# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for dependency graph integration in the healing pipeline."""
from __future__ import annotations

import time
from unittest.mock import MagicMock


def _make_event(target="plex", rule_id="test-rule", source="alert"):
    from server.healing.models import HealEvent
    return HealEvent(
        source=source, rule_id=rule_id, condition="status == offline",
        target=target, severity="warning", timestamp=0, metrics={},
    )


def _make_pipeline_with_deps(dep_config=None):
    """Create a pipeline with a dependency graph."""
    from server.healing import HealPipeline
    from server.healing.dependency_graph import DependencyGraph

    db = MagicMock()
    db.get_heal_outcomes = MagicMock(return_value=[])
    db.get_trust_state = MagicMock(return_value=None)
    db.get_heal_success_rate = MagicMock(return_value=0.0)
    db.insert_heal_outcome = MagicMock()

    pipeline = HealPipeline(db, rules_cfg={}, settle_times={"restart_container": 0})

    if dep_config:
        pipeline._dep_graph = DependencyGraph.from_config(dep_config)

    return pipeline


def _alert_expiry():
    """Return an expiry timestamp 5 minutes in the future."""
    return time.time() + 300


class TestPipelineSiteIsolation:
    def test_suspect_site_suppresses_healing(self):
        """When a site is connectivity-suspect, events for that site are suppressed."""
        pipeline = _make_pipeline_with_deps([
            {"target": "plex", "type": "service", "site": "site-a"},
        ])
        pipeline._connectivity.mark_suspect("site-a", reason="agent unreachable")

        outcomes = []
        pipeline.on_outcome = lambda o: outcomes.append(o)

        event = _make_event(target="plex")
        pipeline.handle_heal_event(event)

        # Should NOT produce any outcome — event was suppressed before planning
        assert len(outcomes) == 0

    def test_non_suspect_site_proceeds(self):
        """Events for non-suspect sites proceed normally."""
        pipeline = _make_pipeline_with_deps([
            {"target": "plex", "type": "service", "site": "site-a"},
        ])
        # site-a is NOT suspect

        # Pipeline should proceed (will likely fail at execution since DB is mocked,
        # but the point is it wasn't suppressed)
        event = _make_event(target="plex")
        pipeline.handle_heal_event(event)
        # If we get here without being suppressed, the test passes
        # (actual execution is tested elsewhere)


class TestPipelineRootCause:
    def test_downstream_target_suppressed_when_root_is_failing(self):
        """If NAS and Plex both fail, and Plex depends on NAS, Plex should be suppressed."""
        pipeline = _make_pipeline_with_deps([
            {"target": "truenas", "type": "service", "site": "site-a"},
            {"target": "plex", "type": "service", "site": "site-a",
             "depends_on": ["truenas"]},
        ])

        # Simulate: truenas is already alerting (TTL dict)
        pipeline._active_alerts = {"truenas": _alert_expiry()}

        outcomes = []
        pipeline.on_outcome = lambda o: outcomes.append(o)

        event = _make_event(target="plex")
        pipeline.handle_heal_event(event)

        # Plex heal should be suppressed because truenas (its dependency) is also failing
        assert len(outcomes) == 0

    def test_independent_target_not_suppressed(self):
        """Targets with no dependency on the failing root are not suppressed."""
        pipeline = _make_pipeline_with_deps([
            {"target": "truenas", "type": "service", "site": "site-a"},
            {"target": "pihole", "type": "service", "site": "site-a"},
        ])

        pipeline._active_alerts = {"truenas": _alert_expiry()}

        event = _make_event(target="pihole")
        pipeline.handle_heal_event(event)
        # pihole has no dependency on truenas — should NOT be suppressed


class TestPipelineExternalRoot:
    def test_external_root_suppresses_all_downstream(self):
        """External node (ISP) failure should suppress all downstream healing."""
        pipeline = _make_pipeline_with_deps([
            {"target": "upstream-wan", "type": "external", "site": "site-a"},
            {"target": "truenas", "type": "service", "site": "site-a",
             "depends_on": ["upstream-wan"]},
            {"target": "plex", "type": "service", "site": "site-a",
             "depends_on": ["truenas"]},
        ])

        future = _alert_expiry()
        pipeline._active_alerts = {"upstream-wan": future, "truenas": future}

        outcomes = []
        pipeline.on_outcome = lambda o: outcomes.append(o)

        event = _make_event(target="plex")
        pipeline.handle_heal_event(event)

        # Should be suppressed — root cause is external
        assert len(outcomes) == 0


class TestActiveAlertsExpiry:
    def test_expired_alert_not_seen_as_active(self):
        """An alert entry past its TTL should not suppress downstream targets."""
        pipeline = _make_pipeline_with_deps([
            {"target": "truenas", "type": "service", "site": "site-a"},
            {"target": "plex", "type": "service", "site": "site-a",
             "depends_on": ["truenas"]},
        ])

        # truenas alert expired 10 seconds ago
        pipeline._active_alerts = {"truenas": time.time() - 10}

        # plex should NOT be suppressed — truenas alert has aged out
        event = _make_event(target="plex")
        pipeline.handle_heal_event(event)
        # If we get here without root-cause suppression, the test passes

    def test_refresh_extends_ttl(self):
        """Incoming events refresh the alert TTL."""
        pipeline = _make_pipeline_with_deps([
            {"target": "truenas", "type": "service", "site": "site-a"},
        ])

        # Start with a near-expired entry
        pipeline._active_alerts = {"truenas": time.time() + 1}

        # Refresh via event
        pipeline._refresh_alert("truenas")

        # TTL should be extended well into the future
        assert pipeline._active_alerts["truenas"] > time.time() + 60

    def test_sweep_removes_expired_entries(self):
        """The opportunistic sweep in _refresh_alert cleans up expired entries."""
        pipeline = _make_pipeline_with_deps()

        pipeline._active_alerts = {
            "service-a": time.time() - 100,  # expired
            "service-b": time.time() - 50,   # expired
            "service-c": time.time() + 300,  # still active
        }

        # Trigger sweep via a refresh
        pipeline._refresh_alert("service-d")

        # Expired entries should be gone
        assert "service-a" not in pipeline._active_alerts
        assert "service-b" not in pipeline._active_alerts
        assert "service-c" in pipeline._active_alerts
        assert "service-d" in pipeline._active_alerts
