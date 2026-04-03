# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Predictive and proactive healing.

Evaluates capacity predictions and anomaly detection on a periodic cycle.
Emits HealEvents into the pipeline for approaching thresholds and
detected anomalies. Conservative approach: predictions only trigger
low-risk actions via trust cap.

Stale data guard: if collector data is older than 2x the collection
interval, all predictive evaluation is suspended to prevent phantom heals.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

from .models import HealEvent

logger = logging.getLogger("noba")

# Default metric groups for prediction evaluation
DEFAULT_METRIC_GROUPS = {
    "disk": ["disk_percent"],
    "memory": ["mem_percent"],
    "cpu": ["cpu_percent"],
}

# Horizon thresholds: hours -> severity
_HORIZONS = [
    (24, "warning"),    # breach within 24h
    (72, "info"),       # breach within 72h
]
# Beyond 168h: suggestion only (no HealEvent)


def _run_prediction(metric_keys: list[str]) -> dict:
    """Run prediction engine. Wraps prediction.predict_capacity."""
    try:
        from ..prediction import predict_capacity
        return predict_capacity(metric_keys)
    except Exception as exc:
        logger.error("Prediction failed for %s: %s", metric_keys, exc)
        return {"metrics": {}, "combined": {"full_at": None}}


def _check_anomalies() -> list[dict]:
    """Run anomaly detection. Wraps alerts.check_anomalies."""
    try:
        from ..alerts import check_anomalies
        from ..db import db as _db
        from ..yaml_config import read_yaml_settings
        return check_anomalies(_db, read_yaml_settings)
    except Exception as exc:
        logger.error("Anomaly check failed: %s", exc)
        return []


def is_data_stale(last_collect_time: float, collect_interval: float = 5.0) -> bool:
    """Check if collector data is stale (older than 2x collection interval)."""
    return (time.time() - last_collect_time) > (collect_interval * 2)


def evaluate_predictions(
    *,
    metric_groups: dict[str, list[str]] | None = None,
) -> list[HealEvent]:
    """Evaluate predictions for all metric groups.

    Returns HealEvents for metrics approaching thresholds.
    Only emits events for 24h (warning) and 72h (info) horizons.
    """
    groups = metric_groups or DEFAULT_METRIC_GROUPS
    events: list[HealEvent] = []
    now = time.time()

    for group_name, keys in groups.items():
        try:
            result = _run_prediction(keys)
            combined = result.get("combined", {})
            full_at_str = combined.get("full_at")
            if not full_at_str:
                continue

            full_at_ts = datetime.fromisoformat(full_at_str).timestamp()
            hours_until = (full_at_ts - now) / 3600

            if hours_until <= 0:
                continue  # already breached — alert system handles this

            # Determine severity based on horizon
            severity = None
            for horizon_hours, sev in _HORIZONS:
                if hours_until <= horizon_hours:
                    severity = sev
                    break

            if severity is None:
                continue  # beyond all horizons

            primary = combined.get("primary_metric", group_name)
            confidence = combined.get("confidence", "low")
            slope = combined.get("slope_per_day", 0)

            events.append(HealEvent(
                source="prediction",
                rule_id=f"prediction:{group_name}",
                condition=f"{primary} trending to 100% in {hours_until:.0f}h",
                target=primary,
                severity=severity,
                timestamp=now,
                metrics={
                    "full_at": full_at_str,
                    "hours_until": round(hours_until, 1),
                    "confidence": confidence,
                    "slope_per_day": slope,
                },
            ))
        except Exception as exc:
            logger.error("Prediction evaluation failed for %s: %s", group_name, exc)

    return events


def evaluate_anomalies() -> list[HealEvent]:
    """Evaluate anomaly detection and emit HealEvents for anomalies."""
    anomalies = _check_anomalies()
    events: list[HealEvent] = []
    now = time.time()

    for anomaly in anomalies:
        msg = anomaly.get("msg", "")
        # Extract metric name from message (e.g., "Anomaly: CPU 98%...")
        metric = "unknown"
        if "CPU" in msg:
            metric = "cpu_percent"
        elif "Memory" in msg or "mem" in msg.lower():
            metric = "mem_percent"
        elif "Temp" in msg or "temp" in msg.lower():
            metric = "cpu_temp"

        events.append(HealEvent(
            source="anomaly",
            rule_id=f"anomaly:{metric}",
            condition=msg,
            target=metric,
            severity=anomaly.get("level", "warning"),
            timestamp=now,
            metrics={"anomaly_message": msg},
        ))

    return events


def run_predictive_cycle(
    *,
    last_collect_time: float | None = None,
    collect_interval: float = 5.0,
    metric_groups: dict[str, list[str]] | None = None,
) -> list[HealEvent]:
    """Run one predictive evaluation cycle.

    Called by the scheduler every 15 minutes.
    Returns list of HealEvents to feed into the pipeline.
    """
    # Stale data guard
    if last_collect_time is not None and is_data_stale(last_collect_time, collect_interval):
        logger.warning("Predictive healing suspended — collector data is stale")
        return []

    events: list[HealEvent] = []

    # Prediction evaluation
    try:
        pred_events = evaluate_predictions(metric_groups=metric_groups)
        events.extend(pred_events)
        if pred_events:
            logger.info("Predictive: %d threshold approaching event(s)", len(pred_events))
    except Exception as exc:
        logger.error("Prediction evaluation cycle failed: %s", exc)

    # Anomaly evaluation
    try:
        anomaly_events = evaluate_anomalies()
        events.extend(anomaly_events)
        if anomaly_events:
            logger.info("Anomaly: %d anomaly event(s) detected", len(anomaly_events))
    except Exception as exc:
        logger.error("Anomaly evaluation cycle failed: %s", exc)

    return events
