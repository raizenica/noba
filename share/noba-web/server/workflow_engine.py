"""Noba -- Workflow engine: automation builders, validation, and workflow execution."""
from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import threading

from fastapi import HTTPException

from .config import ALLOWED_AUTO_TYPES, SCRIPT_DIR, SCRIPT_MAP
from .db import db
from .deps import _safe_int
from .metrics import validate_service_name
from .runner import job_runner
from .yaml_config import read_yaml_settings

logger = logging.getLogger("noba")


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_auto_config(atype: str, config: dict) -> None:
    if atype == "script":
        if not config.get("command") and not config.get("script"):
            raise HTTPException(400, "Script automation requires 'command' or 'script' in config")
    elif atype == "webhook":
        url = config.get("url", "")
        if not url or not url.startswith(("http://", "https://")):
            raise HTTPException(400, "Webhook requires a valid 'url' in config")
    elif atype == "service":
        if not config.get("service"):
            raise HTTPException(400, "Service automation requires 'service' in config")
        if config.get("action", "restart") not in ("start", "stop", "restart"):
            raise HTTPException(400, "Service action must be start, stop, or restart")
    elif atype == "workflow":
        steps = config.get("steps", [])
        if not isinstance(steps, list) or len(steps) < 1:
            raise HTTPException(400, "Workflow requires 'steps' list with at least one automation ID")
    elif atype == "condition":
        if not config.get("condition"):
            raise HTTPException(400, "Condition automation requires 'condition'")
    elif atype == "delay":
        if not config.get("seconds") and not config.get("duration"):
            raise HTTPException(400, "Delay requires 'seconds' or 'duration'")
    elif atype == "notify":
        if not config.get("message"):
            raise HTTPException(400, "Notify requires 'message'")
    elif atype == "http":
        url = config.get("url", "")
        if not url or not url.startswith(("http://", "https://")):
            raise HTTPException(400, "HTTP step requires a valid URL")


# ── Builder functions ─────────────────────────────────────────────────────────

def _build_auto_script_process(config: dict) -> subprocess.Popen | None:
    script_key = config.get("script", "")
    command = config.get("command", "")
    args = config.get("args", "")
    if script_key and script_key in SCRIPT_MAP:
        sfile = os.path.join(SCRIPT_DIR, SCRIPT_MAP[script_key])
        if not os.path.isfile(sfile):
            return None
        cmd = [sfile, "--verbose"]
        if args:
            cmd += shlex.split(args) if isinstance(args, str) else [str(a) for a in args]
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                start_new_session=True, cwd=SCRIPT_DIR)
    if command:
        return subprocess.Popen(["bash", "-c", command],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                start_new_session=True)
    return None


def _build_auto_webhook_process(config: dict) -> subprocess.Popen | None:
    url = config.get("url", "")
    method = config.get("method", "POST").upper()
    body = config.get("body")
    cmd = ["curl", "-sS", "-w", "\n--- HTTP %{http_code} (%{time_total}s) ---", "-X", method]
    for k, v in config.get("headers", {}).items():
        cmd += ["-H", f"{k}: {v}"]
    if body:
        if isinstance(body, (dict, list)):
            cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
        elif isinstance(body, str):
            cmd += ["-d", body]
    cmd.append(url)
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)


def _build_auto_service_process(config: dict) -> subprocess.Popen | None:
    svc = config.get("service", "")
    action = config.get("action", "restart")
    if not svc or not validate_service_name(svc) or action not in ("start", "stop", "restart"):
        return None
    if config.get("is_user"):
        cmd = ["systemctl", "--user", action, svc]
    else:
        cmd = ["sudo", "-n", "systemctl", action, svc]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)


def _build_auto_delay_process(config: dict) -> subprocess.Popen | None:
    seconds = _safe_int(config.get("seconds", config.get("duration", 10)), 10)
    return subprocess.Popen(["sleep", str(seconds)], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, start_new_session=True)


def _build_auto_http_process(config: dict) -> subprocess.Popen | None:
    url = config.get("url", "")
    method = config.get("method", "GET").upper()
    cmd = ["curl", "-sS", "-w", "\n--- HTTP %{http_code} (%{time_total}s) ---", "-X", method]
    for k, v in config.get("headers", {}).items():
        cmd += ["-H", f"{k}: {v}"]
    auth_type = config.get("auth_type", "")
    if auth_type == "bearer":
        cmd += ["-H", f"Authorization: Bearer {config.get('auth_token', '')}"]
    elif auth_type == "basic":
        cmd += ["-u", f"{config.get('auth_user', '')}:{config.get('auth_pass', '')}"]
    body = config.get("body")
    if body:
        if isinstance(body, (dict, list)):
            cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
        elif isinstance(body, str):
            cmd += ["-d", body]
    cmd.append(url)
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)


