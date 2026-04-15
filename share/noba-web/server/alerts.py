# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Alert rule evaluation, notifications, and self-healing engine."""
from __future__ import annotations

import contextlib
import json
import logging
import subprocess
import threading
import time
import urllib.parse
import urllib.request

from .config import NOTIFICATION_COOLDOWN
from .healing.condition_eval import (  # noqa: F401
    safe_eval as _safe_eval,
    safe_eval_single as _safe_eval_single,
)

logger = logging.getLogger("noba")


# ── Alert state (thread-safe) ─────────────────────────────────────────────────
class AlertState:
    """Tracks sent-alert cooldowns and per-rule heal state with full locking."""

    def __init__(self) -> None:
        self._lock        = threading.Lock()
        self._sent:  dict = {}   # key -> last_sent_timestamp
        self._heals: dict = {}   # rule_id -> heal state dict
        self._group_buffer: dict = {}  # group_key -> list of messages

    def cooldown_ok(self, key: str, cooldown: float = NOTIFICATION_COOLDOWN) -> bool:
        """Return True if enough time has passed to send another alert for this key."""
        with self._lock:
            if time.time() - self._sent.get(key, 0) >= cooldown:
                self._sent[key] = time.time()
                return True
        return False

    def heal_state(self, rule_id: str) -> dict:
        with self._lock:
            return dict(self._heals.setdefault(rule_id, {
                "retries": 0, "trigger_times": [], "circuit_open": False, "circuit_open_at": 0,
            }))

    def update_heal(self, rule_id: str, **kwargs) -> None:
        with self._lock:
            state = self._heals.setdefault(rule_id, {
                "retries": 0, "trigger_times": [], "circuit_open": False, "circuit_open_at": 0,
            })
            state.update(kwargs)

    def append_trigger(self, rule_id: str, ts: float) -> None:
        with self._lock:
            state = self._heals.setdefault(rule_id, {
                "retries": 0, "trigger_times": [], "circuit_open": False, "circuit_open_at": 0,
            })
            state["trigger_times"] = [t for t in state["trigger_times"] if ts - t < 3600]
            state["trigger_times"].append(ts)

    def trigger_count(self, rule_id: str) -> int:
        with self._lock:
            return len(self._heals.get(rule_id, {}).get("trigger_times", []))

    def increment_retries(self, rule_id: str) -> int:
        with self._lock:
            state = self._heals.setdefault(rule_id, {
                "retries": 0, "trigger_times": [], "circuit_open": False, "circuit_open_at": 0,
            })
            state["retries"] += 1
            return state["retries"]

    def reset_retries(self, rule_id: str) -> None:
        with self._lock:
            if rule_id in self._heals:
                self._heals[rule_id]["retries"] = 0

    def buffer_group(self, group: str, msg: str) -> None:
        with self._lock:
            self._group_buffer.setdefault(group, []).append(msg)

    def flush_group(self, group: str) -> list[str]:
        with self._lock:
            return self._group_buffer.pop(group, [])


_alert_state = AlertState()



# ── Self-heal: agent_command helper ───────────────────────────────────────────
def _execute_heal_agent_command(action_cfg: dict, rule_id: str) -> bool:
    """Execute a self-healing action that sends a command to a remote agent."""
    from .agent_store import queue_agent_command_and_wait

    hostname = action_cfg.get("hostname", "")
    cmd_type = action_cfg.get("command", "")
    params = action_cfg.get("params", {})
    timeout = int(action_cfg.get("timeout", 30))

    if not hostname or not cmd_type:
        logger.warning("Heal agent_command for rule %s: missing hostname or command", rule_id)
        return False

    try:
        result = queue_agent_command_and_wait(
            hostname, cmd_type, params, timeout=timeout, queued_by=f"heal:{rule_id}",
        )
        if result is None:
            logger.warning("Heal agent_command %s on %s timed out for rule %s",
                           cmd_type, hostname, rule_id)
            return False

        # For __all__ broadcasts
        if isinstance(result, dict) and result.get("__all__"):
            results = result.get("results", {})
            failures = [h for h, r in results.items() if r is None or r.get("status") == "error"]
            success = len(failures) == 0
            logger.info("Heal agent_command %s broadcast: %d/%d succeeded for rule %s",
                        cmd_type, len(results) - len(failures), len(results), rule_id)
            return success

        status = result.get("status", "error")
        logger.info("Heal agent_command %s on %s: %s (rule %s)",
                     cmd_type, hostname, status, rule_id)
        return status != "error"
    except Exception as e:
        logger.error("Heal agent_command %s/%s failed: %s", cmd_type, hostname, e)
        return False


