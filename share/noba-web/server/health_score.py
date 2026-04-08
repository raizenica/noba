# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Infrastructure Health Score computation (Feature 7).

Computes a 0-100 score from data already collected:
agents, endpoint monitors, SLA history, and live metrics.

Honesty contract
----------------
Categories that cannot be evaluated -- because they raised an exception
or because the underlying dataset is empty -- report ``score: None`` and
``status: "unknown"``. They are excluded from the normalized denominator
so an empty install does not inherit an undeserved "A".
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("noba")

_UNKNOWN_STATUS = "unknown"


def _clamp(v: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, v))


def _unknown_category(max_score: int, detail: str, recommendations: list[str] | None = None) -> dict:
    """Return an 'unknown' category entry (score=None, excluded from totals)."""
    return {
        "score": None,
        "max": max_score,
        "status": _UNKNOWN_STATUS,
        "detail": detail,
        "recommendations": recommendations or [],
    }


async def compute_health_score(db, agent_store_data: dict, bg_stats: dict | None) -> dict:
    """Compute infrastructure health score (0-100) with breakdown.

    Parameters
    ----------
    db : Database
        The shared DB instance.
    agent_store_data : dict
        Dict of ``{hostname: agent_data_dict}`` from the agent store.
    bg_stats : dict | None
        Latest collector stats (cpuPercent, memPercent, disks, etc.).
    """
    categories: dict[str, dict] = {}
    stats = bg_stats or {}
    now = int(time.time())
    total_agents = 0

    # ── 1. Monitoring coverage: agents online / total agents (0-10) ───────
    try:
        max_age = 120  # same as _AGENT_MAX_AGE
        total_agents = len(agent_store_data)
        online_agents = sum(1 for d in agent_store_data.values() if now - d.get("_received", 0) < max_age)
        if total_agents > 0:
            ratio = online_agents / total_agents
            score_monitoring = _clamp(ratio * 10)
            recommendations: list[str] = []
            if online_agents < total_agents:
                offline = total_agents - online_agents
                recommendations.append(f"{offline} agent(s) offline -- check connectivity")
            categories["monitoring_coverage"] = {
                "score": round(score_monitoring, 1),
                "max": 10,
                "status": "ok" if score_monitoring >= 8 else "warning" if score_monitoring >= 5 else "critical",
                "detail": f"{online_agents}/{total_agents} agents online",
                "recommendations": recommendations,
            }
        else:
            # No agents enrolled -- we cannot make any statement about coverage.
            categories["monitoring_coverage"] = _unknown_category(
                10,
                "No agents enrolled",
                ["Enroll at least one agent to enable coverage scoring"],
            )
    except Exception as exc:
        logger.warning("health_score: monitoring_coverage failed: %s", exc)
        categories["monitoring_coverage"] = _unknown_category(10, "evaluation failed")

    # ── 2. Certificate health (0-10) ─────────────────────────────────────
    try:
        monitors = db.get_endpoint_monitors(enabled_only=True)
        cert_scores: list[float] = []
        cert_recs: list[str] = []
        for m in monitors:
            days = m.get("cert_expiry_days")
            if days is None:
                continue
            if days <= 0:
                cert_scores.append(0)
                cert_recs.append(f"{m['name']}: certificate EXPIRED")
            elif days <= 7:
                cert_scores.append(2)
                cert_recs.append(f"{m['name']}: certificate expires in {days}d")
            elif days <= 14:
                cert_scores.append(5)
                cert_recs.append(f"{m['name']}: certificate expires in {days}d -- renew soon")
            elif days <= 30:
                cert_scores.append(7)
            else:
                cert_scores.append(10)
        if cert_scores:
            score_certs = sum(cert_scores) / len(cert_scores)
            categories["certificate_health"] = {
                "score": round(_clamp(score_certs), 1),
                "max": 10,
                "status": "ok" if score_certs >= 8 else "warning" if score_certs >= 5 else "critical",
                "detail": f"{len(cert_scores)} certificate(s) tracked",
                "recommendations": cert_recs[:5],
            }
        else:
            # No tracked certificates with expiry data -- nothing to score honestly.
            categories["certificate_health"] = _unknown_category(
                10,
                "No tracked certificates with expiry data",
                ["Add endpoint monitors that surface cert_expiry_days"],
            )
    except Exception as exc:
        logger.warning("health_score: certificate_health failed: %s", exc)
        categories["certificate_health"] = _unknown_category(10, "evaluation failed")

    # ── 3. Update status (0-10) ──────────────────────────────────────────
    # Check if any agents report pending package updates via their metrics.
    try:
        update_recs: list[str] = []
        agents_with_updates = 0
        agents_reporting_updates = 0
        for hostname, adata in agent_store_data.items():
            pkg_updates = adata.get("package_updates")
            if pkg_updates is None:
                pkg_updates = adata.get("pending_updates")
            if pkg_updates is None:
                continue
            agents_reporting_updates += 1
            if isinstance(pkg_updates, int | float) and pkg_updates > 0:
                agents_with_updates += 1
                update_recs.append(f"{hostname}: {int(pkg_updates)} update(s) pending")
        if agents_reporting_updates > 0:
            up_ratio = 1 - min(agents_with_updates / max(agents_reporting_updates, 1), 1)
            score_updates = _clamp(up_ratio * 10)
            categories["update_status"] = {
                "score": round(score_updates, 1),
                "max": 10,
                "status": "ok" if score_updates >= 8 else "warning" if score_updates >= 5 else "critical",
                "detail": (f"{agents_with_updates}/{agents_reporting_updates} host(s) with pending updates"),
                "recommendations": update_recs[:5],
            }
        else:
            # No agents reporting update counts -- cannot claim "up to date".
            categories["update_status"] = _unknown_category(
                10,
                "No agents reporting package_updates",
                ["Enable package update reporting on at least one agent"],
            )
    except Exception as exc:
        logger.warning("health_score: update_status failed: %s", exc)
        categories["update_status"] = _unknown_category(10, "evaluation failed")

    # ── 4. Uptime / SLA (0-10) ──────────────────────────────────────────
    try:
        # Gather SLA for all active alert rules
        alert_history = db.get_alert_history(limit=20)
        rule_ids = list({a["rule_id"] for a in alert_history})
        sla_values: list[float] = []
        sla_recs: list[str] = []
        for rid in rule_ids[:20]:
            sla = db.get_sla(rid, window_hours=720)  # 30 days
            if sla is None:
                # Honesty contract: unknown SLA is not an argument for
                # the uptime category — silently skip.
                continue
            sla_values.append(sla)
            if sla < 99.0:
                sla_recs.append(f"Rule '{rid}' SLA is {sla:.1f}% (target 99.9%)")
        if sla_values:
            avg_sla = sum(sla_values) / len(sla_values)
            # Map 95-100 SLA to 0-10 score
            score_uptime = _clamp((avg_sla - 95) * 2)
            categories["uptime"] = {
                "score": round(score_uptime, 1),
                "max": 10,
                "status": "ok" if score_uptime >= 8 else "warning" if score_uptime >= 5 else "critical",
                "detail": f"{len(sla_values)} SLA rule(s), avg {avg_sla:.1f}%",
                "recommendations": sla_recs[:5],
            }
        else:
            # No alert history to compute SLA from -- score is unknown.
            categories["uptime"] = _unknown_category(
                10,
                "No SLA data",
                ["Configure alert rules to begin accumulating SLA history"],
            )
    except Exception as exc:
        logger.warning("health_score: uptime failed: %s", exc)
        categories["uptime"] = _unknown_category(10, "evaluation failed")

    # ── 5. Capacity: no disk/CPU/RAM >85% (0-10) ────────────────────────
    try:
        has_cpu = "cpuPercent" in stats
        has_mem = "memPercent" in stats
        has_disks = "disks" in stats and stats.get("disks") is not None
        if not (has_cpu or has_mem or has_disks):
            categories["capacity"] = _unknown_category(
                10,
                "No capacity stats reported",
                ["Wait for the background collector to produce a sample"],
            )
        else:
            capacity_deductions = 0.0
            cap_recs: list[str] = []

            cpu = stats.get("cpuPercent", 0) or 0
            if cpu > 90:
                capacity_deductions += 4
                cap_recs.append(f"CPU at {cpu}% -- investigate high load")
            elif cpu > 85:
                capacity_deductions += 2
                cap_recs.append(f"CPU at {cpu}% -- approaching limit")

            mem = stats.get("memPercent", 0) or 0
            if mem > 90:
                capacity_deductions += 4
                cap_recs.append(f"Memory at {mem}% -- consider adding RAM or reducing load")
            elif mem > 85:
                capacity_deductions += 2
                cap_recs.append(f"Memory at {mem}% -- approaching limit")

            for disk in stats.get("disks", []) or []:
                p = disk.get("percent", 0)
                mount = disk.get("mount", "?")
                if p >= 95:
                    capacity_deductions += 3
                    cap_recs.append(f"Disk {mount} at {p}% -- critical, free space immediately")
                elif p >= 85:
                    capacity_deductions += 1.5
                    cap_recs.append(f"Disk {mount} at {p}% -- consider cleanup")

            score_capacity = _clamp(10 - capacity_deductions)
            categories["capacity"] = {
                "score": round(score_capacity, 1),
                "max": 10,
                "status": "ok" if score_capacity >= 8 else "warning" if score_capacity >= 5 else "critical",
                "detail": f"CPU {cpu}%, RAM {mem}%",
                "recommendations": cap_recs[:5],
            }
    except Exception as exc:
        logger.warning("health_score: capacity failed: %s", exc)
        categories["capacity"] = _unknown_category(10, "evaluation failed")

    # ── 6. Backup freshness (0-10) ──────────────────────────────────────
    try:
        backup_recs: list[str] = []
        # Check last successful backup job run
        backup_runs = db.get_job_runs(limit=10, trigger_prefix="manual:backup")
        if not backup_runs:
            # Also check scheduled triggers
            backup_runs = db.get_job_runs(limit=10, trigger_prefix="schedule:")
            backup_runs = [
                r for r in backup_runs if r.get("automation_id") and "backup" in (r.get("automation_id") or "").lower()
            ]

        last_ok = None
        for run in backup_runs:
            if run.get("status") == "done" and run.get("finished_at"):
                last_ok = run["finished_at"]
                break

        if last_ok:
            age_hours = (now - last_ok) / 3600
            if age_hours <= 24:
                score_backup = 10.0
            elif age_hours <= 48:
                score_backup = 7.0
                backup_recs.append(f"Last backup {age_hours:.0f}h ago -- consider daily schedule")
            elif age_hours <= 168:
                score_backup = 4.0
                backup_recs.append(f"Last backup {age_hours:.0f}h ago -- overdue")
            else:
                score_backup = 1.0
                backup_recs.append(f"Last backup {age_hours / 24:.0f}d ago -- severely overdue")
            categories["backup_freshness"] = {
                "score": round(score_backup, 1),
                "max": 10,
                "status": "ok" if score_backup >= 8 else "warning" if score_backup >= 5 else "critical",
                "detail": f"Last backup: {int((now - last_ok) / 3600)}h ago",
                "recommendations": backup_recs[:5],
            }
        else:
            # No backup history — we cannot claim freshness in either direction.
            categories["backup_freshness"] = _unknown_category(
                10,
                "No backup history",
                ["Configure automated backups to populate freshness scoring"],
            )
    except Exception as exc:
        logger.warning("health_score: backup_freshness failed: %s", exc)
        categories["backup_freshness"] = _unknown_category(10, "evaluation failed")

    # ── Compute total ────────────────────────────────────────────────────
    # Exclude "unknown" categories from the denominator -- we will not award
    # or deduct for data we cannot evaluate. The composite grade then reflects
    # the categories that actually produced a score.
    scored = [
        c for c in categories.values() if isinstance(c.get("score"), int | float) and c.get("status") != _UNKNOWN_STATUS
    ]
    total = sum(c["score"] for c in scored)
    max_total = sum(c["max"] for c in scored)
    normalized = round((total / max_total) * 100) if max_total > 0 else 0

    unknown_count = len(categories) - len(scored)
    # "N/A" guard: if fewer than 3 categories produced real scores, or if
    # more than 2 categories are unknown, refuse to emit a composite grade.
    if len(scored) < 3 or unknown_count > 2:
        grade = "N/A"
        normalized_out: int | None = None
    else:
        normalized_out = normalized
        grade = (
            "A"
            if normalized >= 90
            else "B"
            if normalized >= 75
            else "C"
            if normalized >= 60
            else "D"
            if normalized >= 40
            else "F"
        )

    return {
        "score": normalized_out,
        "total_raw": round(total, 1),
        "max_raw": max_total,
        "scored_categories": len(scored),
        "unknown_categories": unknown_count,
        "grade": grade,
        "categories": categories,
        "timestamp": now,
    }


