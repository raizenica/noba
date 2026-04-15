# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Cron-like scheduler for automations."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import subprocess
import threading
import time
from datetime import datetime

from .db import db
from .runner import job_runner
from .workflow_engine import _AUTO_BUILDERS, _run_parallel_workflow, _run_workflow

logger = logging.getLogger("noba")


def _match_cron(expr: str, dt: datetime) -> bool:
    """Check if a 5-field cron expression matches a datetime (minute precision).

    Supports: numbers, ``*``, comma lists, ranges (``-``), and steps (``/``).
    Fields: minute hour day-of-month month day-of-week (0=Sun or 7=Sun).
    """
    parts = expr.strip().split()
    if len(parts) != 5:
        return False
    fields = [dt.minute, dt.hour, dt.day, dt.month, dt.isoweekday() % 7]
    limits = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]

    for part, val, (lo, hi) in zip(parts, fields, limits):
        if not _match_field(part, val, lo, hi):
            return False
    return True


def _match_field(field: str, val: int, lo: int, hi: int) -> bool:
    for item in field.split(","):
        step = 1
        if "/" in item:
            item, step_s = item.split("/", 1)
            try:
                step = int(step_s)
            except ValueError:
                return False
            if step < 1:
                return False
        if item == "*":
            if (val - lo) % step == 0:
                return True
        elif "-" in item:
            try:
                a, b = item.split("-", 1)
                a, b = int(a), int(b)
            except ValueError:
                return False
            if a <= val <= b and (val - a) % step == 0:
                return True
        else:
            try:
                if int(item) == val:
                    return True
            except ValueError:
                return False
    return False


class FSTriggerWatcher:
    """Watches directories for changes and triggers automations."""

    def __init__(self) -> None:
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None
        self._watches: dict[str, dict] = {}  # path -> {mtime: float, auto_id: str}

    def start(self) -> None:
        from .yaml_config import read_yaml_settings
        cfg = read_yaml_settings()
        triggers = cfg.get("fsTriggers", [])
        if not triggers:
            return
        for t in triggers:
            path = t.get("path", "")
            auto_id = t.get("automation_id", "")
            if path and auto_id and os.path.exists(path):
                with contextlib.suppress(OSError):
                    self._watches[path] = {"mtime": os.path.getmtime(path), "auto_id": auto_id}
        if self._watches:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="fs-trigger")
            self._thread.start()
            logger.info("FS trigger watcher started for %d paths", len(self._watches))

    def stop(self) -> None:
        self._shutdown.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._shutdown.wait(5):  # Check every 5 seconds
            for path, info in list(self._watches.items()):
                try:
                    current_mtime = os.path.getmtime(path)
                    if current_mtime > info["mtime"]:
                        info["mtime"] = current_mtime
                        self._trigger_automation(info["auto_id"], path)
                except OSError:
                    pass

    def _trigger_automation(self, auto_id: str, path: str) -> None:
        auto = db.get_automation(auto_id)
        if not auto:
            return
        if auto["type"] == "workflow":
            steps = auto["config"].get("steps", [])
            if steps:
                mode = auto["config"].get("mode", "sequential")
                if mode == "parallel":
                    _run_parallel_workflow(auto["id"], steps, f"fs-trigger:{path}")
                else:
                    _run_workflow(auto["id"], steps, f"fs-trigger:{path}")
            return
        builder = _AUTO_BUILDERS.get(auto["type"])
        if not builder:
            return
        config = auto["config"]

        def make_process(_run_id: int):
            return builder(config)

        try:
            job_runner.submit(make_process, automation_id=auto_id,
                              trigger=f"fs-trigger:{path}", triggered_by="fs-watcher")
            logger.info("FS trigger: '%s' changed, triggered '%s'", path, auto["name"])
        except RuntimeError as exc:
            logger.warning("FS trigger submit failed: %s", exc)


