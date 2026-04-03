# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the agent_command_history database layer."""
from __future__ import annotations

import os
import tempfile
import time

from server.db import Database


def _make_db():
    """Create a fresh temp DB for each test."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_test_cmdh_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


class TestRecordCommand:
    def test_record_and_retrieve(self):
        db, path = _make_db()
        try:
            db.record_command("cmd1", "host-a", "ping", {}, "admin")
            rows = db.get_command_history()
            assert len(rows) == 1
            assert rows[0]["id"] == "cmd1"
            assert rows[0]["hostname"] == "host-a"
            assert rows[0]["cmd_type"] == "ping"
            assert rows[0]["queued_by"] == "admin"
            assert rows[0]["status"] == "queued"
            assert rows[0]["result"] is None
            assert rows[0]["finished_at"] is None
        finally:
            _cleanup(path)

    def test_record_with_params(self):
        db, path = _make_db()
        try:
            db.record_command("cmd2", "host-b", "exec", {"command": "df -h"}, "operator")
            rows = db.get_command_history()
            assert rows[0]["params"] == {"command": "df -h"}
        finally:
            _cleanup(path)

    def test_duplicate_id_ignored(self):
        db, path = _make_db()
        try:
            db.record_command("dup1", "host-a", "ping", {}, "admin")
            db.record_command("dup1", "host-a", "exec", {}, "admin")
            rows = db.get_command_history()
            assert len(rows) == 1
            # Should keep original (ping), not the duplicate (exec)
            assert rows[0]["cmd_type"] == "ping"
        finally:
            _cleanup(path)


class TestCompleteCommand:
    def test_complete_ok(self):
        db, path = _make_db()
        try:
            db.record_command("cmd-ok", "host-a", "ping", {}, "admin")
            db.complete_command("cmd-ok", {"status": "ok", "pong": 123})
            rows = db.get_command_history()
            assert rows[0]["status"] == "ok"
            assert rows[0]["result"]["pong"] == 123
            assert rows[0]["finished_at"] is not None
        finally:
            _cleanup(path)

    def test_complete_error(self):
        db, path = _make_db()
        try:
            db.record_command("cmd-err", "host-a", "exec", {"command": "bad"}, "admin")
            db.complete_command("cmd-err", {"status": "error", "error": "timeout"})
            rows = db.get_command_history()
            assert rows[0]["status"] == "error"
            assert rows[0]["result"]["error"] == "timeout"
        finally:
            _cleanup(path)

    def test_complete_nonexistent_is_noop(self):
        db, path = _make_db()
        try:
            # Should not raise
            db.complete_command("ghost", {"status": "ok"})
            rows = db.get_command_history()
            assert len(rows) == 0
        finally:
            _cleanup(path)


class TestGetCommandHistory:
    def test_filter_by_hostname(self):
        db, path = _make_db()
        try:
            db.record_command("c1", "alpha", "ping", {}, "admin")
            db.record_command("c2", "beta", "ping", {}, "admin")
            db.record_command("c3", "alpha", "exec", {}, "admin")
            rows = db.get_command_history(hostname="alpha")
            assert len(rows) == 2
            assert all(r["hostname"] == "alpha" for r in rows)
        finally:
            _cleanup(path)

    def test_limit(self):
        db, path = _make_db()
        try:
            for i in range(10):
                db.record_command(f"c{i}", "host", "ping", {}, "admin")
            rows = db.get_command_history(limit=3)
            assert len(rows) == 3
        finally:
            _cleanup(path)

    def test_ordering_most_recent_first(self):
        db, path = _make_db()
        try:
            # Insert with explicit timestamps to ensure ordering
            now = int(time.time())
            with db._lock:
                conn = db._get_conn()
                conn.execute(
                    "INSERT INTO agent_command_history "
                    "(id, hostname, cmd_type, params, queued_by, queued_at, status) "
                    "VALUES (?,?,?,?,?,?,?)",
                    ("old", "host", "ping", "{}", "admin", now - 100, "ok"),
                )
                conn.execute(
                    "INSERT INTO agent_command_history "
                    "(id, hostname, cmd_type, params, queued_by, queued_at, status) "
                    "VALUES (?,?,?,?,?,?,?)",
                    ("new", "host", "exec", "{}", "admin", now, "queued"),
                )
                conn.commit()
            rows = db.get_command_history()
            assert rows[0]["id"] == "new"
            assert rows[1]["id"] == "old"
        finally:
            _cleanup(path)

    def test_empty_history(self):
        db, path = _make_db()
        try:
            rows = db.get_command_history()
            assert rows == []
        finally:
            _cleanup(path)
