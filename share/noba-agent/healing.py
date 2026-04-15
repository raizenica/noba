# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Agent-side heal runtime: evaluates server-provided rules locally."""
from __future__ import annotations

import operator as _op
import re as _re
import threading
import time

from utils import _PLATFORM

_HEAL_OPS = {
    ">": _op.gt, "<": _op.lt, ">=": _op.ge, "<=": _op.le,
    "==": _op.eq, "!=": _op.ne,
}

_HEAL_COND_RE = _re.compile(
    r"^\s*([a-zA-Z0-9_\[\]\.]+)\s*(>|<|>=|<=|==|!=)\s*([0-9\.-]+)\s*$"
)


def _heal_eval_single(cond: str, flat: dict) -> bool:
    """Evaluate a single metric comparison (e.g. 'cpu_percent > 90')."""
    m = _HEAL_COND_RE.match(cond)
    if not m:
        return False
    metric, op, val = m.groups()
    if metric not in flat:
        return False
    try:
        return _HEAL_OPS[op](float(flat[metric]), float(val))
    except (ValueError, TypeError):
        return False


def _heal_eval(cond: str, flat: dict) -> bool:
    """Evaluate a condition string, supporting AND/OR."""
    if " AND " in cond:
        return all(_heal_eval_single(p.strip(), flat) for p in cond.split(" AND "))
    if " OR " in cond:
        return any(_heal_eval_single(p.strip(), flat) for p in cond.split(" OR "))
    return _heal_eval_single(cond, flat)


def _heal_flatten(metrics: dict) -> dict:
    """Flatten metrics dict for condition evaluation."""
    flat: dict = {}
    for k, v in metrics.items():
        if isinstance(v, (int, float, str)):
            flat[k] = v
        elif isinstance(v, list):
            for i, item in enumerate(v):
                if isinstance(item, dict):
                    for sk, sv in item.items():
                        if isinstance(sv, (int, float)):
                            flat[f"{k}[{i}].{sk}"] = sv
    return flat


# Map heal action types to existing agent command handlers
if _PLATFORM == "windows":
    _HEAL_ACTION_MAP = {
        "restart_container": ("container_control", lambda p: {"name": p.get("container", ""), "action": "restart"}),
        "restart_service": ("restart_service", lambda p: {"service": p.get("service", p.get("target", ""))}),
        "clear_cache": ("exec", lambda p: {"command": p.get("command", "Clear-RecycleBin -Force -ErrorAction SilentlyContinue; Write-Output 'Cache cleared'")}),
        "flush_dns": ("exec", lambda p: {"command": p.get("command", "Clear-DnsClientCache; ipconfig /flushdns")}),
    }
else:
    _HEAL_ACTION_MAP = {
        "restart_container": ("container_control", lambda p: {"name": p.get("container", ""), "action": "restart"}),
        "restart_service": ("restart_service", lambda p: {"service": p.get("service", p.get("target", ""))}),
        "clear_cache": ("exec", lambda p: {"command": p.get("command", "sync && echo 3 > /proc/sys/vm/drop_caches")}),
        "flush_dns": ("exec", lambda p: {"command": p.get("command", "systemd-resolve --flush-caches 2>/dev/null || resolvectl flush-caches 2>/dev/null || true")}),
    }


class HealRuntime:
    """Agent-side heal runtime: evaluates server-provided rules locally."""

    def __init__(self) -> None:
        self._policy: dict = {}
        self._cooldowns: dict[str, float] = {}
        self._reports: list[dict] = []
        self._lock = threading.Lock()

    def update_policy(self, policy: dict) -> None:
        """Update the heal policy from server heartbeat response."""
        with self._lock:
            self._policy = policy

    def evaluate(self, metrics: dict, ctx: dict) -> None:
        """Evaluate heal rules against current metrics and execute if needed."""
        # Import here to avoid circular import at module load time
        from commands import execute_commands
        from metrics import collect_metrics

        with self._lock:
            rules = self._policy.get("rules", [])
            if not rules:
                return

        flat = _heal_flatten(metrics)
        now = time.time()

        for rule in rules:
            rule_id = rule.get("rule_id", "")
            condition = rule.get("condition", "")
            action_type = rule.get("action_type", "")
            trust = rule.get("trust_level", "notify")

            if not condition or not action_type:
                continue

            if trust != "execute":
                continue

            with self._lock:
                if now < self._cooldowns.get(rule_id, 0):
                    continue

            if not _heal_eval(condition, flat):
                continue

            cooldown_s = rule.get("cooldown_s", 300)
            with self._lock:
                self._cooldowns[rule_id] = now + cooldown_s

            mapping = _HEAL_ACTION_MAP.get(action_type)
            if not mapping:
                continue

            cmd_type, param_builder = mapping
            params = param_builder(rule.get("action_params", {}))
            metrics_before = dict(flat)
            start = time.time()

            print(f"[agent-heal] Executing {action_type} for rule {rule_id}")

            cmd_obj = {"type": cmd_type, "id": f"heal-{rule_id}", "params": params}
            try:
                results = execute_commands([cmd_obj], ctx)
                result = results[0] if results else {"status": "error", "error": "no result"}
            except Exception as e:
                result = {"status": "error", "error": str(e)}

            success = result.get("status") == "ok"
            duration = round(time.time() - start, 2)

            time.sleep(min(rule.get("verify_delay", 5), 15))
            fresh = _heal_flatten(collect_metrics())
            verified = not _heal_eval(condition, fresh)

            status_str = "verified" if verified else ("success" if success else "failed")
            print(f"[agent-heal] {action_type} for {rule_id}: {status_str} ({duration}s)")

            report_entry = {
                "rule_id": rule_id,
                "condition": condition,
                "action_type": action_type,
                "action_params": rule.get("action_params", {}),
                "success": success,
                "verified": verified,
                "duration_s": duration,
                "metrics_before": metrics_before,
                "metrics_after": dict(fresh),
                "trust_level": trust,
            }
            with self._lock:
                self._reports.append(report_entry)

    def drain_reports(self) -> list[dict]:
        """Return and clear buffered heal reports for the next heartbeat."""
        with self._lock:
            reports = self._reports[:]
            self._reports.clear()
            return reports