# ── New action types delegated to remediation module ─────────────────────────
_REMEDIATION_ACTION_TYPES = frozenset({
    "flush_dns", "clear_cache", "trigger_backup",
    "failover_dns", "scale_container", "run_playbook",
})


# ── Self-heal action executor ─────────────────────────────────────────────────
def _execute_heal(action_cfg: dict, rule_id: str, read_settings_fn) -> bool:
    atype  = action_cfg.get("type", "")
    target = action_cfg.get("target", "").strip() if action_cfg.get("target") else ""
    if not atype:
        return False

    # Delegate new action types to the remediation module
    if atype in _REMEDIATION_ACTION_TYPES:
        from . import remediation
        params = {k: v for k, v in action_cfg.items() if k not in ("type",)}
        result = remediation.execute_action(atype, params, triggered_by=f"heal:{rule_id}")
        success = result.get("success", False)
        if success:
            logger.info("Heal remediation %s succeeded for rule %s: %s",
                        atype, rule_id, result.get("output", ""))
        else:
            logger.warning("Heal remediation %s failed for rule %s: %s",
                           atype, rule_id, result.get("error") or result.get("output", ""))
        return success

    # agent_command doesn't use 'target' — it uses hostname/command/params
    if atype == "agent_command":
        return _execute_heal_agent_command(action_cfg, rule_id)

    if not target:
        return False
    try:
        if atype == "run":
            import shlex
            r = subprocess.run(shlex.split(target), timeout=60, capture_output=True)
            logger.info("Heal run %s → rc=%d", target, r.returncode)
            return r.returncode == 0

        if atype == "restart_service":
            svc = target if target.endswith(".service") else f"{target}.service"
            cmd = ["systemctl", "--no-ask-password", "restart", svc]
            if subprocess.os.geteuid() != 0:
                cmd = ["sudo", "-n"] + cmd
            r = subprocess.run(cmd, timeout=30, capture_output=True)
            logger.info("Heal restart_service %s → rc=%d", svc, r.returncode)
            return r.returncode == 0

        if atype == "restart_container":
            runtime, ct = target.split(":", 1) if ":" in target else ("docker", target)
            r = subprocess.run([runtime, "restart", ct], timeout=30, capture_output=True)
            logger.info("Heal restart_container %s via %s → rc=%d", ct, runtime, r.returncode)
            return r.returncode == 0

        if atype == "webhook":
            cfg  = read_settings_fn()
            hook = next((a for a in cfg.get("automations", []) if a.get("id") == target), None)
            if not hook or not hook.get("url"):
                return False
            req = urllib.request.Request(hook["url"], method=hook.get("method", "POST").upper())
            for k, v in (hook.get("headers") or {}).items():
                req.add_header(str(k).replace("\n", ""), str(v).replace("\n", ""))
            with urllib.request.urlopen(req, timeout=8) as r:
                return 200 <= r.getcode() < 300

        if atype == "automation":
            from .db import db
            from .runner import job_runner
            auto = db.get_automation(target)
            if not auto:
                logger.warning("Heal automation '%s' not found", target)
                return False
            from .workflow_engine import _AUTO_BUILDERS, _run_workflow
            if auto["type"] == "workflow":
                steps = auto["config"].get("steps", [])
                if steps:
                    _run_workflow(auto["id"], steps, "alert:" + rule_id)
                    return True
                return False
            builder = _AUTO_BUILDERS.get(auto["type"])
            if not builder:
                return False
            config = auto["config"]

            def make_process(_run_id: int) -> subprocess.Popen | None:
                return builder(config)

            try:
                job_runner.submit(
                    make_process,
                    automation_id=auto["id"],
                    trigger=f"alert:{rule_id}",
                    triggered_by="alert:" + rule_id,
                )
                logger.info("Heal triggered automation '%s' for rule %s", auto["name"], rule_id)
                return True
            except RuntimeError as exc:
                logger.warning("Heal automation submit failed: %s", exc)
                return False

    except Exception as e:
        logger.error("Heal action %s/%s failed: %s", atype, target, e)
    return False


