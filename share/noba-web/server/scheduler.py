"""Noba – Cron-like scheduler for automations."""
from __future__ import annotations

import logging
import subprocess
import threading
import time
from datetime import datetime

from .db import db
from .runner import job_runner

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
        from .app import _AUTO_BUILDERS, _run_workflow

        # Workflow: chain steps
        if auto["type"] == "workflow":
            steps = auto["config"].get("steps", [])
            if steps:
                wf_retries = int(auto["config"].get("retries", 0))
                _run_workflow(auto["id"], steps, "scheduler", retries=wf_retries)
                logger.info("Scheduler triggered workflow '%s' (%d steps)", auto["name"], len(steps))
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


# Singleton
scheduler = Scheduler()