class Scheduler:
    """Background thread that checks automations every 60s and triggers matching ones."""

    def __init__(self) -> None:
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._shutdown.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._shutdown.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        # Align to the start of the next minute
        now = time.time()
        wait = 60 - (now % 60)
        if self._shutdown.wait(wait):
            return

        while not self._shutdown.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error("Scheduler tick error: %s", e)
            # Wait until the next minute boundary
            now = time.time()
            wait = 60 - (now % 60)
            if wait < 1:
                wait = 60
            self._shutdown.wait(wait)

    def _tick(self) -> None:
        now = datetime.now()
        # Check maintenance windows (reuse alerts.py logic)
        from .alerts import in_maintenance_window
        from .yaml_config import read_yaml_settings
        if in_maintenance_window(read_yaml_settings):
            logger.info("Maintenance window active, skipping scheduled automations")
            return
        autos = db.list_automations()
        for auto in autos:
            if not auto["enabled"]:
                continue
            schedule = auto.get("schedule")
            if not schedule:
                continue
            if not _match_cron(schedule, now):
                continue
            self._trigger(auto)

        # Every tick (60s), auto-approve expired pending approvals and execute them
        self._process_auto_approvals()

        # Every 15 minutes: run predictive healing evaluation
        if now.minute % 15 == 0:
            try:
                from .healing import get_pipeline
                from .healing.predictive import run_predictive_cycle

                events = run_predictive_cycle()
                if events:
                    pipeline = get_pipeline()
                    for event in events:
                        pipeline.handle_heal_event(event)
                    logger.info("Predictive: fed %d event(s) into pipeline", len(events))
            except Exception as exc:
                logger.error("Predictive cycle failed: %s", exc)

        # Hourly: generate heal suggestions and evaluate trust promotions
        if now.minute == 0:  # once per hour
            try:
                from .healing.auto_discovery import run_auto_discovery
                from .healing.governor import evaluate_promotions
                from .healing.ledger import generate_suggestions
                generate_suggestions(db)
                promotion_suggestions = evaluate_promotions(db)
                for s in promotion_suggestions:
                    db.insert_heal_suggestion(**s)
                if promotion_suggestions:
                    logger.info("Trust governor: %d promotion suggestion(s)", len(promotion_suggestions))
                # Auto-discovery: detect co-failure patterns
                run_auto_discovery(db)
            except Exception as exc:
                logger.error("Heal suggestion generation failed: %s", exc)

            # Hourly: evaluate health score thresholds
            try:
                from .healing import get_pipeline as _get_pipeline
                from .healing.health_triggers import evaluate_health_thresholds
                # Health score categories are cached from the last /api/health-score
                # call. Use the latest cached result if available.
                _cached_hs = getattr(db, '_cached_health_score', None)
                _categories = _cached_hs.get("categories", {}) if isinstance(_cached_hs, dict) else {}
                suggestions, events = evaluate_health_thresholds(_categories) if _categories else ([], [])
                if suggestions:
                    for s in suggestions:
                        db.insert_heal_suggestion(**s)
                    logger.info("Health triggers: %d suggestion(s)", len(suggestions))
                if events:
                    _pipeline = _get_pipeline()
                    for event in events:
                        _pipeline.handle_heal_event(event)
                    logger.info("Health triggers: fed %d event(s) into pipeline", len(events))
            except Exception as exc:
                logger.error("Health score trigger evaluation failed: %s", exc)

    def _process_auto_approvals(self) -> None:
        """Auto-approve any pending approvals past their auto_approve_at time,
        then execute all auto_approved items that have no result yet."""
        count = db.auto_approve_expired()
        if count:
            logger.info("Auto-approved %d expired approval(s)", count)

        # Execute auto_approved items that haven't been executed yet
        try:
            pending_exec = [
                a for a in db.list_approvals(status="auto_approved")
                if not a.get("result")
            ]
        except Exception as exc:
            logger.error("Failed to list auto_approved approvals: %s", exc)
            return

        if not pending_exec:
            return

        import json as _json

        from .remediation import execute_action

        for approval in pending_exec:
            try:
                action_params = approval.get("action_params") or {}
                if isinstance(action_params, str):
                    action_params = _json.loads(action_params)
                result = execute_action(
                    approval["action_type"],
                    action_params,
                    triggered_by="auto_approve",
                )
                db.update_approval_result(approval["id"], _json.dumps(result))
                logger.info(
                    "Executed auto-approved action id=%d type=%s",
                    approval["id"], approval["action_type"],
                )
            except Exception as exc:
                logger.error(
                    "Failed to execute auto-approved action id=%d: %s",
                    approval.get("id"), exc,
                )

    def _trigger(self, auto: dict) -> None:
        """Submit an automation to the job runner."""
        # Workflow: chain steps
        if auto["type"] == "workflow":
            steps = auto["config"].get("steps", [])
            if steps:
                wf_retries = int(auto["config"].get("retries", 0))
                mode = auto["config"].get("mode", "sequential")
                if mode == "parallel":
                    _run_parallel_workflow(auto["id"], steps, "scheduler")
                else:
                    _run_workflow(auto["id"], steps, "scheduler", retries=wf_retries)
                logger.info("Scheduler triggered workflow '%s' (%d steps, %s)", auto["name"], len(steps), mode)
            return

        builder = _AUTO_BUILDERS.get(auto["type"])
        if not builder:
            logger.warning("Scheduler: unknown type %s for %s", auto["type"], auto["id"])
            return

        config = auto["config"]

        def make_process(_run_id: int) -> subprocess.Popen | None:
            return builder(config)

        try:
            run_id = job_runner.submit(
                make_process,
                automation_id=auto["id"],
                trigger=f"schedule:{auto['schedule']}",
                triggered_by="scheduler",
            )
            logger.info("Scheduler triggered '%s' -> run_id=%d", auto["name"], run_id)
        except RuntimeError as exc:
            logger.warning("Scheduler: cannot run '%s': %s", auto["name"], exc)