# ── Notification dispatchers ──────────────────────────────────────────────────
def _send_email(level: str, msg: str, cfg: dict) -> None:
    try:
        import smtplib
        from email.message import EmailMessage
        smtp, user, passwd = cfg.get("smtp_server", ""), cfg.get("username", ""), cfg.get("password", "")
        from_a, to_a       = cfg.get("from", ""), cfg.get("to", "")
        if smtp and user and passwd and from_a and to_a:
            em = EmailMessage()
            em.set_content(f"NOBA Alert [{level}]: {msg}")
            em["Subject"] = f"NOBA {level.upper()} Alert"
            em["From"]    = from_a
            em["To"]      = to_a
            with smtplib.SMTP(smtp) as s:
                if cfg.get("starttls"):
                    s.starttls()
                s.login(user, passwd)
                s.send_message(em)
    except Exception as e:
        logger.error("Email notification failed: %s", e)


def _send_telegram(level: str, msg: str, cfg: dict) -> None:
    try:
        token, chat_id = cfg.get("bot_token", ""), cfg.get("chat_id", "")
        if token and chat_id:
            data = urllib.parse.urlencode({"chat_id": chat_id, "text": f"*NOBA {level.upper()}*: {msg}"}).encode()
            req  = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=data, headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.error("Telegram notification failed: %s", e)


def _send_discord(level: str, msg: str, cfg: dict) -> None:
    try:
        webhook = cfg.get("webhook_url", "")
        if webhook:
            payload = json.dumps({"content": f"**NOBA {level.upper()}**\n{msg}"}).encode()
            req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.error("Discord notification failed: %s", e)


def _send_slack(level: str, msg: str, cfg: dict) -> None:
    try:
        webhook = cfg.get("webhook_url", "")
        if webhook:
            payload = json.dumps({"text": f"*NOBA {level.upper()} Alert*\n{msg}"}).encode()
            req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.error("Slack notification failed: %s", e)


