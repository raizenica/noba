"""Noba – Multi-job runner with concurrency control."""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from typing import Callable

from .config import JOB_MAX_OUTPUT, JOB_TIMEOUT, MAX_CONCURRENT_JOBS
from .db import db

logger = logging.getLogger("noba")


class JobRunner:
    """Manages concurrent background jobs with DB-backed state."""

    def __init__(self, max_concurrent: int = MAX_CONCURRENT_JOBS) -> None:
        self._max = max_concurrent
        self._lock = threading.Lock()
        # run_id -> {"thread": Thread, "process": Popen | None, "cancelled": bool}
        self._active: dict[int, dict] = {}

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def submit(
        self,
        run_fn: Callable[[int], subprocess.Popen | None],
        *,
        automation_id: str | None = None,
        trigger: str = "manual",
        triggered_by: str = "system",
        on_complete: Callable[[int, str], None] | None = None,
    ) -> int:
        """Queue and start a job.  Returns the run_id.

        ``run_fn`` receives the run_id and must return a ``Popen`` handle
        (or ``None`` if the command could not be built).  The runner
        captures its output, enforces timeouts and records the result.

        ``on_complete``, if given, is called with ``(run_id, status)``
        after the job finishes (regardless of outcome).
        """
        with self._lock:
            if len(self._active) >= self._max:
                raise RuntimeError(
                    f"Max concurrent jobs ({self._max}) reached"
                )

        run_id = db.insert_job_run(automation_id, trigger, triggered_by)
        if run_id is None:
            raise RuntimeError("Failed to create job_run record")

        entry: dict = {"thread": None, "process": None, "cancelled": False}
        with self._lock:
            self._active[run_id] = entry

        t = threading.Thread(
            target=self._run,
            args=(run_id, run_fn, entry, on_complete),
            daemon=True,
            name=f"job-{run_id}",
        )
        entry["thread"] = t
        t.start()
        return run_id

    # ── Cancel ─────────────────────────────────────────────────────────────────
    def cancel(self, run_id: int) -> bool:
        """Request cancellation.  Returns True if the job was still active."""
        with self._lock:
            entry = self._active.get(run_id)
            if not entry:
                return False
            entry["cancelled"] = True
            proc: subprocess.Popen | None = entry.get("process")

        if proc and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        return True

    # ── Query ──────────────────────────────────────────────────────────────────
    def get_active_ids(self) -> list[int]:
        with self._lock:
            return list(self._active.keys())

    def is_active(self, run_id: int) -> bool:
        with self._lock:
            return run_id in self._active

    # ── Shutdown ───────────────────────────────────────────────────────────────
    def shutdown(self, timeout: float = 10) -> None:
        """Cancel all active jobs and wait for threads to finish."""
        with self._lock:
            ids = list(self._active.keys())
        for rid in ids:
            self.cancel(rid)
        deadline = time.monotonic() + timeout
        for rid in ids:
            with self._lock:
                entry = self._active.get(rid)
            if entry and entry["thread"]:
                remaining = max(0.1, deadline - time.monotonic())
                entry["thread"].join(timeout=remaining)

    # ── Internal runner ────────────────────────────────────────────────────────
    def _run(
        self,
        run_id: int,
        run_fn: Callable[[int], subprocess.Popen | None],
        entry: dict,
        on_complete: Callable[[int, str], None] | None = None,
    ) -> None:
        status = "failed"
        output_buf: list[str] = []
        exit_code: int | None = None
        error: str | None = None
        proc: subprocess.Popen | None = None

        try:
            proc = run_fn(run_id)
            if proc is None:
                status = "failed"
                error = "Command could not be constructed"
                return

            entry["process"] = proc

            # Stream stdout/stderr capped at JOB_MAX_OUTPUT
            # Collapse \r-based progress lines (rsync --info=progress2, etc.)
            # to keep only the last update per burst.
            total = 0
            for line in iter(proc.stdout.readline, b""):
                if entry["cancelled"]:
                    break
                decoded = line.decode("utf-8", errors="replace")
                # Collapse carriage-return progress: keep only the last non-empty segment
                if "\r" in decoded:
                    parts = decoded.split("\r")
                    # Walk backwards to find the last segment with content
                    for i in range(len(parts) - 1, -1, -1):
                        if parts[i].strip():
                            decoded = parts[i] if parts[i].endswith("\n") else parts[i] + "\n"
                            break
                    else:
                        decoded = "\n"
                if total + len(decoded) <= JOB_MAX_OUTPUT:
                    output_buf.append(decoded)
                    total += len(decoded)
                elif total < JOB_MAX_OUTPUT:
                    remaining = JOB_MAX_OUTPUT - total
                    output_buf.append(decoded[:remaining])
                    output_buf.append("\n[output truncated]\n")
                    break

            # Wait for completion with timeout
            try:
                proc.wait(timeout=JOB_TIMEOUT)
            except subprocess.TimeoutExpired:
                self._kill_process(proc)
                status = "timeout"
                error = f"Timed out after {JOB_TIMEOUT}s"
                output_buf.append(f"\n[ERROR] Job timed out after {JOB_TIMEOUT}s\n")
                return

            if entry["cancelled"]:
                self._kill_process(proc)
                status = "cancelled"
                return

            exit_code = proc.returncode
            status = "done" if exit_code == 0 else "failed"
            if exit_code != 0:
                error = f"Exit code {exit_code}"

        except Exception as exc:
            logger.exception("Job %d runner error: %s", run_id, exc)
            error = str(exc)[:512]
        finally:
            output = "".join(output_buf) if output_buf else None
            db.update_job_run(run_id, status, output=output,
                              exit_code=exit_code, error=error)
            with self._lock:
                self._active.pop(run_id, None)
            if on_complete:
                try:
                    on_complete(run_id, status)
                except Exception as cb_exc:
                    logger.error("on_complete callback error for job %d: %s", run_id, cb_exc)

    @staticmethod
    def _kill_process(proc: subprocess.Popen) -> None:
        """SIGTERM → wait → SIGKILL a process group."""
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL)
                proc.wait(timeout=3)
        except (ProcessLookupError, PermissionError):
            pass


# Singleton
job_runner = JobRunner()