def _build_auto_notify_process(config: dict) -> subprocess.Popen | None:
    """Dispatch a notification and return a trivial process for status tracking."""
    msg = config.get("message", "Automation notification")
    level = config.get("level", "info")
    channels = config.get("channels")
    try:
        cfg = read_yaml_settings()
        notif_cfg = cfg.get("notifications", {})
        if notif_cfg:
            # Late import to avoid circular dependency: alerts -> workflow_engine
            from .alerts import dispatch_notifications
            threading.Thread(
                target=dispatch_notifications,
                args=(level, msg, notif_cfg, channels),
                daemon=True,
            ).start()
    except Exception as e:
        logger.error("Notify step failed: %s", e)
    # Return a trivial success process so the runner records the step
    return subprocess.Popen(["echo", f"Notification sent: {msg}"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)


def _build_auto_condition_process(config: dict) -> subprocess.Popen | None:
    """Evaluate a condition and exit 0 (true) or 1 (false).

    Workflow engine treats exit 0 as 'done' (proceed to next step)
    and non-zero as 'failed' (stop or retry). This lets conditions
    gate subsequent steps in a sequential workflow.
    """
    condition = config.get("condition", "")
    if not condition:
        return subprocess.Popen(["false"], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, start_new_session=True)
    # Late imports to avoid circular dependency: collector -> alerts -> workflow_engine
    from .collector import bg_collector
    from .alerts import _safe_eval
    stats = bg_collector.get() or {}
    flat: dict = {}
    for k, v in stats.items():
        if isinstance(v, (int, float, str)):
            flat[k] = v
    result = _safe_eval(condition, flat)
    cmd = ["true"] if result else ["false"]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)


# ── Builder registry ──────────────────────────────────────────────────────────

_AUTO_BUILDERS = {
    "script": _build_auto_script_process, "webhook": _build_auto_webhook_process,
    "service": _build_auto_service_process, "delay": _build_auto_delay_process,
    "http": _build_auto_http_process, "notify": _build_auto_notify_process,
    "condition": _build_auto_condition_process,
}
_AUTO_TYPES = ALLOWED_AUTO_TYPES  # from config


# ── Workflow execution ────────────────────────────────────────────────────────

def _run_workflow(auto_id: str, steps: list[str], triggered_by: str,
                  step_idx: int = 0, retries: int = 0, attempt: int = 0) -> None:
    """Chain-execute workflow steps sequentially via on_complete callbacks.

    ``retries`` is the max retry count per step (0 = no retries).
    ``attempt`` tracks the current attempt for the active step.
    """
    if step_idx >= len(steps):
        return
    step_auto_id = steps[step_idx]
    step_auto = db.get_automation(step_auto_id)
    if not step_auto:
        logger.warning("Workflow %s: step %d auto '%s' not found, skipping", auto_id, step_idx, step_auto_id)
        _run_workflow(auto_id, steps, triggered_by, step_idx + 1, retries)
        return

    builder = _AUTO_BUILDERS.get(step_auto["type"])
    if not builder:
        logger.warning("Workflow %s: step %d has unsupported type '%s'", auto_id, step_idx, step_auto["type"])
        _run_workflow(auto_id, steps, triggered_by, step_idx + 1, retries)
        return

    config = step_auto["config"]

    def make_process(_run_id: int) -> subprocess.Popen | None:
        return builder(config)

    def on_step_complete(_run_id: int, status: str) -> None:
        if status == "done":
            _run_workflow(auto_id, steps, triggered_by, step_idx + 1, retries)
        elif retries > 0 and attempt < retries:
            logger.info("Workflow %s: step %d ('%s') %s -- retry %d/%d",
                        auto_id, step_idx, step_auto["name"], status, attempt + 1, retries)
            _run_workflow(auto_id, steps, triggered_by, step_idx, retries, attempt + 1)
        else:
            logger.info("Workflow %s: step %d ('%s') %s -- stopping chain",
                        auto_id, step_idx, step_auto["name"], status)

    trigger_suffix = f":step{step_idx}" if attempt == 0 else f":step{step_idx}:retry{attempt}"
    try:
        job_runner.submit(
            make_process,
            automation_id=step_auto_id,
            trigger=f"workflow:{auto_id}{trigger_suffix}",
            triggered_by=triggered_by,
            on_complete=on_step_complete,
        )
    except RuntimeError as exc:
        logger.warning("Workflow %s: step %d submit failed: %s", auto_id, step_idx, exc)


def _run_parallel_workflow(auto_id: str, steps: list[str], triggered_by: str) -> None:
    """Submit all workflow steps concurrently (fan-out)."""
    for idx, step_auto_id in enumerate(steps):
        step_auto = db.get_automation(step_auto_id)
        if not step_auto:
            logger.warning("Parallel workflow %s: step %d auto '%s' not found", auto_id, idx, step_auto_id)
            continue
        builder = _AUTO_BUILDERS.get(step_auto["type"])
        if not builder:
            logger.warning("Parallel workflow %s: step %d unsupported type '%s'", auto_id, idx, step_auto["type"])
            continue
        config = step_auto["config"]

        def make_process(_run_id: int, _b=builder, _c=config) -> subprocess.Popen | None:
            return _b(_c)

        try:
            job_runner.submit(
                make_process,
                automation_id=step_auto_id,
                trigger=f"workflow:{auto_id}:parallel{idx}",
                triggered_by=triggered_by,
            )
        except RuntimeError as exc:
            logger.warning("Parallel workflow %s: step %d submit failed: %s", auto_id, idx, exc)
