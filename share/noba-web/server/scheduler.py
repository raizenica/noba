"""Noba – Cron-like scheduler for automations."""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from datetime import datetime

from .db import db
from .runner import job_runner
from .workflow_engine import _AUTO_BUILDERS, _run_workflow, _run_parallel_workflow

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
                try:
                    self._watches[path] = {"mtime": os.path.getmtime(path), "auto_id": auto_id}
                except OSError:
                    pass
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
        from .yaml_config import read_yaml_settings
        from .alerts import in_maintenance_window
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
        import xml.etree.ElementTree as ET
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
            r = httpx.get(url, timeout=10, follow_redirects=True)
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


# Singletons
scheduler = Scheduler()
fs_watcher = FSTriggerWatcher()
rss_watcher = RSSFeedWatcher()
