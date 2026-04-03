# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Condition evaluation for alert rules and healing pipeline.

Extracted from alerts.py to break circular imports when the healing
pipeline needs condition evaluation without importing the full alerts module.
"""
from __future__ import annotations

import logging
import operator
import re

logger = logging.getLogger("noba")

# ── Comparison operators ──────────────────────────────────────────────────────
_OPS: dict = {
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


_SINGLE_RE = re.compile(
    r"^\s*([a-zA-Z0-9_\[\]\.]+)\s*(>|<|>=|<=|==|!=)\s*([0-9\.-]+)\s*$"
)


def validate_condition(condition_str: str) -> str | None:
    """Return *None* if *condition_str* is syntactically valid, else an error message."""
    if not condition_str or not condition_str.strip():
        return "Condition is required"
    if " AND " in condition_str:
        parts = [p.strip() for p in condition_str.split(" AND ")]
    elif " OR " in condition_str:
        parts = [p.strip() for p in condition_str.split(" OR ")]
    else:
        parts = [condition_str.strip()]
    for part in parts:
        if not _SINGLE_RE.match(part):
            return f"Invalid condition fragment: {part!r} — expected 'metric operator number' (e.g. cpuPercent > 90)"
    return None


def safe_eval_single(condition_str: str, flat: dict) -> bool:
    """Evaluate a single metric comparison (e.g. 'cpu_percent > 90')."""
    s = condition_str.replace("flat['", "").replace('flat["', "").replace("']", "").replace('"]', "")
    m = _SINGLE_RE.match(s)
    if not m:
        logger.warning("Malformed alert condition (parse failed): %s", condition_str)
        return False
    metric, op, val = m.groups()
    if metric not in flat:
        return False
    try:
        return _OPS[op](float(flat[metric]), float(val))
    except (ValueError, TypeError):
        logger.warning("Malformed alert condition (bad value): %s=%r", metric, flat[metric])
        return False


def safe_eval(condition_str: str, flat: dict) -> bool:
    """Evaluate a condition string, supporting AND/OR composite conditions."""
    if " AND " in condition_str:
        return all(safe_eval_single(part.strip(), flat) for part in condition_str.split(" AND "))
    if " OR " in condition_str:
        return any(safe_eval_single(part.strip(), flat) for part in condition_str.split(" OR "))
    return safe_eval_single(condition_str, flat)


def flatten_metrics(stats: dict) -> dict:
    """Flatten nested collector stats into a single-level dict for condition evaluation.

    Scalar values (int, float, str) are preserved as-is.
    Lists of dicts are expanded to ``key[i].subkey`` entries for numeric subvalues.
    Non-numeric nested values and non-dict list items are skipped.
    """
    flat: dict = {}
    for k, v in stats.items():
        if isinstance(v, (int, float, str)):
            flat[k] = v
        elif isinstance(v, list):
            for i, item in enumerate(v):
                if isinstance(item, dict):
                    for sk, sv in item.items():
                        if isinstance(sv, (int, float)):
                            flat[f"{k}[{i}].{sk}"] = sv
    return flat