class RSSFeedWatcher:
    """Polls RSS feeds and triggers automations on new items."""

    def __init__(self) -> None:
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None
        self._feeds: list[dict] = []
        self._seen: dict[str, set[str]] = {}  # feed_url -> set of seen item IDs/links

    def start(self) -> None:
        from .yaml_config import read_yaml_settings
        cfg = read_yaml_settings()
        self._feeds = cfg.get("rssTriggers", [])
        if not self._feeds:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="rss-trigger")
        self._thread.start()
        logger.info("RSS feed watcher started for %d feeds", len(self._feeds))

    def stop(self) -> None:
        self._shutdown.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        import defusedxml.ElementTree as ET
        import httpx
        # Initial scan to populate seen items (don't trigger on first run)
        for feed in self._feeds:
            url = feed.get("url", "")
            if url:
                self._scan_feed(url, ET, httpx, initial=True)
        while not self._shutdown.wait(300):  # Check every 5 minutes
            for feed in self._feeds:
                url = feed.get("url", "")
                auto_id = feed.get("automation_id", "")
                if not url or not auto_id:
                    continue
                new_items = self._scan_feed(url, ET, httpx)
                if new_items:
                    self._trigger_automation(auto_id, f"rss:{url}")

    def _scan_feed(self, url, ET, httpx, initial=False) -> list[str]:  # noqa: N803
        try:
            r = httpx.get(url, timeout=10, follow_redirects=False)
            r.raise_for_status()
            root = ET.fromstring(r.text)
            # Handle both RSS and Atom feeds
            items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
            current_ids: set[str] = set()
            for item in items:
                link = item.findtext("link") or item.findtext("{http://www.w3.org/2005/Atom}id") or ""
                guid = item.findtext("guid") or link
                current_ids.add(guid)
            seen = self._seen.get(url, set())
            new_items = [i for i in current_ids if i not in seen]
            self._seen[url] = current_ids
            if initial:
                return []
            return new_items
        except Exception as e:
            logger.debug("RSS feed scan failed for %s: %s", url, e)
            return []

    def _trigger_automation(self, auto_id: str, trigger_source: str) -> None:
        auto = db.get_automation(auto_id)
        if not auto:
            return
        if auto["type"] == "workflow":
            steps = auto["config"].get("steps", [])
            if steps:
                mode = auto["config"].get("mode", "sequential")
                if mode == "parallel":
                    _run_parallel_workflow(auto["id"], steps, trigger_source)
                else:
                    _run_workflow(auto["id"], steps, trigger_source)
            return
        builder = _AUTO_BUILDERS.get(auto["type"])
        if not builder:
            return
        config = auto["config"]

        def make_process(_run_id: int):
            return builder(config)

        try:
            job_runner.submit(make_process, automation_id=auto_id,
                              trigger=trigger_source, triggered_by="rss-watcher")
            logger.info("RSS trigger: new items in feed, triggered '%s'", auto["name"])
        except RuntimeError as exc:
            logger.warning("RSS trigger submit failed: %s", exc)


