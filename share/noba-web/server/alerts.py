"""Noba – Alert rule evaluation, notifications, and self-healing engine."""
from __future__ import annotations

import json
import logging
import operator
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from typing import Any

from .config import NOTIFICATION_COOLDOWN

logger = logging.getLogger("noba")


# ── Alert state (thread-safe) ─────────────────────────────────────────────────
class AlertState:
    """Tracks sent-alert cooldowns and per-rule heal state with full locking."""

    def __init__(self) -> None:
        self._lock        = threading.Lock()
        self._sent:  dict = {}   # key -> last_sent_timestamp
        self._heals: dict = {}   # rule_id -> heal state dict

    def cooldown_ok(self, key: str, cooldown: float = NOTIFICATION_COOLDOWN) -> bool:
        """Return True if enough time has passed to send another alert for this key."""
        with self._lock:
            if time.time() - self._sent.get(key, 0) >= cooldown:
                self._sent[key] = time.time()
                return True
        return False

    def heal_state(self, rule_id: str) -> dict:
        with self._lock:
            return self._heals.setdefault(rule_id, {
                "retries": 0, "trigger_times": [], "circuit_open": False, "circuit_open_at": 0,
            })

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


_alert_state = AlertState()


# ── Safe condition evaluator ──────────────────────────────────────────────────
_OPS = {">": operator.gt, "<": operator.lt, ">=": operator.ge, "<=": operator.le,
        "==": operator.eq, "!=": operator.ne}


def _safe_eval(condition_str: str, flat: dict) -> bool:
    s = condition_str.replace("flat['", "").replace('flat["', "").replace("']", "").replace('"]', "")
    m = re.match(r"^\s*([a-zA-Z0-9_\[\]\.]+)\s*(>|<|>=|<=|==|!=)\s*([0-9\.-]+)\s*$", s)
    if m:
        metric, op, val = m.groups()
        if metric in flat:
            try:
                return _OPS[op](float(flat[metric]), float(val))
            except ValueError:
                pass
    return False


# ── Self-heal action executor ─────────────────────────────────────────────────
def _execute_heal(action_cfg: dict, rule_id: str, read_settings_fn) -> bool:
    atype  = action_cfg.get("type", "")
    target = action_cfg.get("target", "").strip()
    if not atype or not target:
        return False
    try:
        if atype == "run":
            import shlex
            r = subprocess.run(shlex.split(target), timeout=60, capture_output=True)
            logger.info("Heal run %s → rc=%d", target, r.returncode)
            return r.returncode == 0

        if atype == "restart_service":
            svc = target if target.endswith(".service") else f"{target}.service"
            cmd = ["systemctl", "restart", svc]
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
                f"{url}/message?token={token}",
                data=payload, headers={"Content-Type": "application/json"},
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

            now      = time.time()
            severity = rule.get("severity", "warning")
            message  = rule.get("message", condition)
            channels = rule.get("channels", [])

            if not _alert_state.cooldown_ok(rule_id):
                continue

            dispatch_notifications(severity, message, cfg.get("notifications", {}), channels)

            action_cfg = rule.get("action")
            if not action_cfg or not isinstance(action_cfg, dict):
                continue

            max_retries         = int(rule.get("max_retries", 3))
            circuit_break_after = int(rule.get("circuit_break_after", 5))

            _alert_state.append_trigger(rule_id, now)
            state = _alert_state.heal_state(rule_id)

            if _alert_state.trigger_count(rule_id) >= circuit_break_after:
                if not state["circuit_open"]:
                    _alert_state.update_heal(rule_id, circuit_open=True, circuit_open_at=now)
                    logger.warning("Heal circuit OPEN for rule %s", rule_id)
                    dispatch_notifications(
                        "danger",
                        f'[Circuit Open] Rule "{rule_id}" triggered {_alert_state.trigger_count(rule_id)}× in 1 hour. '
                        "Auto-healing suspended.",
                        cfg.get("notifications", {}), channels,
                    )
                continue

            if state["circuit_open"] and now - state["circuit_open_at"] >= 3600:
                _alert_state.update_heal(rule_id, circuit_open=False, retries=0, trigger_times=[])
                logger.info("Heal circuit CLOSED for rule %s", rule_id)

            if state["circuit_open"]:
                continue

            if state["retries"] >= max_retries:
                logger.warning("Max retries reached for rule %s", rule_id)
                continue

            retries = _alert_state.increment_retries(rule_id)
            success = _execute_heal(action_cfg, rule_id, read_settings_fn)
            if success:
                logger.info("Heal succeeded for rule %s (attempt %d)", rule_id, retries)
                _alert_state.reset_retries(rule_id)
            else:
                logger.warning("Heal attempt %d/%d failed for rule %s", retries, max_retries, rule_id)

        except Exception as e:
            logger.error("Error evaluating rule %s: %s", rule.get("id"), e)


# ── Built-in threshold alerts ─────────────────────────────────────────────────
def build_threshold_alerts(stats: dict, read_settings_fn) -> list:
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
        elif p >= 80:
            alerts.append({"level": "warning", "msg": f"Disk {mount} at {p}%"})
            send_notification("warning", f"Disk {mount} at {p}%", f"disk_high_{mount}", read_settings_fn)

    for svc in stats.get("services", []):
        if svc.get("status") == "failed":
            alerts.append({"level": "danger", "msg": f"Service failed: {svc['name']}"})
            send_notification("danger", f"Service failed: {svc['name']}", f"svc_{svc['name']}", read_settings_fn)

    tn = stats.get("truenas")
    if tn and tn.get("status") == "online":
        for alert in tn.get("alerts", []):
            if alert.get("level") in ("WARNING", "CRITICAL"):
                lvl = "danger" if alert["level"] == "CRITICAL" else "warning"
                txt = alert.get("text", "")
                alerts.append({"level": lvl, "msg": f"TrueNAS: {txt}"})
                send_notification(lvl, f"TrueNAS: {txt}", f"tn_{txt[:20]}", read_settings_fn)

    return alerts