# ── Per-service weighted health scoring ───────────────────────────────────────


def _score_to_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _calc_uptime_score(db_instance, monitor_id: int, hours: int = 720) -> float | None:
    """Uptime percentage from check history → 0-100 score, or None if unknown.

    Honesty contract: a failed DB lookup or no-data-yet monitor must NOT
    inherit a free 100/100 — the only honest answer is "unknown", returned
    as ``None`` and filtered out by the caller.
    """
    try:
        pct = db_instance.get_endpoint_uptime(monitor_id, hours=hours)
    except Exception as exc:
        logger.debug("uptime lookup failed for monitor %s: %s", monitor_id, exc)
        return None
    if pct is None:
        return None
    return min(100.0, float(pct))


def _calc_latency_score(db_instance, monitor_id: int, hours: int = 720) -> float | None:
    """Lower latency = higher score. 0ms=100, 1000ms+=0. None if unknown."""
    try:
        avg_ms = db_instance.get_endpoint_avg_latency(monitor_id, hours=hours)
    except Exception as exc:
        logger.debug("latency lookup failed for monitor %s: %s", monitor_id, exc)
        return None
    if avg_ms is None:
        return None
    return max(0.0, min(100.0, 100.0 - (avg_ms / 10.0)))  # 0ms=100, 1000ms=0


