# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Dependency graph model and root cause resolution for the healing pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DepNode:
    """A node in the dependency graph representing a monitored target."""

    target: str
    node_type: str = "service"          # "service" | "infrastructure" | "external"
    site: str = ""
    health_check: str = ""
    depends_on: list[str] = field(default_factory=list)
    auto_discovered: bool = False
    confirmed: bool = True


class DependencyGraph:
    """Directed Acyclic Graph of monitored targets and their dependencies.

    Edges are stored as ``depends_on`` lists on each node (parent pointers).
    Dependent lookups (child pointers) are derived on the fly by scanning
    all nodes — the graph is expected to be small (tens to low hundreds of
    nodes), so the linear scan cost is negligible.
    """

    def __init__(self) -> None:
        # target -> DepNode
        self._nodes: dict[str, DepNode] = {}

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_node(
        self,
        target: str,
        *,
        node_type: str = "service",
        site: str = "",
        health_check: str = "",
        depends_on: list[str] | None = None,
        auto_discovered: bool = False,
        confirmed: bool = True,
    ) -> DepNode:
        """Add or replace a node in the graph."""
        node = DepNode(
            target=target,
            node_type=node_type,
            site=site,
            health_check=health_check,
            depends_on=list(depends_on or []),
            auto_discovered=auto_discovered,
            confirmed=confirmed,
        )
        self._nodes[target] = node
        return node

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_node(self, target: str) -> DepNode | None:
        """Return the node for *target*, or None if not registered."""
        return self._nodes.get(target)

    def all_nodes(self) -> list[DepNode]:
        """Return all nodes in the graph."""
        return list(self._nodes.values())

    def get_dependents(self, target: str) -> list[DepNode]:
        """Return nodes that *directly* depend on *target* (children)."""
        return [n for n in self._nodes.values() if target in n.depends_on]

    def get_ancestors(self, target: str, _visited: set[str] | None = None) -> list[DepNode]:
        """Return all ancestor nodes (direct and transitive) of *target*.

        Walks upward through ``depends_on`` edges recursively, guarding
        against cycles via *_visited*.
        """
        if _visited is None:
            _visited = set()

        node = self._nodes.get(target)
        if node is None:
            return []

        result: list[DepNode] = []
        for parent_target in node.depends_on:
            if parent_target in _visited:
                continue
            _visited.add(parent_target)
            parent = self._nodes.get(parent_target)
            if parent is not None:
                result.append(parent)
                result.extend(self.get_ancestors(parent_target, _visited))
        return result

    def get_all_descendants(self, target: str, _visited: set[str] | None = None) -> set[str]:
        """Return the set of all descendant target names (direct and transitive).

        Walks downward through dependent relationships recursively.
        """
        if _visited is None:
            _visited = set()

        result: set[str] = set()
        for child in self.get_dependents(target):
            if child.target in _visited:
                continue
            _visited.add(child.target)
            result.add(child.target)
            result.update(self.get_all_descendants(child.target, _visited))
        return result

    def get_site_targets(self, site: str) -> list[DepNode]:
        """Return all nodes belonging to *site*."""
        return [n for n in self._nodes.values() if n.site == site]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> list[dict]:
        """Serialize all nodes to a list of plain dicts (YAML-compatible)."""
        out = []
        for node in self._nodes.values():
            entry: dict = {
                "target": node.target,
                "type": node.node_type,
            }
            if node.site:
                entry["site"] = node.site
            if node.health_check:
                entry["health_check"] = node.health_check
            if node.depends_on:
                entry["depends_on"] = list(node.depends_on)
            if node.auto_discovered:
                entry["auto_discovered"] = True
            if not node.confirmed:
                entry["confirmed"] = False
            out.append(entry)
        return out

    @classmethod
    def from_config(cls, config: list[dict]) -> DependencyGraph:
        """Build a graph from a list of plain dicts (e.g. parsed YAML).

        Each dict must have a ``target`` key; all other keys are optional
        and map directly to :class:`DepNode` fields.  ``type`` maps to
        ``node_type`` so the YAML schema stays human-friendly.
        """
        g = cls()
        for entry in config:
            target = entry["target"]
            g.add_node(
                target,
                node_type=entry.get("type", "service"),
                site=entry.get("site", ""),
                health_check=entry.get("health_check", ""),
                depends_on=list(entry.get("depends_on", [])),
                auto_discovered=bool(entry.get("auto_discovered", False)),
                confirmed=bool(entry.get("confirmed", True)),
            )
        return g


# ---------------------------------------------------------------------------
# Root-cause resolution
# ---------------------------------------------------------------------------

def resolve_root_cause(
    graph: DependencyGraph,
    failing_targets: set[str],
) -> tuple[str | None, set[str]]:
    """Identify the root-cause target among a set of failing targets.

    Algorithm
    ---------
    1. For every failing target find its ancestors that are *also* failing.
    2. The root cause is the failing target whose *none* of its ancestors
       are also failing — i.e. it sits highest in the failure chain.
    3. When multiple such candidates exist (independent failures), pick the
       one that suppresses the most other failing targets (most descendants
       that are failing).  If still tied, return the lexicographically first
       so results are deterministic.
    4. All other failing targets that are descendants of the root cause are
       returned as *suppressed* (their alerts/actions should be held until
       the root is fixed).

    Returns
    -------
    (root_target | None, suppressed_set)
        *None* when *failing_targets* is empty.
    """
    if not failing_targets:
        return None, set()

    # Step 1: find candidates — targets with no failing ancestor
    candidates: list[str] = []
    for target in failing_targets:
        ancestor_targets = {a.target for a in graph.get_ancestors(target)}
        if not ancestor_targets.intersection(failing_targets):
            candidates.append(target)

    if not candidates:
        # Cycle or unknown deps — fall back to first alphabetically
        candidates = sorted(failing_targets)

    # Step 2: among candidates pick the one with the most failing descendants
    def _failing_descendant_count(t: str) -> int:
        return len(graph.get_all_descendants(t).intersection(failing_targets))

    root = max(candidates, key=lambda t: (_failing_descendant_count(t), t.__neg__ if False else 0))
    # For deterministic tie-breaking use a tuple sort
    root = sorted(candidates, key=lambda t: (-_failing_descendant_count(t), t))[0]

    # Step 3: suppressed = failing descendants of the root
    suppressed = graph.get_all_descendants(root).intersection(failing_targets)

    return root, suppressed
