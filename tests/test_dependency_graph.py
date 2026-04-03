# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing.dependency_graph: DAG model and root cause resolution."""
from __future__ import annotations


def _sample_graph():
    from server.healing.dependency_graph import DependencyGraph
    g = DependencyGraph()
    g.add_node("isp:site-a", node_type="external", site="site-a", health_check="ping 1.1.1.1")
    g.add_node("power:site-a", node_type="external", site="site-a", health_check="agent_reachable")
    g.add_node("network:site-a", node_type="infrastructure", site="site-a", depends_on=["isp:site-a", "power:site-a"])
    g.add_node("truenas", node_type="service", site="site-a", depends_on=["network:site-a"])
    g.add_node("plex", node_type="service", site="site-a", depends_on=["truenas", "network:site-a"])
    g.add_node("jellyfin", node_type="service", site="site-a", depends_on=["truenas"])
    g.add_node("pihole", node_type="service", site="site-a")
    return g


class TestDependencyGraph:
    def test_add_and_get_node(self):
        from server.healing.dependency_graph import DependencyGraph
        g = DependencyGraph()
        g.add_node("truenas", node_type="service", site="site-a")
        node = g.get_node("truenas")
        assert node is not None
        assert node.node_type == "service"
        assert node.site == "site-a"

    def test_get_nonexistent_returns_none(self):
        from server.healing.dependency_graph import DependencyGraph
        g = DependencyGraph()
        assert g.get_node("nope") is None

    def test_get_dependents(self):
        g = _sample_graph()
        dependents = g.get_dependents("truenas")
        names = {d.target for d in dependents}
        assert "plex" in names
        assert "jellyfin" in names
        assert "pihole" not in names

    def test_get_ancestors(self):
        g = _sample_graph()
        ancestors = g.get_ancestors("plex")
        names = {a.target for a in ancestors}
        assert "truenas" in names
        assert "network:site-a" in names
        assert "isp:site-a" in names

    def test_get_site_targets(self):
        g = _sample_graph()
        targets = g.get_site_targets("site-a")
        names = {t.target for t in targets}
        assert "plex" in names
        assert "truenas" in names

    def test_node_count(self):
        g = _sample_graph()
        assert len(g.all_nodes()) == 7

    def test_load_from_yaml_config(self):
        from server.healing.dependency_graph import DependencyGraph
        config = [
            {"target": "isp:site-a", "type": "external", "site": "site-a"},
            {"target": "truenas", "type": "service", "depends_on": ["isp:site-a"]},
        ]
        g = DependencyGraph.from_config(config)
        assert g.get_node("isp:site-a") is not None
        assert g.get_node("truenas") is not None
        ancestors = g.get_ancestors("truenas")
        assert any(a.target == "isp:site-a" for a in ancestors)

    def test_to_dict_serialization(self):
        from server.healing.dependency_graph import DependencyGraph
        g = DependencyGraph()
        g.add_node("svc", node_type="service", depends_on=["dep"])
        data = g.to_dict()
        assert len(data) == 1
        assert data[0]["target"] == "svc"
        assert data[0]["depends_on"] == ["dep"]

    def test_get_all_descendants(self):
        g = _sample_graph()
        desc = g.get_all_descendants("network:site-a")
        assert "truenas" in desc
        assert "plex" in desc
        assert "jellyfin" in desc
        assert "pihole" not in desc


class TestRootCauseResolution:
    def test_single_failure_is_its_own_root(self):
        from server.healing.dependency_graph import resolve_root_cause
        g = _sample_graph()
        root, suppressed = resolve_root_cause(g, failing_targets={"plex"})
        assert root == "plex"
        assert len(suppressed) == 0

    def test_nas_down_is_root_for_plex_and_jellyfin(self):
        from server.healing.dependency_graph import resolve_root_cause
        g = _sample_graph()
        root, suppressed = resolve_root_cause(g, failing_targets={"truenas", "plex", "jellyfin"})
        assert root == "truenas"
        assert "plex" in suppressed
        assert "jellyfin" in suppressed

    def test_external_root_suppresses_everything(self):
        from server.healing.dependency_graph import resolve_root_cause
        g = _sample_graph()
        root, suppressed = resolve_root_cause(g, failing_targets={"isp:site-a", "network:site-a", "truenas", "plex"})
        assert root == "isp:site-a"
        assert "plex" in suppressed
        assert "truenas" in suppressed

    def test_independent_failure_not_suppressed(self):
        from server.healing.dependency_graph import resolve_root_cause
        g = _sample_graph()
        root, suppressed = resolve_root_cause(g, failing_targets={"truenas", "pihole"})
        assert "pihole" not in suppressed

    def test_no_failures_returns_none(self):
        from server.healing.dependency_graph import resolve_root_cause
        g = _sample_graph()
        root, suppressed = resolve_root_cause(g, failing_targets=set())
        assert root is None
        assert len(suppressed) == 0

    def test_external_root_flagged_as_unhealable(self):
        from server.healing.dependency_graph import resolve_root_cause
        g = _sample_graph()
        root, suppressed = resolve_root_cause(g, failing_targets={"isp:site-a", "truenas", "plex"})
        node = g.get_node(root)
        assert node.node_type == "external"
