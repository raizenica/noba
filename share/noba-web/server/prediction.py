# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Predictive capacity planning engine.

Multi-metric regression with seasonal decomposition and confidence intervals.
Uses only Python stdlib (math, statistics). No numpy/scipy dependency.
"""
from __future__ import annotations

import math
import statistics
import time
from typing import Any

from .db import db


def predict_capacity(
    metric_keys: list[str],
    range_hours: int = 168,
    projection_hours: int = 720,
) -> dict:
    """Multi-metric capacity prediction with confidence intervals.

    Combines multiple related metrics (e.g., disk_percent + inode_percent + io_rate)
    for more accurate predictions than single-metric linear regression.

    Returns:
        {
            "metrics": {key: {regression, seasonal, projection, residual_std}},
            "combined": {full_at, primary_metric, r_squared, confidence, slope_per_day},
        }
    """
    results: dict[str, Any] = {}
    for key in metric_keys:
        points = db.get_history(key, range_hours=range_hours, resolution=300, raw=True)
        if len(points) < 10:
            results[key] = {"error": "Insufficient data"}
            continue
        xs = [p["time"] for p in points]
        ys = [p["value"] for p in points]
        reg = _linear_regression(xs, ys)
        detrended = _remove_trend(xs, ys, reg["slope"], reg["intercept"])
        seasonal = _detect_seasonality(xs, detrended)
        residual_std = _residual_std(xs, ys, reg["slope"], reg["intercept"])
        projection = _project_with_confidence(
            xs, reg, seasonal, residual_std, projection_hours
        )
        results[key] = {
            "regression": reg,
            "seasonal": seasonal,
            "projection": projection,
            "residual_std": round(residual_std, 4),
        }

    combined = _combine_predictions(results, projection_hours)
    return {"metrics": results, "combined": combined}


def _linear_regression(xs: list, ys: list) -> dict:
    """Simple linear regression. Returns slope, intercept, r_squared."""
    n = len(xs)
    if n < 2:
        return {"slope": 0, "intercept": 0, "r_squared": 0}
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_x2 = sum(x * x for x in xs)
    denom = n * sum_x2 - sum_x ** 2
    if denom == 0:
        return {"slope": 0, "intercept": sum_y / n, "r_squared": 0}
    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    y_mean = sum_y / n
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return {
        "slope": round(slope, 10),
        "intercept": round(intercept, 4),
        "r_squared": round(r_squared, 4),
    }


def _detect_seasonality(
    xs: list, ys: list, max_period_hours: int = 168
) -> dict | None:
    """Detect weekly/daily seasonal patterns via autocorrelation.

    Checks periods at 24h and 168h (weekly). Returns the strongest
    detected pattern or None if no significant seasonality.

    The autocorrelation denominator is the total sum of squares (not sample
    variance), so the result is the fraction of total variance explained at
    that lag.
    """
    if len(xs) < 48:
        return None

    y_mean = statistics.mean(ys)
    y_var = statistics.variance(ys) if len(ys) > 1 else 0
    if y_var < 0.01:
        return None

    step = xs[1] - xs[0] if len(xs) > 1 else 300
    best_period = None
    best_corr = 0.0

    for period_hours in [24, 168]:
        lag = int(period_hours * 3600 / step)
        if lag >= len(ys) - 1:
            continue
        pairs = [(ys[i] - y_mean, ys[i + lag] - y_mean) for i in range(len(ys) - lag)]
        if not pairs:
            continue
        num = sum(a * b for a, b in pairs)
        ss_total = sum((y - y_mean) ** 2 for y in ys)
        if ss_total == 0:
            continue
        corr = num / ss_total
        if corr > best_corr and corr > 0.3:
            best_corr = corr
            best_period = period_hours

    if best_period is None:
        return None

    lag = int(best_period * 3600 / step)
    chunk_size = min(lag, len(ys))
    chunks = [ys[i : i + chunk_size] for i in range(0, len(ys) - chunk_size + 1, chunk_size)]
    if chunks:
        avg_range = statistics.mean(max(c) - min(c) for c in chunks if c)
        amplitude = avg_range / 2
    else:
        amplitude = 0

    return {
        "period_hours": best_period,
        "correlation": round(best_corr, 4),
        "amplitude": round(amplitude, 2),
    }


def _remove_trend(xs: list, ys: list, slope: float, intercept: float) -> list:
    """Remove linear trend, return detrended residuals."""
    return [y - (slope * x + intercept) for x, y in zip(xs, ys)]


def _residual_std(xs: list, ys: list, slope: float, intercept: float) -> float:
    """Standard deviation of residuals from the regression line."""
    residuals = [y - (slope * x + intercept) for x, y in zip(xs, ys)]
    if len(residuals) < 2:
        return 0.0
    return statistics.stdev(residuals)


def _project_with_confidence(
    xs: list,
    regression: dict,
    seasonal: dict | None,
    residual_std: float,
    projection_hours: int,
) -> list:
    """Generate projection points with 68% and 95% confidence intervals.

    Uses the proper prediction interval formula:
        SE = s * sqrt(1 + 1/n + (x - x_mean)^2 / S_xx)

    The 68% interval corresponds to ±1 SE; the 95% interval to ±1.96 SE.
    Seasonal component is added as amplitude * sin(2*pi*t/period).
    """
    slope = regression["slope"]
    intercept = regression["intercept"]
    last_t = xs[-1]
    step = 3600  # 1-hour steps for projection
    n_points = int(projection_hours)

    n = len(xs)
    x_mean = sum(xs) / n if n else 0
    s_xx = sum((x - x_mean) ** 2 for x in xs) if n > 1 else 1

    has_season = seasonal is not None
    period_s = seasonal["period_hours"] * 3600 if has_season else 0
    amplitude = seasonal["amplitude"] if has_season else 0

    points = []
    for i in range(1, n_points + 1):
        t = last_t + i * step
        trend_val = slope * t + intercept

        seasonal_adj = 0.0
        if has_season and period_s > 0:
            seasonal_adj = amplitude * math.sin(2 * math.pi * t / period_s)

        predicted = trend_val + seasonal_adj

        x_dev = (t - x_mean) ** 2 / s_xx if s_xx > 0 else 0
        se = residual_std * math.sqrt(1 + 1 / max(n, 1) + x_dev)

        points.append({
            "time": t,
            "predicted": round(predicted, 2),
            "lower_68": round(predicted - se, 2),
            "upper_68": round(predicted + se, 2),
            "lower_95": round(predicted - 1.96 * se, 2),
            "upper_95": round(predicted + 1.96 * se, 2),
        })

    return points


def _combine_predictions(results: dict, projection_hours: int) -> dict:
    """Combine multiple metric predictions into a single forecast.

    Picks the metric with the highest R² as the primary signal for the
    combined full_at estimate and confidence rating.
    """
    best_key = None
    best_r2 = -1.0
    for key, data in results.items():
        if "error" in data:
            continue
        r2 = data["regression"]["r_squared"]
        if r2 > best_r2:
            best_r2 = r2
            best_key = key

    if best_key is None:
        return {"full_at": None, "primary_metric": None, "confidence": "low"}

    reg = results[best_key]["regression"]
    slope = reg["slope"]
    intercept = reg["intercept"]

    full_at = None
    if slope > 0:
        t_full = (100 - intercept) / slope
        now = time.time()
        if t_full > now:
            from datetime import datetime, timezone
            full_at = datetime.fromtimestamp(t_full, tz=timezone.utc).isoformat()

    confidence = "high" if best_r2 > 0.8 else "medium" if best_r2 > 0.5 else "low"

    return {
        "full_at": full_at,
        "primary_metric": best_key,
        "r_squared": best_r2,
        "confidence": confidence,
        "slope_per_day": round(slope * 86400, 4) if slope else 0,
    }