def _run_endpoint_check(monitor: dict) -> dict:
    """Execute an endpoint check locally (server-side) or via agent.

    Returns the monitor dict with updated status fields.
    """
    import socket
    import ssl
    import urllib.error
    import urllib.parse
    import urllib.request

    url = monitor["url"]
    method = monitor.get("method", "GET")
    timeout = monitor.get("timeout", 10)
    expected_status = monitor.get("expected_status", 200)
    agent_hostname = monitor.get("agent_hostname")

    # If an agent is assigned, dispatch via agent command
    if agent_hostname:
        return _dispatch_agent_endpoint_check(monitor)

    # Detect self-referential URLs that would deadlock when called from
    # within the same uvicorn process (manual check via API).
    from .config import PORT
    parsed_check = urllib.parse.urlparse(url)
    check_host = (parsed_check.hostname or "").lower()
    check_port = parsed_check.port or (443 if parsed_check.scheme == "https" else 80)
    _self_hosts = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
    try:
        import socket as _sock
        _self_hosts.add(_sock.gethostname().lower())
        _self_hosts.add(_sock.getfqdn().lower())
    except Exception:
        pass
    if check_host in _self_hosts and check_port == PORT:
        logger.warning("Endpoint '%s' targets this NOBA instance — "
                       "skipping to avoid self-referential deadlock", monitor.get("name"))
        db.record_endpoint_check(
            monitor["id"], status="skipped", response_ms=0, status_code=0,
            cert_expiry_days=None,
            error="Self-referential: monitors targeting this NOBA instance "
                  "are skipped to prevent deadlocks. Use an external NOBA "
                  "instance or agent to monitor this server.",
        )
        return {
            "last_status": "skipped",
            "last_response_ms": 0,
            "status_code": 0,
            "cert_expiry_days": None,
            "error": "Self-referential: this monitor targets the same NOBA "
                     "instance. Assign an agent or use an external checker.",
        }

    # Run locally on the server
    result: dict = {}
    start = time.time()

    try:
        req = urllib.request.Request(url, method=method)
        req.add_header("User-Agent", "NOBA-Server/1.0")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.status
            elapsed_ms = int((time.time() - start) * 1000)
            result["status_code"] = status_code
            result["response_ms"] = elapsed_ms
    except urllib.error.HTTPError as e:
        elapsed_ms = int((time.time() - start) * 1000)
        result["status_code"] = e.code
        result["response_ms"] = elapsed_ms
    except urllib.error.URLError as e:
        elapsed_ms = int((time.time() - start) * 1000)
        result["status_code"] = 0
        result["response_ms"] = elapsed_ms
        result["error"] = str(e.reason)
    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        result["status_code"] = 0
        result["response_ms"] = elapsed_ms
        result["error"] = str(e)

    # Determine status
    code = result.get("status_code", 0)
    if code == 0:
        status = "down"
    elif code == expected_status:
        status = "up"
    elif 200 <= code < 400:
        status = "degraded"
    else:
        status = "down"

    # TLS cert check
    cert_expiry_days = None
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https" and code > 0:
        try:
            hostname = parsed.hostname or ""
            port = parsed.port or 443
            ctx = ssl.create_default_context()
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            with ctx.wrap_socket(
                socket.socket(socket.AF_INET, socket.SOCK_STREAM),
                server_hostname=hostname,
            ) as ssock:
                ssock.settimeout(timeout)
                ssock.connect((hostname, port))
                cert = ssock.getpeercert()
            if cert:
                import datetime as _dt
                not_after = cert.get("notAfter", "")
                if not_after:
                    expiry_dt = _dt.datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
                    cert_expiry_days = (expiry_dt - _dt.datetime.utcnow()).days
        except Exception:
            pass

    # Store result
    db.record_endpoint_check(
        monitor["id"],
        status=status,
        response_ms=result.get("response_ms"),
        status_code=result.get("status_code"),
        cert_expiry_days=cert_expiry_days,
        error=result.get("error"),
    )

    # Record into check history for trending/uptime
    db.record_endpoint_check_history(
        monitor["id"],
        status=status,
        response_ms=result.get("response_ms"),
        error=result.get("error"),
    )

    # Record response_ms as a metric for trending
    try:
        now_ts = int(time.time())
        metric_name = f"endpoint_ms:{monitor['name']}"
        if result.get("response_ms") is not None:
            db.insert_metrics([(now_ts, metric_name, float(result["response_ms"]), None)])
    except Exception:
        pass

    return {
        "last_status": status,
        "last_response_ms": result.get("response_ms"),
        "status_code": result.get("status_code"),
        "cert_expiry_days": cert_expiry_days,
        "error": result.get("error"),
    }