def _calc_error_rate_score(db_instance, monitor_id: int, hours: int = 720) -> float | None:
    """Inverse of error rate. 0% errors=100, 100% errors=0. None if unknown."""
    try:
        uptime = db_instance.get_endpoint_uptime(monitor_id, hours=hours)
    except Exception as exc:
        logger.debug("error-rate lookup failed for monitor %s: %s", monitor_id, exc)
        return None
    if uptime is None:
        return None
    return min(100.0, float(uptime))  # Uptime IS the inverse of error rate


def _calc_headroom_score(monitor: dict) -> float | None:
    """Response time headroom vs configured timeout. None if never probed."""
    timeout_ms = (monitor.get("timeout") or 10) * 1000
    if timeout_ms <= 0:
        return None
    last_ms = monitor.get("last_response_ms")
    if last_ms is None:
        return None
    ratio = last_ms / timeout_ms
    return max(0.0, min(100.0, (1.0 - ratio) * 100.0))


def compute_service_health_scores(db_instance) -> dict:
    """Per-service health scoring with weighted composite.

    Weights: uptime (40%) + latency trend (25%) + error rate (20%) + resource headroom (15%)
    """
    import statistics as _statistics

    # Base component weights — must sum to 1.0.
    _WEIGHTS = {"uptime": 0.40, "latency": 0.25, "error_rate": 0.20, "headroom": 0.15}

    monitors = db_instance.get_endpoint_monitors(enabled_only=True)
    services = []
    for m in monitors:
        mid = m["id"]
        components = {
            "uptime": _calc_uptime_score(db_instance, mid),
            "latency": _calc_latency_score(db_instance, mid),
            "error_rate": _calc_error_rate_score(db_instance, mid),
            "headroom": _calc_headroom_score(m),
        }

        # Honesty contract: any ALL-unknown monitor is emitted as "unknown" —
        # we never paper over a total data gap with a fake 100/100. But a
        # PARTIAL gap (e.g. latency unknown because there are no successful
        # probes to compute from) is scored against the components we DO
        # have, with weights renormalised to sum to 1 over that subset. This
        # is the honest middle ground: a service that's demonstrably down
        # still receives a bad composite even if its successful-probe
        # latency is mathematically undefined.
        known = {k: v for k, v in components.items() if v is not None}
        if not known:
            services.append(
                {
                    "name": m["name"],
                    "url": m.get("url", ""),
                    "composite_score": None,
                    "breakdown": {k: None for k in components},
                    "grade": "N/A",
                    "status": "unknown",
                },
            )
            continue

        weight_sum = sum(_WEIGHTS[k] for k in known)
        composite = sum(known[k] * (_WEIGHTS[k] / weight_sum) for k in known)

        services.append(
            {
                "name": m["name"],
                "url": m.get("url", ""),
                "composite_score": round(composite, 1),
                "breakdown": {
                    k: (round(v, 1) if v is not None else None)
                    for k, v in components.items()
                },
                "grade": _score_to_grade(composite),
                "status": "ok" if len(known) == len(components) else "partial",
            },
        )

    # Sort real scores ahead of unknown ones so operators see the worst real
    # services first and the unknowns clustered at the end (rather than
    # crashing the sort on None). Unknowns are assigned +inf composite.
    services.sort(
        key=lambda s: (
            s["composite_score"] if s["composite_score"] is not None else float("inf")
        ),
    )

    # Aggregate: only real (known) scores count towards the overall. Empty
    # or all-unknown monitor set → overall is None / "N/A" per honesty
    # contract — not an undeserved 100/100.
    real_scores = [s["composite_score"] for s in services if s["composite_score"] is not None]
    if real_scores:
        overall = round(_statistics.mean(real_scores), 1)
        grade = _score_to_grade(overall)
    else:
        overall = None
        grade = "N/A"
    return {
        "overall": overall,
        "grade": grade,
        "services": services,
        "unknown_count": sum(1 for s in services if s["composite_score"] is None),
    }
