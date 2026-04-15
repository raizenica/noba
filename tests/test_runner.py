# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the multi-job runner."""
import subprocess
import sys
import time

from server.db import db
from server.runner import JobRunner


def _make_runner() -> JobRunner:
    """Create a fresh runner backed by the test DB."""
    return JobRunner(max_concurrent=2)


def _echo_process(run_id: int) -> subprocess.Popen:
    """Spawn a quick process that prints a line and exits 0."""
    return subprocess.Popen(
        [sys.executable, "-c", "print('hello')"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _sleep_process(run_id: int) -> subprocess.Popen:
    """Spawn a long-sleeping process for cancel/timeout tests."""
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _fail_process(run_id: int) -> subprocess.Popen:
    """Spawn a process that exits with code 1."""
    return subprocess.Popen(
        [sys.executable, "-c", "import sys; print('fail'); sys.exit(1)"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _none_process(run_id: int) -> subprocess.Popen | None:
    """Simulates a command that could not be built."""
    return None


class TestJobRunnerSubmit:
    def test_submit_returns_run_id(self):
        runner = _make_runner()
        run_id = runner.submit(_echo_process, trigger="test")
        assert isinstance(run_id, int)
        assert run_id > 0
        # Wait for completion
        time.sleep(0.5)
        assert not runner.is_active(run_id)

    def test_successful_job_records_output(self):
        runner = _make_runner()
        run_id = runner.submit(_echo_process, trigger="test")
        time.sleep(0.5)
        run = db.get_job_run(run_id)
        assert run is not None
        assert run["status"] == "done"
        assert run["exit_code"] == 0
        assert "hello" in (run["output"] or "")

    def test_failed_job_records_exit_code(self):
        runner = _make_runner()
        run_id = runner.submit(_fail_process, trigger="test")
        time.sleep(0.5)
        run = db.get_job_run(run_id)
        assert run is not None
        assert run["status"] == "failed"
        assert run["exit_code"] == 1

    def test_none_process_marks_failed(self):
        runner = _make_runner()
        run_id = runner.submit(_none_process, trigger="test")
        time.sleep(0.5)
        run = db.get_job_run(run_id)
        assert run is not None
        assert run["status"] == "failed"
        assert run["error"] is not None


class TestJobRunnerConcurrency:
    def test_max_concurrent_enforced(self):
        runner = _make_runner()  # max_concurrent=2
        id1 = runner.submit(_sleep_process, trigger="test")
        id2 = runner.submit(_sleep_process, trigger="test")
        time.sleep(0.2)
        assert runner.active_count == 2
        try:
            runner.submit(_sleep_process, trigger="test")
            assert False, "Should have raised RuntimeError"
        except RuntimeError as e:
            assert "Max concurrent" in str(e)
        finally:
            runner.cancel(id1)
            runner.cancel(id2)
            time.sleep(0.5)


class TestJobRunnerCancel:
    def test_cancel_active_job(self):
        runner = _make_runner()
        run_id = runner.submit(_sleep_process, trigger="test")
        time.sleep(0.2)
        assert runner.is_active(run_id)
        assert runner.cancel(run_id)
        time.sleep(1)
        assert not runner.is_active(run_id)
        run = db.get_job_run(run_id)
        assert run is not None
        assert run["status"] == "cancelled"

    def test_cancel_nonexistent_returns_false(self):
        runner = _make_runner()
        assert not runner.cancel(999999)


class TestJobRunnerOnComplete:
    def test_on_complete_called_on_success(self):
        runner = _make_runner()
        results = []

        def callback(run_id, status):
            results.append((run_id, status))

        run_id = runner.submit(_echo_process, trigger="test", on_complete=callback)
        time.sleep(0.5)
        assert len(results) == 1
        assert results[0] == (run_id, "done")

    def test_on_complete_called_on_failure(self):
        runner = _make_runner()
        results = []

        def callback(run_id, status):
            results.append((run_id, status))

        run_id = runner.submit(_fail_process, trigger="test", on_complete=callback)
        time.sleep(0.5)
        assert len(results) == 1
        assert results[0] == (run_id, "failed")


class TestJobRunnerShutdown:
    def test_shutdown_cancels_all(self):
        runner = _make_runner()
        id1 = runner.submit(_sleep_process, trigger="test")
        id2 = runner.submit(_sleep_process, trigger="test")
        time.sleep(0.2)
        runner.shutdown(timeout=5)
        assert runner.active_count == 0
        for rid in (id1, id2):
            run = db.get_job_run(rid)
            assert run is not None
            assert run["status"] in ("cancelled", "failed")
