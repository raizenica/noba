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
    elif atype == "agent_command":
        if not config.get("hostname"):
            raise HTTPException(400, "agent_command requires 'hostname' in config")
        if not config.get("command"):
            raise HTTPException(400, "agent_command requires 'command' in config")


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


class _HttpResult:
    """Popen-compatible wrapper around an httpx response for job_runner."""

    def __init__(self, stdout_bytes: bytes, returncode: int) -> None:
        self.stdout = __import__("io").BytesIO(stdout_bytes)
        self.returncode = returncode
        self.pid = 0

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def poll(self) -> int:
        return self.returncode

    def kill(self) -> None:
        pass


def _do_http_request(
    url: str,
    method: str = "GET",
    headers: dict | None = None,
    body: str | bytes | None = None,
    auth: tuple[str, str] | None = None,
    timeout: float = 30,
) -> _HttpResult:
    """Perform an HTTP request via httpx and return a Popen-compatible result."""
    import httpx
    import time as _time

    t0 = _time.monotonic()
    try:
        r = httpx.request(
            method,
            url,
            headers=headers,
            content=body,
            auth=auth,
            timeout=timeout,
            follow_redirects=True,
        )
        elapsed = _time.monotonic() - t0
        out = r.text + f"\n--- HTTP {r.status_code} ({elapsed:.3f}s) ---"
        return _HttpResult(out.encode(), 0 if r.status_code < 400 else 1)
    except Exception as exc:
        elapsed = _time.monotonic() - t0
        out = f"Request failed: {exc}\n--- HTTP 0 ({elapsed:.3f}s) ---"
        return _HttpResult(out.encode(), 1)


def _build_auto_webhook_process(config: dict) -> _HttpResult | None:
    url = config.get("url", "")
    method = config.get("method", "POST").upper()
    headers = dict(config.get("headers", {}))
    body = config.get("body")
    content = None
    if body:
        if isinstance(body, (dict, list)):
            headers["Content-Type"] = "application/json"
            content = json.dumps(body).encode()
        elif isinstance(body, str):
            content = body.encode()
    return _do_http_request(url, method, headers=headers, body=content)


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


def _build_auto_http_process(config: dict) -> _HttpResult | None:
    url = config.get("url", "")
    method = config.get("method", "GET").upper()
    headers = dict(config.get("headers", {}))
    auth_type = config.get("auth_type", "")
    auth = None
    if auth_type == "bearer":
        headers["Authorization"] = f"Bearer {config.get('auth_token', '')}"
    elif auth_type == "basic":
        auth = (config.get("auth_user", ""), config.get("auth_pass", ""))
    body = config.get("body")
    content = None
    if body:
        if isinstance(body, (dict, list)):
            headers["Content-Type"] = "application/json"
            content = json.dumps(body).encode()
        elif isinstance(body, str):
            content = body.encode()
    return _do_http_request(url, method, headers=headers, body=content, auth=auth)


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


def _build_auto_agent_command_process(config: dict) -> subprocess.Popen | None:
    """Execute an agent command via the agent store and return a process for status tracking.

    Config keys: hostname (str), command (str), params (dict), timeout (int).
    Supports hostname ``__all__`` for broadcast to all online agents.
    """
    from .agent_store import queue_agent_command_and_wait

    hostname = config.get("hostname", "")
    cmd_type = config.get("command", "")
    params = config.get("params", {})
    timeout = int(config.get("timeout", 30))

    if not hostname or not cmd_type:
        return None

    result = queue_agent_command_and_wait(
        hostname, cmd_type, params, timeout=timeout, queued_by="workflow",
    )

    if result is None:
        logger.warning("agent_command %s on %s: timeout (no result)", cmd_type, hostname)
        return subprocess.Popen(
            ["bash", "-c", "echo 'agent_command timed out'; exit 1"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
        )

    # For __all__ broadcasts, check if any host failed
    if isinstance(result, dict) and result.get("__all__"):
        results = result.get("results", {})
        failures = [h for h, r in results.items() if r is None or r.get("status") == "error"]
        if failures:
            msg = f"agent_command {cmd_type} failed on: {', '.join(failures)}"
            return subprocess.Popen(
                ["bash", "-c", f"echo '{msg}'; exit 1"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
            )
        msg = f"agent_command {cmd_type} succeeded on {len(results)} agents"
        return subprocess.Popen(
            ["bash", "-c", f"echo '{msg}'"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
        )

    # Single-host result
    status = result.get("status", "error")
    if status == "error":
        err = result.get("error", "unknown error")
        return subprocess.Popen(
            ["bash", "-c", f"echo 'agent_command error: {err}'; exit 1"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
        )

    return subprocess.Popen(
        ["bash", "-c", f"echo 'agent_command {cmd_type} on {hostname}: {status}'"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
    )


# ── Builder registry ──────────────────────────────────────────────────────────

_AUTO_BUILDERS = {
    "script": _build_auto_script_process, "webhook": _build_auto_webhook_process,
    "service": _build_auto_service_process, "delay": _build_auto_delay_process,
    "http": _build_auto_http_process, "notify": _build_auto_notify_process,
    "condition": _build_auto_condition_process,
    "agent_command": _build_auto_agent_command_process,
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
