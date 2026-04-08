# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Task queue abstraction (Celery or thread fallback).

When NOBA_CELERY_BROKER is set and celery is installed, long-running jobs
(backups, cloud sync) are dispatched to Celery workers. Otherwise, the
existing thread-based JobRunner handles everything.

Usage:
    from .tasks import task_queue
    if task_queue.available:
        task_queue.submit_async(automation_id, config)
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("noba")

CELERY_BROKER = os.environ.get("NOBA_CELERY_BROKER", "")

_celery_app = None


def _init_celery():
    """Initialize Celery app if broker is configured and celery is installed."""
    global _celery_app
    if not CELERY_BROKER:
        return
    try:
        from celery import Celery
        _celery_app = Celery(
            "noba",
            broker=CELERY_BROKER,
            backend=os.environ.get("NOBA_CELERY_BACKEND", ""),
        )
        _celery_app.conf.update(
            task_serializer="json",
            result_serializer="json",
            accept_content=["json"],
            timezone="UTC",
            enable_utc=True,
            task_track_started=True,
            task_time_limit=3600,
            task_soft_time_limit=3300,
            worker_max_tasks_per_child=100,
            worker_prefetch_multiplier=1,
        )
        logger.info("Celery task queue initialized: %s", CELERY_BROKER)
    except ImportError:
        logger.info("Celery not installed — using thread-based job runner")
        _celery_app = None
    except Exception as e:
        logger.warning("Celery init failed: %s — using thread-based job runner", e)
        _celery_app = None


# Initialize on module load
_init_celery()


# ── Celery tasks (only defined if celery is available) ────────────────────────

if _celery_app:
    @_celery_app.task(name="noba.run_script", bind=True, max_retries=3)
    def _celery_run_script(self, script_key: str, args: str = "") -> dict:
        """Run a noba script via Celery worker."""
        import shlex
        import subprocess

        from .config import SCRIPT_DIR, SCRIPT_MAP
        sfile = os.path.join(SCRIPT_DIR, SCRIPT_MAP.get(script_key, ""))
        if not os.path.isfile(sfile):
            return {"status": "failed", "error": f"Script not found: {script_key}"}
        cmd = [sfile, "--verbose"]
        if args:
            cmd += shlex.split(args)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, cwd=SCRIPT_DIR)
            return {
                "status": "done" if r.returncode == 0 else "failed",
                "exit_code": r.returncode,
                "output": r.stdout[-65536:] if r.stdout else "",
                "error": r.stderr[-4096:] if r.stderr else "",
            }
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "error": "Script timed out after 3600s"}
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    @_celery_app.task(name="noba.run_command", bind=True, max_retries=1)
    def _celery_run_command(self, command: str) -> dict:
        """Run an arbitrary command via Celery worker."""
        import subprocess
        try:
            r = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=3600)
            return {
                "status": "done" if r.returncode == 0 else "failed",
                "exit_code": r.returncode,
                "output": r.stdout[-65536:],
            }
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "error": "Command timed out"}
        except Exception as e:
            return {"status": "failed", "error": str(e)}


# ── Public interface ──────────────────────────────────────────────────────────

class TaskQueue:
    """Unified task queue interface."""

    @property
    def available(self) -> bool:
        """Whether Celery is available for async task dispatch."""
        return _celery_app is not None

    @property
    def broker(self) -> str:
        return CELERY_BROKER

    def submit_script(self, script_key: str, args: str = "") -> str | None:
        """Submit a script to run asynchronously via Celery.

        Returns the Celery task ID, or None if Celery is not available.
        """
        if not self.available:
            return None
        try:
            result = _celery_run_script.delay(script_key, args)
            logger.info("Celery task submitted: %s (script=%s)", result.id, script_key)
            return result.id
        except Exception as e:
            logger.error("Celery submit failed: %s", e)
            return None

    def submit_command(self, command: str) -> str | None:
        """Submit a command to run asynchronously via Celery."""
        if not self.available:
            return None
        try:
            result = _celery_run_command.delay(command)
            return result.id
        except Exception as e:
            logger.error("Celery submit failed: %s", e)
            return None

    def get_result(self, task_id: str) -> dict | None:
        """Check the result of a Celery task."""
        if not self.available:
            return None
        try:
            from celery.result import AsyncResult
            result = AsyncResult(task_id, app=_celery_app)
            if result.ready():
                return result.get(timeout=1)
            return {"status": result.state.lower()}
        except Exception as e:
            logger.debug("Celery result check failed: %s", e)
            return None


# Singleton
task_queue = TaskQueue()
