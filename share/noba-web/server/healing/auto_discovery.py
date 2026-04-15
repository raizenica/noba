# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Co-failure auto-discovery for dependency suggestions.

Analyzes historical heal outcomes to detect targets that frequently
fail together within a time window. Surfaces patterns as dependency
suggestions for operator confirmation.

Auto-discovered dependencies are NEVER acted on without operator
confirmation. They remain as suggestions until explicitly accepted.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from itertools import combinations

logger = logging.getLogger("noba")


def detect_co_failures(
    outcomes: list[dict],
    *,
    window_s: int = 120,
    min_co_occurrences: int = 3,
) -> list[dict]:
    """Detect pairs of targets that frequently fail within a time window.

    Args:
        outcomes: list of heal outcome dicts with 'target' and 'created_at'
        window_s: max seconds between failures to count as co-failure
        min_co_occurrences: minimum times a pair must co-fail to be reported

    Returns:
        list of {"targets": [a, b], "count": N, "percentage": float}
    """
    # Group outcomes by target
    by_target: dict[str, list[int]] = defaultdict(list)
    for o in outcomes:
        target = o.get("target", "")
        ts = o.get("created_at", 0)
        if target and ts:
            by_target[target].append(ts)

    # Sort timestamps for each target
    for timestamps in by_target.values():
        timestamps.sort()

    # Count co-failures for each pair
    targets = list(by_target.keys())
    pair_counts: dict[frozenset, int] = defaultdict(int)
    pair_total: dict[frozenset, int] = defaultdict(int)

    for a, b in combinations(targets, 2):
        if a == b:
            continue
        key = frozenset({a, b})
        ts_a = by_target[a]
        ts_b = by_target[b]

        # For each failure of a, check if b failed within window
        co_count = 0
        for ta in ts_a:
            for tb in ts_b:
                if abs(ta - tb) <= window_s:
                    co_count += 1
                    break  # count each a-failure once

        pair_counts[key] = co_count
        pair_total[key] = len(ts_a)

    # Filter by min occurrences
    results = []
    for pair, count in pair_counts.items():
        if count >= min_co_occurrences:
            total = pair_total[pair]
            pct = (count / total * 100) if total > 0 else 0
            targets_list = sorted(pair)
            results.append({
                "targets": targets_list,
                "count": count,
                "percentage": round(pct, 1),
            })

    return sorted(results, key=lambda x: x["count"], reverse=True)


def generate_dependency_suggestions(co_failures: list[dict]) -> list[dict]:
    """Convert co-failure patterns into dependency suggestions.

    Returns list of suggestion dicts ready for db.insert_heal_suggestion().
    """
    suggestions = []
    for cf in co_failures:
        targets = cf["targets"]
        count = cf["count"]
        pct = cf["percentage"]

        msg = (
            f"'{targets[0]}' and '{targets[1]}' co-fail {pct}% of the time "
            f"({count} occurrences within 2-minute window). "
            f"Consider adding a dependency relationship."
        )

        suggestions.append({
            "category": "dependency_candidate",
            "severity": "info",
            "message": msg,
            "rule_id": None,
            "suggested_action": json.dumps({
                "action": "add_dependency",
                "source": targets[0],
                "depends_on": targets[1],
            }),
            "evidence": json.dumps({
                "targets": targets,
                "count": count,
                "percentage": pct,
            }),
        })

    return suggestions


def run_auto_discovery(db) -> int:
    """Run auto-discovery cycle. Returns number of new suggestions generated.

    Meant to be called from the scheduler (hourly).
    """
    try:
        outcomes = db.get_heal_outcomes(limit=1000)
        co_failures = detect_co_failures(outcomes)
        suggestions = generate_dependency_suggestions(co_failures)

        for s in suggestions:
            db.insert_heal_suggestion(**s)

        if suggestions:
            logger.info("Auto-discovery: %d dependency suggestion(s) generated", len(suggestions))
        return len(suggestions)
    except Exception as exc:
        logger.error("Auto-discovery failed: %s", exc)
        return 0
