# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Infrastructure Health Score computation (Feature 7).

Computes a 0-100 score from data already collected:
agents, endpoint monitors, SLA history, and live metrics.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("noba")


def _clamp(v: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, v))


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
        online_agents = sum(
            1 for d in agent_store_data.values()
            if now - d.get("_received", 0) < max_age
        )
        if total_agents > 0:
            ratio = online_agents / total_agents
            score_monitoring = _clamp(ratio * 10)
        else:
            # No agents configured — neutral (full marks, nothing to penalise)
            score_monitoring = 10.0
        recommendations = []
        if total_agents > 0 and online_agents < total_agents:
            offline = total_agents - online_agents
            recommendations.append(f"{offline} agent(s) offline -- check connectivity")
        categories["monitoring_coverage"] = {
            "score": round(score_monitoring, 1),
            "max": 10,
            "status": "ok" if score_monitoring >= 8 else "warning" if score_monitoring >= 5 else "critical",
            "detail": f"{online_agents}/{total_agents} agents online",
            "recommendations": recommendations,
        }
    except Exception as exc:
        logger.warning("health_score: monitoring_coverage failed: %s", exc)
        categories["monitoring_coverage"] = {
            "score": 10, "max": 10, "status": "ok",
            "detail": "N/A", "recommendations": [],
        }

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
        else:
            score_certs = 10.0  # No certs to check — full marks
        categories["certificate_health"] = {
            "score": round(_clamp(score_certs), 1),
            "max": 10,
            "status": "ok" if score_certs >= 8 else "warning" if score_certs >= 5 else "critical",
            "detail": f"{len(cert_scores)} certificate(s) tracked",
            "recommendations": cert_recs[:5],
        }
    except Exception as exc:
        logger.warning("health_score: certificate_health failed: %s", exc)
        categories["certificate_health"] = {
            "score": 10, "max": 10, "status": "ok",
            "detail": "N/A", "recommendations": [],
        }

    # ── 3. Update status (0-10) ──────────────────────────────────────────
    # Check if any agents report pending package updates via their metrics.
    try:
        update_recs: list[str] = []
        agents_with_updates = 0
        for hostname, adata in agent_store_data.items():
            pkg_updates = adata.get("package_updates") or adata.get("pending_updates")
            if pkg_updates and isinstance(pkg_updates, (int, float)) and pkg_updates > 0:
                agents_with_updates += 1
                update_recs.append(f"{hostname}: {int(pkg_updates)} update(s) pending")
        if total_agents > 0:
            up_ratio = 1 - min(agents_with_updates / max(total_agents, 1), 1)
            score_updates = _clamp(up_ratio * 10)
        else:
            score_updates = 10.0
        categories["update_status"] = {
            "score": round(score_updates, 1),
            "max": 10,
            "status": "ok" if score_updates >= 8 else "warning" if score_updates >= 5 else "critical",
            "detail": f"{agents_with_updates} host(s) with pending updates",
            "recommendations": update_recs[:5],
        }
    except Exception as exc:
        logger.warning("health_score: update_status failed: %s", exc)
        categories["update_status"] = {
            "score": 10, "max": 10, "status": "ok",
            "detail": "N/A", "recommendations": [],
        }

    # ── 4. Uptime / SLA (0-10) ──────────────────────────────────────────
    try:
        # Gather SLA for all active alert rules
        alert_history = db.get_alert_history(limit=20)
        rule_ids = list({a["rule_id"] for a in alert_history})
        sla_values: list[float] = []
        sla_recs: list[str] = []
        for rid in rule_ids[:20]:
            sla = db.get_sla(rid, window_hours=720)  # 30 days
            sla_values.append(sla)
            if sla < 99.0:
                sla_recs.append(f"Rule '{rid}' SLA is {sla:.1f}% (target 99.9%)")
        if sla_values:
            avg_sla = sum(sla_values) / len(sla_values)
            # Map 95-100 SLA to 0-10 score
            score_uptime = _clamp((avg_sla - 95) * 2)
        else:
            score_uptime = 10.0  # No SLA data means nothing to penalize
        categories["uptime"] = {
            "score": round(score_uptime, 1),
            "max": 10,
            "status": "ok" if score_uptime >= 8 else "warning" if score_uptime >= 5 else "critical",
            "detail": f"{len(sla_values)} SLA rule(s), avg {sum(sla_values)/len(sla_values):.1f}%" if sla_values else "No SLA data",
            "recommendations": sla_recs[:5],
        }
    except Exception as exc:
        logger.warning("health_score: uptime failed: %s", exc)
        categories["uptime"] = {
            "score": 10, "max": 10, "status": "ok",
            "detail": "N/A", "recommendations": [],
        }

    # ── 5. Capacity: no disk/CPU/RAM >85% (0-10) ────────────────────────
    try:
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

        for disk in stats.get("disks", []):
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
        categories["capacity"] = {
            "score": 10, "max": 10, "status": "ok",
            "detail": "N/A", "recommendations": [],
        }

    # ── 6. Backup freshness (0-10) ──────────────────────────────────────
    try:
        backup_recs: list[str] = []
        # Check last successful backup job run
        backup_runs = db.get_job_runs(limit=10, trigger_prefix="manual:backup")
        if not backup_runs:
            # Also check scheduled triggers
            backup_runs = db.get_job_runs(limit=10, trigger_prefix="schedule:")
            backup_runs = [r for r in backup_runs
                           if r.get("automation_id") and "backup" in (r.get("automation_id") or "").lower()]

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
        else:
            # No backup history — cannot verify
            score_backup = 5.0
            backup_recs.append("No backup history found -- configure automated backups")

        categories["backup_freshness"] = {
            "score": round(score_backup, 1),
            "max": 10,
            "status": "ok" if score_backup >= 8 else "warning" if score_backup >= 5 else "critical",
            "detail": f"Last backup: {int((now - last_ok) / 3600)}h ago" if last_ok else "No backup data",
            "recommendations": backup_recs[:5],
        }
    except Exception as exc:
        logger.warning("health_score: backup_freshness failed: %s", exc)
        categories["backup_freshness"] = {
            "score": 5, "max": 10, "status": "warning",
            "detail": "N/A", "recommendations": ["Could not evaluate backup status"],
        }

    # ── Compute total ────────────────────────────────────────────────────
    total = sum(c["score"] for c in categories.values())
    max_total = sum(c["max"] for c in categories.values())
    # Normalize to 0-100 scale
    normalized = round((total / max_total) * 100) if max_total > 0 else 0

    return {
        "score": normalized,
        "total_raw": round(total, 1),
        "max_raw": max_total,
        "grade": (
            "A" if normalized >= 90 else
            "B" if normalized >= 75 else
            "C" if normalized >= 60 else
            "D" if normalized >= 40 else "F"
        ),
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


def _calc_uptime_score(db_instance, monitor_id: int, hours: int = 720) -> float:
    """Uptime percentage from check history → 0-100 score."""
    try:
        pct = db_instance.get_endpoint_uptime(monitor_id, hours=hours)
        return min(100.0, pct)  # Already 0-100
    except Exception:
        return 100.0  # No data = assume OK


def _calc_latency_score(db_instance, monitor_id: int, hours: int = 720) -> float:
    """Lower latency = higher score. 0ms=100, 1000ms+=0."""
    try:
        avg_ms = db_instance.get_endpoint_avg_latency(monitor_id, hours=hours)
        if avg_ms is None:
            return 100.0
        return max(0.0, min(100.0, 100.0 - (avg_ms / 10.0)))  # 0ms=100, 1000ms=0
    except Exception:
        return 100.0


def _calc_error_rate_score(db_instance, monitor_id: int, hours: int = 720) -> float:
    """Inverse of error rate. 0% errors=100, 100% errors=0."""
    try:
        uptime = db_instance.get_endpoint_uptime(monitor_id, hours=hours)
        return min(100.0, uptime)  # Uptime IS the inverse of error rate
    except Exception:
        return 100.0


def _calc_headroom_score(monitor: dict) -> float:
    """Response time headroom vs configured timeout."""
    timeout_ms = (monitor.get("timeout") or 10) * 1000
    last_ms = monitor.get("last_response_ms") or 0
    if timeout_ms <= 0:
        return 100.0
    ratio = last_ms / timeout_ms
    return max(0.0, min(100.0, (1.0 - ratio) * 100.0))


def compute_service_health_scores(db_instance) -> dict:
    """Per-service health scoring with weighted composite.

    Weights: uptime (40%) + latency trend (25%) + error rate (20%) + resource headroom (15%)
    """
    import statistics as _statistics

    monitors = db_instance.get_endpoint_monitors(enabled_only=True)
    services = []
    for m in monitors:
        mid = m["id"]
        uptime_score = _calc_uptime_score(db_instance, mid)
        latency_score = _calc_latency_score(db_instance, mid)
        error_score = _calc_error_rate_score(db_instance, mid)
        headroom_score = _calc_headroom_score(m)

        composite = (
            uptime_score * 0.40
            + latency_score * 0.25
            + error_score * 0.20
            + headroom_score * 0.15
        )

        services.append({
            "name": m["name"],
            "url": m.get("url", ""),
            "composite_score": round(composite, 1),
            "breakdown": {
                "uptime": round(uptime_score, 1),
                "latency": round(latency_score, 1),
                "error_rate": round(error_score, 1),
                "headroom": round(headroom_score, 1),
            },
            "grade": _score_to_grade(composite),
        })

    services.sort(key=lambda s: s["composite_score"])
    overall = (
        round(_statistics.mean(s["composite_score"] for s in services), 1)
        if services
        else 100.0
    )
    return {
        "overall": overall,
        "grade": _score_to_grade(overall),
        "services": services,
    }