def _dispatch_agent_endpoint_check(monitor: dict) -> dict:
    """Send endpoint_check command to an agent and process the result."""
    import uuid

    from .agent_store import (
        _agent_cmd_lock,
        _agent_cmd_ready,
        _agent_cmd_results,
        _agent_commands,
    )
    cmd_id = str(uuid.uuid4())
    hostname = monitor["agent_hostname"]
    cmd = {
        "id": cmd_id,
        "type": "endpoint_check",
        "params": {
            "url": monitor["url"],
            "method": monitor.get("method", "GET"),
            "timeout": monitor.get("timeout", 10),
        },
    }
    with _agent_cmd_lock:
        _agent_commands.setdefault(hostname, []).append(cmd)

    db.record_command(cmd_id, hostname, "endpoint_check", cmd["params"], "scheduler")

    # Wait for result using condition variable (up to timeout + 5s)
    deadline = time.time() + monitor.get("timeout", 10) + 5
    agent_result = None
    with _agent_cmd_ready:
        while agent_result is None:
            rlist = _agent_cmd_results.get(hostname, [])
            for i, r in enumerate(rlist):
                if isinstance(r, dict) and r.get("id") == cmd_id:
                    agent_result = rlist.pop(i)
                    break
            if agent_result is not None:
                break
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            _agent_cmd_ready.wait(timeout=remaining)

    if agent_result is None:
        # Timed out waiting for agent
        db.record_endpoint_check(
            monitor["id"], status="down", response_ms=None,
            error="Agent did not respond in time",
        )
        return {"last_status": "down", "error": "Agent timeout"}

    db.complete_command(cmd_id, agent_result)

    # Interpret agent result
    expected_status = monitor.get("expected_status", 200)
    code = agent_result.get("status_code", 0)
    if agent_result.get("status") == "error" or code == 0:
        status = "down"
    elif code == expected_status:
        status = "up"
    elif 200 <= code < 400:
        status = "degraded"
    else:
        status = "down"

    cert_expiry_days = agent_result.get("cert_expiry_days")

    db.record_endpoint_check(
        monitor["id"],
        status=status,
        response_ms=agent_result.get("response_ms"),
        status_code=code,
        cert_expiry_days=cert_expiry_days,
        error=agent_result.get("error"),
    )

    # Record into check history for trending/uptime
    db.record_endpoint_check_history(
        monitor["id"],
        status=status,
        response_ms=agent_result.get("response_ms"),
        error=agent_result.get("error"),
    )

    # Record metric
    try:
        now_ts = int(time.time())
        metric_name = f"endpoint_ms:{monitor['name']}"
        if agent_result.get("response_ms") is not None:
            db.insert_metrics([(now_ts, metric_name, float(agent_result["response_ms"]), None)])
    except Exception:
        pass

    return {
        "last_status": status,
        "last_response_ms": agent_result.get("response_ms"),
        "status_code": code,
        "cert_expiry_days": cert_expiry_days,
        "error": agent_result.get("error"),
    }


