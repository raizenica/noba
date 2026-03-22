"""Tests for healing.auto_discovery: co-failure pattern detection."""
from __future__ import annotations

import time


def _make_outcomes(pairs, window_s=120):
    """Generate mock heal outcomes for co-failure testing.

    pairs: list of (target, timestamp) tuples
    """
    outcomes = []
    for target, ts in pairs:
        outcomes.append({
            "target": target,
            "created_at": int(ts),
            "action_success": True,
            "verified": True,
            "rule_id": f"rule-{target}",
        })
    return outcomes


class TestCoFailureDetection:
    def test_detects_frequent_co_failures(self):
        from server.healing.auto_discovery import detect_co_failures
        now = time.time()
        # truenas and plex fail together 5 times within 2 min of each other
        outcomes = []
        for i in range(5):
            base = now - (i * 3600)  # every hour
            outcomes.extend(_make_outcomes([
                ("truenas", base),
                ("plex", base + 30),  # 30s after truenas
            ]))

        pairs = detect_co_failures(outcomes, window_s=120, min_co_occurrences=3)
        # Should detect truenas<->plex as co-failing
        pair_targets = {frozenset(p["targets"]) for p in pairs}
        assert frozenset({"truenas", "plex"}) in pair_targets

    def test_ignores_infrequent_co_failures(self):
        from server.healing.auto_discovery import detect_co_failures
        now = time.time()
        # truenas and plex fail together only once
        outcomes = _make_outcomes([
            ("truenas", now), ("plex", now + 30),
        ])
        pairs = detect_co_failures(outcomes, window_s=120, min_co_occurrences=3)
        assert len(pairs) == 0

    def test_ignores_failures_outside_window(self):
        from server.healing.auto_discovery import detect_co_failures
        now = time.time()
        # truenas and plex fail but 10 minutes apart (outside 2-min window)
        outcomes = []
        for i in range(5):
            base = now - (i * 3600)
            outcomes.extend(_make_outcomes([
                ("truenas", base),
                ("plex", base + 600),  # 10 min later — outside window
            ]))
        pairs = detect_co_failures(outcomes, window_s=120, min_co_occurrences=3)
        assert len(pairs) == 0

    def test_does_not_pair_target_with_itself(self):
        from server.healing.auto_discovery import detect_co_failures
        now = time.time()
        outcomes = []
        for i in range(5):
            outcomes.extend(_make_outcomes([
                ("truenas", now - (i * 3600)),
                ("truenas", now - (i * 3600) + 10),
            ]))
        pairs = detect_co_failures(outcomes, window_s=120, min_co_occurrences=3)
        for p in pairs:
            assert len(p["targets"]) == 2  # no self-pairs

    def test_returns_co_occurrence_count(self):
        from server.healing.auto_discovery import detect_co_failures
        now = time.time()
        outcomes = []
        for i in range(7):
            base = now - (i * 3600)
            outcomes.extend(_make_outcomes([
                ("truenas", base), ("plex", base + 15),
            ]))
        pairs = detect_co_failures(outcomes, window_s=120, min_co_occurrences=3)
        for p in pairs:
            if set(p["targets"]) == {"truenas", "plex"}:
                assert p["count"] >= 5


class TestDependencySuggestions:
    def test_generates_suggestion_from_co_failure(self):
        from server.healing.auto_discovery import generate_dependency_suggestions
        co_failures = [
            {"targets": ["truenas", "plex"], "count": 8, "percentage": 87.5},
        ]
        suggestions = generate_dependency_suggestions(co_failures)
        assert len(suggestions) >= 1
        assert suggestions[0]["category"] == "dependency_candidate"
        assert "truenas" in suggestions[0]["message"]
        assert "plex" in suggestions[0]["message"]

    def test_no_suggestions_for_empty_input(self):
        from server.healing.auto_discovery import generate_dependency_suggestions
        suggestions = generate_dependency_suggestions([])
        assert len(suggestions) == 0