def _send_pushover(level: str, msg: str, cfg: dict) -> None:
    try:
        app_token = cfg.get("app_token", "")
        user_key  = cfg.get("user_key",  "")
        if app_token and user_key:
            data = urllib.parse.urlencode({
                "token":    app_token,
                "user":     user_key,
                "title":    f"NOBA {level.upper()} Alert",
                "message":  msg,
                "priority": "1" if level in ("danger", "critical") else "0",
            }).encode()
            req = urllib.request.Request(
                "https://api.pushover.net/1/messages.json",
                data=data, headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.error("Pushover notification failed: %s", e)


def _send_gotify(level: str, msg: str, cfg: dict) -> None:
    try:
        url   = cfg.get("url", "").rstrip("/")
        token = cfg.get("app_token", "")
        if url and token:
            payload = json.dumps({
                "title":    f"NOBA {level.upper()} Alert",
                "message":  msg,
                "priority": 8 if level in ("danger", "critical") else 5,
            }).encode()
            req = urllib.request.Request(
                f"{url}/message",
                data=payload, headers={"Content-Type": "application/json", "X-Gotify-Key": token},
            )
            urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.error("Gotify notification failed: %s", e)


_SENDERS = {
    "email":    _send_email,
    "telegram": _send_telegram,
    "discord":  _send_discord,
    "slack":    _send_slack,
    "pushover": _send_pushover,
    "gotify":   _send_gotify,
}


def dispatch_notifications(level: str, msg: str, notif_cfg: dict, channels: list | None = None) -> None:
    targets = channels if channels else list(_SENDERS.keys())
    for ch in targets:
        fn     = _SENDERS.get(ch)
        ch_cfg = notif_cfg.get(ch, {})
        if fn and ch_cfg.get("enabled"):
            fn(level, msg, ch_cfg)


def send_notification(level: str, msg: str, category: str | None, read_settings_fn) -> None:
    key = category or msg
    if not _alert_state.cooldown_ok(key):
        return
    cfg = read_settings_fn()
    notif_cfg = cfg.get("notifications", {})
    if not notif_cfg:
        return
    threading.Thread(
        target=dispatch_notifications, args=(level, msg, notif_cfg, None), daemon=True
    ).start()


# ── Escalation policies ──────────────────────────────────────────────────────
def _check_escalation(rule: dict, rule_id: str, severity: str, message: str,
                      notif_cfg: dict, read_settings_fn) -> None:
    """Check escalation tiers for a rule."""
    escalation = rule.get("escalation", [])
    if not escalation:
        return
    state = _alert_state.heal_state(rule_id)
    first_trigger = state.get("first_trigger_at", 0)
    if not first_trigger:
        _alert_state.update_heal(rule_id, first_trigger_at=time.time())
        return
    elapsed_min = (time.time() - first_trigger) / 60
    for tier in escalation:
        delay = tier.get("delay_minutes", 0)
        if elapsed_min >= delay:
            channels = tier.get("channels", [])
            if channels:
                dispatch_notifications(severity, f"[ESCALATED] {message}", notif_cfg, channels)


# ── Maintenance window check ─────────────────────────────────────────────────
def in_maintenance_window(read_settings_fn) -> bool:
    """Check if current time falls within any configured maintenance window."""
    from datetime import datetime

    from .scheduler import _match_cron

    # Check YAML-configured windows (backward compat)
    cfg = read_settings_fn()
    windows = cfg.get("maintenanceWindows", [])
    now = datetime.now()
    for window in windows:
        start_cron = window.get("start", "")
        duration_min = int(window.get("duration_minutes", 60))
        if start_cron and _match_cron(start_cron, now):
            # Check if we are within the maintenance window duration
            # For cron-based windows, the match triggers at the start minute;
            # any time within duration_min minutes of that is in-window.
            _ = duration_min  # reserved for duration-aware window matching
            return True

    # Also check DB-backed windows
    try:
        from .db import db
        active = db.get_active_maintenance_windows()
        if active:
            return True
    except Exception:
        pass

    return False


# ── Alert rule evaluator ──────────────────────────────────────────────────────
def evaluate_alert_rules(stats: dict, read_settings_fn) -> None:
    cfg   = read_settings_fn()
    rules = cfg.get("alertRules", [])
    if not rules:
        return

    # Build flat metric dict for condition evaluation
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

    for rule in rules:
        try:
            rule_id   = rule.get("id", "unknown")
            condition = rule.get("condition", "")
            if not condition or not _safe_eval(condition, flat):
                continue

            # ── Autonomy enforcement ───────────────────────────────────────
            autonomy = rule.get("autonomy", "execute")

            # Check for maintenance window autonomy override and suppression
            from .db import db as _db
            active_windows = _db.get_active_maintenance_windows()
            suppress_notifications = False
            for window in active_windows:
                if window.get("override_autonomy"):
                    autonomy = window["override_autonomy"]
                    break
            for window in active_windows:
                if window.get("suppress_alerts") is True:
                    suppress_notifications = True
                    break

            # disabled: skip entirely — no notification, no action
            if autonomy == "disabled":
                continue

            now      = time.time()
            severity = rule.get("severity", "warning")
            message  = rule.get("message", condition)
            channels = rule.get("channels", [])

            if not _alert_state.cooldown_ok(rule_id):
                continue

            notif_cfg = cfg.get("notifications", {})

            # notify / approve: dispatch notification (possibly modified message)
            # skip notification dispatch when a maintenance window suppresses alerts
            if not suppress_notifications and autonomy in ("execute", "notify", "approve"):
                if autonomy == "approve":
                    dispatch_notifications(
                        severity,
                        f"[APPROVAL NEEDED] {message}",
                        notif_cfg,
                        channels,
                    )
                else:
                    dispatch_notifications(severity, message, notif_cfg, channels)

            # Record alert in history
            logger.info(
                "Alert fired: %s", rule_id,
                extra={"rule_id": rule_id, "severity": severity, "autonomy": autonomy},
            )
            _db.insert_alert_history(rule_id, severity, message)

            # Auto-create incident
            try:
                incident_id = _db.insert_incident(severity, "alert", message, condition)
            except Exception:
                incident_id = 0

            # auto_close_alerts: if alert condition is met during a maintenance window
            # with auto_close enabled and the alert was just inserted, resolve it immediately
            if incident_id:
                for window in active_windows:
                    if window.get("auto_close_alerts"):
                        with contextlib.suppress(Exception):
                            _db.resolve_incident(incident_id)
                        break

            # Check escalation policies
            _check_escalation(rule, rule_id, severity, message, notif_cfg, read_settings_fn)

            action_cfg = rule.get("action")
            if not action_cfg or not isinstance(action_cfg, dict):
                continue

            # ── Healing pipeline integration ──────────────────────────
            try:
                from .healing import get_pipeline
                from .healing.models import HealEvent

                heal_event = HealEvent(
                    source="alert",
                    rule_id=rule_id,
                    condition=condition,
                    target=action_cfg.get("target", ""),
                    severity=severity,
                    timestamp=now,
                    metrics=dict(flat),
                )
                # Build rules config from alert rule
                chain = rule.get("escalation_chain", [])
                if not chain:
                    # Try default chain based on rule_id pattern
                    from .healing.default_rules import get_chain_for_rule_id
                    chain = get_chain_for_rule_id(rule_id) or []
                if not chain and action_cfg:
                    # Legacy: single action, wrap as chain
                    chain = [{"action": action_cfg.get("type", ""), "params": action_cfg.get("params", {})}]

                pipeline = get_pipeline()  # module-level singleton
                pipeline.update_rule_config(rule_id, {"escalation_chain": chain})
                pipeline.handle_heal_event(heal_event)
            except Exception as exc:
                logger.error("Healing pipeline error for rule %s: %s", rule_id, exc)

        except Exception as e:
            logger.error("Error evaluating rule %s: %s", rule.get("id"), e)


# ── Built-in threshold alerts ─────────────────────────────────────────────────
def build_threshold_alerts(stats: dict, read_settings_fn) -> list:
    if in_maintenance_window(read_settings_fn):
        return []

    alerts = []

    cpu = stats.get("cpuPercent", 0)
    if cpu > 90:
        alerts.append({"level": "danger",  "msg": f"CPU critical: {cpu}%"})
        send_notification("danger",  f"CPU critical: {cpu}%",  "cpu_crit", read_settings_fn)
    elif cpu > 75:
        alerts.append({"level": "warning", "msg": f"CPU high: {cpu}%"})
        send_notification("warning", f"CPU high: {cpu}%",      "cpu_high", read_settings_fn)

    ct = stats.get("cpuTemp", "N/A")
    if ct != "N/A":
        try:
            t = int(ct.replace("°C", ""))
            if t > 85:
                alerts.append({"level": "danger",  "msg": f"CPU temp critical: {t}°C"})
                send_notification("danger",  f"CPU temp critical: {t}°C", "temp_crit", read_settings_fn)
            elif t > 70:
                alerts.append({"level": "warning", "msg": f"CPU temp elevated: {t}°C"})
                send_notification("warning", f"CPU temp elevated: {t}°C", "temp_high", read_settings_fn)
        except ValueError:
            pass

    for disk in stats.get("disks", []):
        p     = disk.get("percent", 0)
        mount = disk.get("mount", "?")
        if p >= 90:
            alerts.append({"level": "danger",  "msg": f"Disk {mount} at {p}%"})
            send_notification("danger",  f"Disk {mount} at {p}%", f"disk_crit_{mount}", read_settings_fn)
            _emit_threshold_heal_event(
                f"disk_crit_{mount}", "disk_percent >= 90", mount, "danger", stats,
            )
        elif p >= 80:
            alerts.append({"level": "warning", "msg": f"Disk {mount} at {p}%"})
            send_notification("warning", f"Disk {mount} at {p}%", f"disk_high_{mount}", read_settings_fn)

    for svc in stats.get("services", []):
        if svc.get("status") == "failed":
            alerts.append({"level": "danger", "msg": f"Service failed: {svc['name']}"})
            send_notification("danger", f"Service failed: {svc['name']}", f"svc_{svc['name']}", read_settings_fn)
            _emit_threshold_heal_event(
                f"svc_{svc['name']}", "service_status == failed",
                svc["name"], "danger", stats,
            )

    tn = stats.get("truenas")
    if tn and tn.get("status") == "online":
        for alert in tn.get("alerts", []):
            if alert.get("level") in ("WARNING", "CRITICAL"):
                lvl = "danger" if alert["level"] == "CRITICAL" else "warning"
                txt = alert.get("text", "")
                alerts.append({"level": lvl, "msg": f"TrueNAS: {txt}"})
                send_notification(lvl, f"TrueNAS: {txt}", f"tn_{txt[:20]}", read_settings_fn)

    # Emit heal events for CPU/disk threshold breaches
    if cpu > 90:
        _emit_threshold_heal_event("cpu_crit", "cpuPercent > 90", "system", "danger", stats)
    if stats.get("memPercent", 0) > 90:
        _emit_threshold_heal_event(
            "mem_crit", "memPercent > 90", "system", "danger", stats,
        )

    return alerts


def _emit_threshold_heal_event(
    rule_id: str, condition: str, target: str, severity: str, stats: dict,
) -> None:
    """Feed a built-in threshold alert into the healing pipeline.

    Uses default escalation chains from healing.default_rules.
    Events go through the full pipeline: correlation, dependency check,
    trust governor, pre-flight, execution, verification.
    """
    try:
        from .healing import get_pipeline
        from .healing.default_rules import get_chain_for_rule_id
        from .healing.models import HealEvent

        chain = get_chain_for_rule_id(rule_id)
        if not chain:
            return  # no default chain for this scenario

        event = HealEvent(
            source="threshold",
            rule_id=rule_id,
            condition=condition,
            target=target,
            severity=severity,
            timestamp=time.time(),
            metrics=dict(stats) if isinstance(stats, dict) else {},
        )

        pipeline = get_pipeline()
        pipeline.update_rule_config(rule_id, {"escalation_chain": chain})
        pipeline.handle_heal_event(event)
    except Exception as exc:
        logger.debug("Threshold heal event failed for %s: %s", rule_id, exc)


# ── Historical anomaly detection ─────────────────────────────────────────────
_ANOMALY_METRICS = {
    "cpu_percent": ("CPU", "%"),
    "mem_percent": ("Memory", "%"),
    "cpu_temp":    ("CPU Temp", "°C"),
}


def check_anomalies(db_instance, read_settings_fn) -> list:
    """Check recent metrics against historical patterns and notify on anomalies."""
    alerts = []
    for metric, (label, unit) in _ANOMALY_METRICS.items():
        try:
            points = db_instance.get_history(metric, range_hours=6, resolution=60, anomaly=True)
            if len(points) < 10:
                continue
            latest = points[-1]
            if not latest.get("anomaly"):
                continue
            val = latest["value"]
            upper = latest.get("upper_band", 0)
            lower = latest.get("lower_band", 0)
            direction = "above" if val > upper else "below"
            msg = f"Anomaly: {label} {val}{unit} ({direction} normal range {lower:.0f}–{upper:.0f}{unit})"
            alerts.append({"level": "warning", "msg": msg})
            send_notification("warning", msg, f"anomaly_{metric}", read_settings_fn)
        except Exception as e:
            logger.debug("Anomaly check failed for %s: %s", metric, e)
    return alerts