class EndpointChecker:
    """Background thread that runs endpoint checks every 60 seconds."""

    def __init__(self) -> None:
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._shutdown.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="endpoint-checker")
        self._thread.start()
        logger.info("Endpoint checker started")

    def stop(self) -> None:
        self._shutdown.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _loop(self) -> None:
        # Initial delay to let the app start
        if self._shutdown.wait(10):
            return
        while not self._shutdown.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error("Endpoint checker tick error: %s", e)
            self._shutdown.wait(60)

    def _process_monitor(self, monitor: dict) -> None:
        """Check a single endpoint monitor and fire alerts."""
        try:
            result = _run_endpoint_check(monitor)
            # Check for cert expiry alerts
            cert_days = result.get("cert_expiry_days")
            notify_days = monitor.get("notify_cert_days", 14)
            if cert_days is not None and cert_days <= notify_days:
                db.insert_alert_history(
                    f"cert_expiry:{monitor['name']}",
                    "warning" if cert_days > 7 else "critical",
                    f"Certificate for {monitor['name']} ({monitor['url']}) "
                    f"expires in {cert_days} day(s)",
                )
            # Check for endpoint down alerts
            if result.get("last_status") == "down":
                db.insert_alert_history(
                    f"endpoint_down:{monitor['name']}",
                    "critical",
                    f"Endpoint {monitor['name']} ({monitor['url']}) is DOWN"
                    + (f": {result.get('error', '')}" if result.get("error") else ""),
                )
            elif result.get("last_status") == "up":
                # Resolve any existing alert for this endpoint
                db.resolve_alert(f"endpoint_down:{monitor['name']}")
        except Exception as e:
            logger.error("Endpoint check failed for %s: %s", monitor.get("name"), e)

    def _tick(self) -> None:
        due = db.get_due_endpoint_monitors()
        if not due:
            return
        logger.debug("Endpoint checker: %d monitors due", len(due))
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(10, len(due))) as pool:
            list(pool.map(self._process_monitor, due))


class DriftChecker:
    """Background thread that checks config baselines against agents every 5 minutes."""

    def __init__(self) -> None:
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._main_loop = loop
        self._shutdown.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="drift-checker")
        self._thread.start()
        logger.info("Drift checker started")

    def stop(self) -> None:
        self._shutdown.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _loop(self) -> None:
        # Initial delay to let agents connect
        if self._shutdown.wait(30):
            return
        while not self._shutdown.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error("Drift checker tick error: %s", e)
            self._shutdown.wait(300)  # Every 5 minutes

    def _tick(self) -> None:
        baselines = db.list_baselines()
        if not baselines:
            return
        from .agent_store import (
            _agent_cmd_lock,
            _agent_cmd_results,
            _agent_commands,
            _agent_data,
            _agent_data_lock,
            _agent_websockets,
            _agent_ws_lock,
        )
        # Build list of online agents
        now_ts = time.time()
        with _agent_data_lock:
            online_agents = [
                h for h, d in _agent_data.items()
                if (now_ts - d.get("_received", 0)) < 120
            ]
        if not online_agents:
            return
        logger.debug("Drift checker: %d baselines, %d online agents",
                      len(baselines), len(online_agents))
        for baseline in baselines:
            group = baseline.get("agent_group", "__all__")
            targets = online_agents if group == "__all__" else [
                h for h in online_agents if h == group or group in h
            ]
            if not targets:
                continue
            self._check_baseline(baseline, targets,
                                 _agent_cmd_lock, _agent_cmd_results,
                                 _agent_commands, _agent_websockets, _agent_ws_lock)

    def _check_baseline(self, baseline: dict, targets: list[str],
                        cmd_lock, cmd_results, cmd_queue,
                        ws_registry, ws_lock) -> None:
        """Send file_checksum to each target agent and record results."""
        import secrets
        cmd_ids: dict[str, str] = {}  # hostname -> cmd_id
        for hostname in targets:
            cmd_id = secrets.token_hex(8)
            cmd = {
                "id": cmd_id,
                "type": "file_checksum",
                "params": {"path": baseline["path"], "algorithm": "sha256"},
            }
            # Try WebSocket first, fall back to queue
            delivered = False
            with ws_lock:
                ws = ws_registry.get(hostname)
            if ws:
                try:
                    # Use the main loop for thread-safe asyncio dispatch
                    if self._main_loop:
                        future = asyncio.run_coroutine_threadsafe(
                            ws.send_json({
                                "type": "command", "id": cmd_id,
                                "cmd": "file_checksum", "params": cmd["params"],
                            }),
                            self._main_loop
                        )
                        # Wait up to 5s for delivery
                        future.result(timeout=5)
                        delivered = True
                except Exception:
                    pass
            if not delivered:
                with cmd_lock:
                    cmd_queue.setdefault(hostname, []).append(cmd)
            cmd_ids[hostname] = cmd_id

        # Wait for results using condition variable (up to 20s total)
        from .agent_store import _agent_cmd_ready
        deadline = time.time() + 20
        pending = dict(cmd_ids)  # hostname -> cmd_id
        results: dict[str, dict] = {}  # hostname -> result dict
        with _agent_cmd_ready:
            while pending:
                for hostname in list(pending):
                    cid = pending[hostname]
                    rlist = cmd_results.get(hostname, [])
                    for i, r in enumerate(rlist):
                        if isinstance(r, dict) and r.get("id") == cid:
                            results[hostname] = rlist.pop(i)
                            del pending[hostname]
                            break
                if not pending:
                    break
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                _agent_cmd_ready.wait(timeout=remaining)

        # Record results
        expected = baseline["expected_hash"]
        for hostname, result in results.items():
            actual = result.get("checksum", "")
            status = "match" if actual == expected else "drift"
            db.record_drift_check(baseline["id"], hostname, actual, status=status)
            db.complete_command(cmd_ids[hostname], result)
            if status == "drift":
                db.insert_alert_history(
                    f"config_drift:{baseline['path']}:{hostname}",
                    "warning",
                    f"Config drift detected: {baseline['path']} on {hostname} "
                    f"(expected {expected[:16]}..., got {actual[:16]}...)",
                )

        # Record timeout for agents that didn't respond
        for hostname in pending:
            db.record_drift_check(baseline["id"], hostname, None, status="timeout")

    def run_check_now(self) -> None:
        """Run a drift check immediately (callable from API)."""
        try:
            self._tick()
        except Exception as e:
            logger.error("Manual drift check error: %s", e)


# Singletons
scheduler = Scheduler()
fs_watcher = FSTriggerWatcher()
rss_watcher = RSSFeedWatcher()
endpoint_checker = EndpointChecker()
drift_checker = DriftChecker()
