# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for db/core.py — the foundation of all NOBA data access.

Covers: connection management, lock patterns, schema migrations, CRUD wrappers,
transaction safety, edge cases, settings storage, and metric insertion.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import time

import pytest

from server.db import Database


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_db() -> tuple[Database, str]:
    """Create a fresh temp-file-backed Database for isolation."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_core_test_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path: str) -> None:
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Connection Management
# ═══════════════════════════════════════════════════════════════════════════════

class TestConnectionManagement:
    """Initialization, WAL mode, dual connections (read/write)."""

    def test_database_creates_file(self):
        db, path = _make_db()
        try:
            assert os.path.exists(path)
        finally:
            _cleanup(path)

    def test_wal_mode_enabled(self):
        db, path = _make_db()
        try:
            mode = db._get_conn().execute("PRAGMA journal_mode;").fetchone()[0]
            assert mode.lower() == "wal"
        finally:
            _cleanup(path)

    def test_busy_timeout_set(self):
        db, path = _make_db()
        try:
            timeout = db._get_conn().execute("PRAGMA busy_timeout;").fetchone()[0]
            assert timeout == 5000
        finally:
            _cleanup(path)

    def test_synchronous_normal(self):
        db, path = _make_db()
        try:
            val = db._get_conn().execute("PRAGMA synchronous;").fetchone()[0]
            # 1 = NORMAL
            assert val == 1
        finally:
            _cleanup(path)

    def test_dual_connections_are_separate(self):
        db, path = _make_db()
        try:
            write_conn = db._get_conn()
            read_conn = db._get_read_conn()
            assert write_conn is not read_conn
        finally:
            _cleanup(path)

    def test_write_conn_is_persistent(self):
        db, path = _make_db()
        try:
            c1 = db._get_conn()
            c2 = db._get_conn()
            assert c1 is c2
        finally:
            _cleanup(path)

    def test_read_conn_is_persistent(self):
        db, path = _make_db()
        try:
            c1 = db._get_read_conn()
            c2 = db._get_read_conn()
            assert c1 is c2
        finally:
            _cleanup(path)

    def test_read_conn_query_only(self):
        """Read connection should refuse writes (PRAGMA query_only=ON)."""
        db, path = _make_db()
        try:
            rconn = db._get_read_conn()
            with pytest.raises(sqlite3.OperationalError):
                rconn.execute(
                    "INSERT INTO metrics (timestamp, metric, value) VALUES (1, 'x', 1.0)"
                )
        finally:
            _cleanup(path)

    def test_read_conn_autocommit(self):
        """Read connection uses autocommit (isolation_level=None)."""
        db, path = _make_db()
        try:
            rconn = db._get_read_conn()
            assert rconn.isolation_level is None
        finally:
            _cleanup(path)

    def test_init_creates_parent_directory(self):
        tmpdir = tempfile.mkdtemp(prefix="noba_core_test_")
        subpath = os.path.join(tmpdir, "sub", "deep", "test.db")
        try:
            Database(path=subpath)
            assert os.path.isdir(os.path.dirname(subpath))
        finally:
            _cleanup(subpath)
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_init_noop(self):
        """db.init() is a no-op alias kept for compat; should not raise."""
        db, path = _make_db()
        try:
            db.init()  # Should succeed silently
        finally:
            _cleanup(path)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Lock Patterns
# ═══════════════════════════════════════════════════════════════════════════════

class TestLockPatterns:
    """Verify read lock, write lock, and concurrent access."""

    def test_write_lock_exists(self):
        db, path = _make_db()
        try:
            # RLock allowed for reentrant locking during migrations
            assert isinstance(db._lock, (type(threading.Lock()), type(threading.RLock())))
        finally:
            _cleanup(path)

    def test_read_lock_exists(self):
        db, path = _make_db()
        try:
            assert isinstance(db._read_lock, type(threading.Lock()))
        finally:
            _cleanup(path)

    def test_execute_write_holds_lock(self):
        """execute_write should acquire the write lock around the operation."""
        db, path = _make_db()
        try:
            lock_count_during_fn = []

            def fn(conn):
                # Check lock count - should be > 0 if lock is held
                # For RLock, owner will be current thread; for Lock, acquire would succeed
                lock_count_during_fn.append(db._lock._is_owned())
                return None

            db.execute_write(fn)
            # With RLock, _is_owned() returns True if current thread owns it
            assert lock_count_during_fn == [True]
        finally:
            _cleanup(path)

    def test_execute_read_no_write_lock(self):
        """execute_read should NOT acquire the write lock."""
        db, path = _make_db()
        try:
            lock_was_free = []

            def fn(conn):
                acquired = db._lock.acquire(blocking=False)
                if acquired:
                    db._lock.release()
                    lock_was_free.append(True)
                else:
                    lock_was_free.append(False)
                return None

            db.execute_read(fn)
            assert lock_was_free == [True]
        finally:
            _cleanup(path)

    def test_concurrent_reads_do_not_block(self):
        """Two concurrent reads should both complete without blocking."""
        db, path = _make_db()
        try:
            db.insert_metrics([("cpu", 50.0, None)])
            results = []
            barrier = threading.Barrier(2, timeout=5)

            def reader():
                def fn(conn):
                    barrier.wait()
                    return conn.execute(
                        "SELECT COUNT(*) FROM metrics"
                    ).fetchone()[0]
                results.append(db.execute_read(fn))

            t1 = threading.Thread(target=reader)
            t2 = threading.Thread(target=reader)
            t1.start()
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)
            assert len(results) == 2
            assert all(r >= 1 for r in results)
        finally:
            _cleanup(path)

    def test_concurrent_writes_serialized(self):
        """Concurrent writes should be serialized by the write lock."""
        db, path = _make_db()
        try:
            order = []
            barrier = threading.Barrier(2, timeout=5)

            def writer(label):
                def fn(conn):
                    order.append(f"{label}_start")
                    conn.execute(
                        "INSERT INTO metrics (timestamp, metric, value) "
                        "VALUES (?, ?, ?)",
                        (int(time.time()), f"test_{label}", 1.0),
                    )
                    order.append(f"{label}_end")
                    return None
                barrier.wait()
                db.execute_write(fn)

            t1 = threading.Thread(target=writer, args=("A",))
            t2 = threading.Thread(target=writer, args=("B",))
            t1.start()
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)
            # Writes are serialized: one must fully finish before the other starts
            assert len(order) == 4
            # Either A_start,A_end,B_start,B_end or B_start,B_end,A_start,A_end
            assert (
                (order[0].endswith("_start") and order[1].endswith("_end")
                 and order[0][0] == order[1][0])
            )
        finally:
            _cleanup(path)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Schema Migrations
# ═══════════════════════════════════════════════════════════════════════════════

class TestSchemaMigrations:
    """Table creation, migration execution, version tracking."""

    EXPECTED_TABLES = [
        "metrics", "audit", "automations", "job_runs", "alert_history",
        "api_keys", "notifications", "user_dashboards", "incidents",
        "metrics_1m", "metrics_1h", "agent_registry", "agent_command_history",
        "endpoint_monitors", "custom_dashboards", "status_components",
        "status_incidents", "status_updates", "incident_messages",
        "service_dependencies", "user_preferences", "security_findings",
        "security_scores", "config_baselines", "drift_checks",
        "network_devices", "webhook_endpoints", "backup_verifications",
        "backup_321_status", "approval_queue", "maintenance_windows",
        "action_audit", "endpoint_check_history", "playbook_templates",
        "tokens", "heal_ledger", "trust_state", "heal_suggestions",
        "integration_instances", "integration_groups", "capability_manifests",
        "dependency_graph", "heal_maintenance_windows", "heal_snapshots",
    ]

    def test_all_tables_created(self):
        db, path = _make_db()
        try:
            conn = db._get_conn()
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            tables = {r[0] for r in rows}
            for tbl in self.EXPECTED_TABLES:
                assert tbl in tables, f"Missing table: {tbl}"
        finally:
            _cleanup(path)

    def test_metrics_index_exists(self):
        db, path = _make_db()
        try:
            conn = db._get_conn()
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_metric_time'"
            ).fetchall()
            assert len(rows) == 1
        finally:
            _cleanup(path)

    def test_migration_approval_queue_workflow_context(self):
        """The workflow_context column should be added to approval_queue."""
        db, path = _make_db()
        try:
            conn = db._get_conn()
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(approval_queue)"
            ).fetchall()]
            assert "workflow_context" in cols
        finally:
            _cleanup(path)

    def test_migration_heal_ledger_extended_columns(self):
        """Extended heal_ledger columns should exist after migration."""
        db, path = _make_db()
        try:
            conn = db._get_conn()
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(heal_ledger)"
            ).fetchall()]
            for col in ("risk_level", "snapshot_id", "rollback_status",
                        "dependency_root", "suppressed_by",
                        "maintenance_window_id", "instance_id"):
                assert col in cols, f"Missing heal_ledger column: {col}"
        finally:
            _cleanup(path)

    def test_migration_integration_instances_tls_columns(self):
        """verify_ssl and ca_bundle columns on integration_instances."""
        db, path = _make_db()
        try:
            conn = db._get_conn()
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(integration_instances)"
            ).fetchall()]
            assert "verify_ssl" in cols
            assert "ca_bundle" in cols
        finally:
            _cleanup(path)

    def test_migration_status_incidents_assigned_to(self):
        db, path = _make_db()
        try:
            conn = db._get_conn()
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(status_incidents)"
            ).fetchall()]
            assert "assigned_to" in cols
        finally:
            _cleanup(path)

    def test_schema_idempotent(self):
        """Creating a second Database on the same file should not fail."""
        db1, path = _make_db()
        try:
            db2 = Database(path=path)
            # Both should work
            db1.insert_metrics([("cpu", 1.0, None)])
            db2.insert_metrics([("cpu", 2.0, None)])
        finally:
            _cleanup(path)

    def test_playbook_templates_seeded(self):
        """Default playbook templates should be seeded on init."""
        db, path = _make_db()
        try:
            templates = db.list_playbook_templates()
            assert len(templates) > 0
        finally:
            _cleanup(path)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. CRUD Operations (main get/set/list/delete wrappers)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCRUDOperations:
    """Test the delegation wrappers on the Database class."""

    # ── Automations ──────────────────────────────────────────────────────────

    def test_automation_crud(self):
        db, path = _make_db()
        try:
            ok = db.insert_automation("auto-1", "Test Auto", "script",
                                      {"cmd": "echo hi"})
            assert ok is True

            auto = db.get_automation("auto-1")
            assert auto is not None
            assert auto["name"] == "Test Auto"

            autos = db.list_automations()
            assert any(a["id"] == "auto-1" for a in autos)

            db.update_automation("auto-1", name="Renamed")
            auto = db.get_automation("auto-1")
            assert auto["name"] == "Renamed"

            ok = db.delete_automation("auto-1")
            assert ok is True
            assert db.get_automation("auto-1") is None
        finally:
            _cleanup(path)

    # ── Notifications ────────────────────────────────────────────────────────

    def test_notification_crud(self):
        db, path = _make_db()
        try:
            db.insert_notification("info", "Test Title", "Body", username="admin")
            notes = db.get_notifications(username="admin")
            assert len(notes) >= 1
            assert notes[0]["title"] == "Test Title"

            count = db.get_unread_count("admin")
            assert count >= 1

            db.mark_notification_read(notes[0]["id"], "admin")
            count = db.get_unread_count("admin")
            assert count == 0
        finally:
            _cleanup(path)

    def test_mark_all_notifications_read(self):
        db, path = _make_db()
        try:
            db.insert_notification("info", "N1", "B1", username="bob")
            db.insert_notification("warn", "N2", "B2", username="bob")
            assert db.get_unread_count("bob") == 2
            db.mark_all_notifications_read("bob")
            assert db.get_unread_count("bob") == 0
        finally:
            _cleanup(path)

    # ── Alert History ────────────────────────────────────────────────────────

    def test_alert_history_crud(self):
        db, path = _make_db()
        try:
            db.insert_alert_history("rule-cpu", "warning", "CPU high")
            rows = db.get_alert_history(limit=10)
            assert len(rows) == 1
            assert rows[0]["rule_id"] == "rule-cpu"
            assert rows[0]["severity"] == "warning"

            db.resolve_alert("rule-cpu")
            rows = db.get_alert_history(limit=10)
            assert rows[0].get("resolved_at") is not None and rows[0]["resolved_at"] > 0
        finally:
            _cleanup(path)

    # ── Incidents ────────────────────────────────────────────────────────────

    def test_incident_crud(self):
        db, path = _make_db()
        try:
            iid = db.insert_incident("critical", "sensor", "Disk full")
            assert iid is not None

            incidents = db.get_incidents(limit=10, hours=1)
            assert any(i["id"] == iid for i in incidents)

            ok = db.resolve_incident(iid)
            assert ok is True
        finally:
            _cleanup(path)

    # ── Agent Registry ───────────────────────────────────────────────────────

    def test_agent_crud(self):
        db, path = _make_db()
        try:
            db.upsert_agent("node01", "10.0.0.1", "linux", "amd64", "1.0")
            agents = db.get_all_agents()
            assert any(a["hostname"] == "node01" for a in agents)

            db.update_agent_config("node01", {"interval": 30})
            agents = db.get_all_agents()
            a = next(a for a in agents if a["hostname"] == "node01")
            cfg = a["config"] if isinstance(a["config"], dict) else json.loads(a["config"])
            assert cfg.get("interval") == 30

            db.delete_agent("node01")
            agents = db.get_all_agents()
            assert not any(a["hostname"] == "node01" for a in agents)
        finally:
            _cleanup(path)

    # ── User Preferences ─────────────────────────────────────────────────────

    def test_user_preferences_crud(self):
        db, path = _make_db()
        try:
            assert db.get_user_preferences("alice") is None

            ok = db.save_user_preferences("alice", {"theme": "dracula"})
            assert ok is True

            prefs = db.get_user_preferences("alice")
            assert prefs is not None
            p = prefs["preferences"] if isinstance(prefs["preferences"], dict) else json.loads(prefs["preferences"])
            assert p["theme"] == "dracula"

            ok = db.delete_user_preferences("alice")
            assert ok is True
            assert db.get_user_preferences("alice") is None
        finally:
            _cleanup(path)

    # ── User Dashboards ──────────────────────────────────────────────────────

    def test_user_dashboard_crud(self):
        db, path = _make_db()
        try:
            assert db.get_user_dashboard("bob") is None

            db.save_user_dashboard("bob", card_order=["cpu", "mem"])
            dash = db.get_user_dashboard("bob")
            assert dash is not None
        finally:
            _cleanup(path)

    # ── API Keys ─────────────────────────────────────────────────────────────

    def test_api_key_crud(self):
        db, path = _make_db()
        try:
            db.insert_api_key("k1", "MyKey", "hash123", "viewer")
            keys = db.list_api_keys()
            assert any(k["id"] == "k1" for k in keys)

            found = db.get_api_key("hash123")
            assert found is not None
            assert found["name"] == "MyKey"

            ok = db.delete_api_key("k1")
            assert ok is True
            assert db.list_api_keys() == [] or not any(k["id"] == "k1" for k in db.list_api_keys())
        finally:
            _cleanup(path)

    # ── Job Runs ─────────────────────────────────────────────────────────────

    def test_job_run_lifecycle(self):
        db, path = _make_db()
        try:
            db.insert_automation("auto-j", "Job Auto", "script", {})
            run_id = db.insert_job_run("auto-j", "manual", "admin")
            assert run_id is not None

            run = db.get_job_run(run_id)
            assert run is not None
            assert run["status"] == "running"

            db.update_job_run(run_id, "completed", output="done", exit_code=0)
            run = db.get_job_run(run_id)
            assert run["status"] == "completed"
            assert run["exit_code"] == 0

            runs = db.get_job_runs(automation_id="auto-j")
            assert len(runs) >= 1
        finally:
            _cleanup(path)

    # ── Command History ──────────────────────────────────────────────────────

    def test_command_history(self):
        db, path = _make_db()
        try:
            db.record_command("cmd-1", "node01", "shell", {"cmd": "uptime"}, "admin")
            history = db.get_command_history(hostname="node01")
            assert len(history) == 1
            assert history[0]["cmd_type"] == "shell"

            db.complete_command("cmd-1", {"status": "ok", "output": "up 5 days"})
            history = db.get_command_history(hostname="node01")
            assert history[0]["status"] == "ok"
        finally:
            _cleanup(path)

    # ── Endpoint Monitors ────────────────────────────────────────────────────

    def test_endpoint_monitor_crud(self):
        db, path = _make_db()
        try:
            mid = db.create_endpoint_monitor("Google", "https://google.com")
            assert mid is not None

            mon = db.get_endpoint_monitor(mid)
            assert mon is not None
            assert mon["name"] == "Google"

            monitors = db.get_endpoint_monitors()
            assert any(m["id"] == mid for m in monitors)

            ok = db.update_endpoint_monitor(mid, name="Google Updated")
            assert ok is True

            ok = db.delete_endpoint_monitor(mid)
            assert ok is True
        finally:
            _cleanup(path)

    # ── Service Dependencies ─────────────────────────────────────────────────

    def test_service_dependency_crud(self):
        db, path = _make_db()
        try:
            dep_id = db.create_dependency("web", "db")
            assert dep_id is not None

            deps = db.list_dependencies()
            assert len(deps) >= 1

            ok = db.delete_dependency(dep_id)
            assert ok is True
        finally:
            _cleanup(path)

    # ── Webhooks ─────────────────────────────────────────────────────────────

    def test_webhook_crud(self):
        db, path = _make_db()
        try:
            wid = db.create_webhook("Deploy Hook", "hook-abc", "secret123")
            assert wid is not None

            wh = db.get_webhook_by_hook_id("hook-abc")
            assert wh is not None
            assert wh["name"] == "Deploy Hook"

            hooks = db.list_webhooks()
            assert len(hooks) >= 1

            ok = db.delete_webhook(wid)
            assert ok is True
        finally:
            _cleanup(path)

    # ── Trust State ──────────────────────────────────────────────────────────

    def test_trust_state_crud(self):
        db, path = _make_db()
        try:
            db.upsert_trust_state("rule-1", "notify", "execute")
            ts = db.get_trust_state("rule-1")
            assert ts is not None
            assert ts["current_level"] == "notify"

            states = db.list_trust_states()
            assert len(states) >= 1

            # Update
            db.upsert_trust_state("rule-1", "suggest", "execute")
            ts = db.get_trust_state("rule-1")
            assert ts["current_level"] == "suggest"
        finally:
            _cleanup(path)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Transaction Safety
# ═══════════════════════════════════════════════════════════════════════════════

class TestTransactionSafety:
    """Commit/rollback and nested operations via transaction()."""

    def test_transaction_commits_on_success(self):
        db, path = _make_db()
        try:
            def multi_insert(conn):
                conn.execute(
                    "INSERT INTO metrics (timestamp, metric, value) VALUES (?,?,?)",
                    (1, "tx_a", 10.0),
                )
                conn.execute(
                    "INSERT INTO metrics (timestamp, metric, value) VALUES (?,?,?)",
                    (2, "tx_b", 20.0),
                )

            db.transaction(multi_insert)

            rows = db.execute_read(
                lambda c: c.execute("SELECT COUNT(*) FROM metrics WHERE metric LIKE 'tx_%'").fetchone()[0]
            )
            assert rows == 2
        finally:
            _cleanup(path)

    def test_transaction_rolls_back_on_error(self):
        db, path = _make_db()
        try:
            def bad_insert(conn):
                conn.execute(
                    "INSERT INTO metrics (timestamp, metric, value) VALUES (?,?,?)",
                    (1, "rollback_test", 99.0),
                )
                raise ValueError("Intentional failure")

            with pytest.raises(ValueError, match="Intentional"):
                db.transaction(bad_insert)

            count = db.execute_read(
                lambda c: c.execute(
                    "SELECT COUNT(*) FROM metrics WHERE metric='rollback_test'"
                ).fetchone()[0]
            )
            assert count == 0
        finally:
            _cleanup(path)

    def test_execute_write_auto_commits(self):
        db, path = _make_db()
        try:
            db.execute_write(
                lambda c: c.execute(
                    "INSERT INTO metrics (timestamp, metric, value) VALUES (?,?,?)",
                    (1, "ew_test", 5.0),
                )
            )
            count = db.execute_read(
                lambda c: c.execute(
                    "SELECT COUNT(*) FROM metrics WHERE metric='ew_test'"
                ).fetchone()[0]
            )
            assert count == 1
        finally:
            _cleanup(path)

    def test_execute_write_returns_result(self):
        db, path = _make_db()
        try:
            result = db.execute_write(lambda c: 42)
            assert result == 42
        finally:
            _cleanup(path)

    def test_transaction_returns_result(self):
        db, path = _make_db()
        try:
            result = db.transaction(lambda c: "hello")
            assert result == "hello"
        finally:
            _cleanup(path)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Database edge cases: concurrent writes, VACUUM, WAL checkpoint."""

    def test_auto_vacuum_incremental(self):
        db, path = _make_db()
        try:
            val = db._get_conn().execute("PRAGMA auto_vacuum;").fetchone()[0]
            # 2 = INCREMENTAL
            assert val == 2
        finally:
            _cleanup(path)

    def test_wal_checkpoint(self):
        """wal_checkpoint should succeed without error."""
        db, path = _make_db()
        try:
            db.insert_metrics([("cpu", 50.0, None)])
            db.wal_checkpoint()  # Should not raise
        finally:
            _cleanup(path)

    def test_many_concurrent_writes(self):
        """Stress test: 20 threads each inserting a row."""
        db, path = _make_db()
        try:
            errors = []

            def writer(i):
                try:
                    db.execute_write(
                        lambda c: c.execute(
                            "INSERT INTO metrics (timestamp, metric, value) "
                            "VALUES (?,?,?)",
                            (int(time.time()), f"stress_{i}", float(i)),
                        )
                    )
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            assert errors == []
            count = db.execute_read(
                lambda c: c.execute(
                    "SELECT COUNT(*) FROM metrics WHERE metric LIKE 'stress_%'"
                ).fetchone()[0]
            )
            assert count == 20
        finally:
            _cleanup(path)

    def test_empty_table_queries(self):
        """Querying empty tables should return empty results, not crash."""
        db, path = _make_db()
        try:
            assert db.get_audit() == []
            assert db.list_automations() == []
            assert db.get_alert_history() == []
            assert db.list_api_keys() == []
            assert db.get_notifications() == []
            assert db.get_incidents() == []
            assert db.get_all_agents() == []
            assert db.list_dependencies() == []
            assert db.list_webhooks() == []
            assert db.list_trust_states() == []
        finally:
            _cleanup(path)

    def test_get_nonexistent_returns_none(self):
        """Fetching by ID that does not exist should return None."""
        db, path = _make_db()
        try:
            assert db.get_automation("nonexistent") is None
            assert db.get_job_run(99999) is None
            assert db.get_user_dashboard("nobody") is None
            assert db.get_user_preferences("nobody") is None
            assert db.get_endpoint_monitor(99999) is None
            assert db.get_trust_state("no-rule") is None
            assert db.get_webhook_by_hook_id("no-hook") is None
            assert db.get_approval(99999) is None
        finally:
            _cleanup(path)

    def test_delete_nonexistent_returns_false_or_noop(self):
        """Deleting something that doesn't exist should not crash."""
        db, path = _make_db()
        try:
            # These should return False or just not raise
            assert db.delete_automation("nope") is False
            assert db.delete_dependency(99999) is False
            assert db.delete_webhook(99999) is False
            assert db.delete_endpoint_monitor(99999) is False
        finally:
            _cleanup(path)

    def test_duplicate_automation_insert(self):
        """Inserting the same automation ID twice should not crash.

        INSERT OR IGNORE silently skips the duplicate, so return is still True.
        The original row must remain unchanged.
        """
        db, path = _make_db()
        try:
            db.insert_automation("dup-1", "First", "script", {})
            ok = db.insert_automation("dup-1", "Second", "script", {})
            assert ok is True  # INSERT OR IGNORE returns True (no error)
            auto = db.get_automation("dup-1")
            assert auto["name"] == "First"  # Original preserved
        finally:
            _cleanup(path)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Settings Storage (yaml_config)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSettingsStorage:
    """read_yaml_settings and write_yaml_settings."""

    def test_read_yaml_settings_returns_defaults(self):
        from server.yaml_config import read_yaml_settings
        settings = read_yaml_settings()
        assert isinstance(settings, dict)
        # Should have default keys
        assert "monitoredServices" in settings
        assert "wanTestIp" in settings

    def test_write_and_read_yaml_settings(self):
        from server.yaml_config import read_yaml_settings, write_yaml_settings
        original = read_yaml_settings()

        # Write a change
        updated = dict(original)
        updated["wanTestIp"] = "1.1.1.1"
        ok = write_yaml_settings(updated)
        assert ok is True

        # Read back
        result = read_yaml_settings()
        assert result["wanTestIp"] == "1.1.1.1"

        # Restore
        write_yaml_settings(original)

    def test_read_yaml_settings_caching(self):
        """Second call within TTL should return cached result."""
        from server.yaml_config import read_yaml_settings
        s1 = read_yaml_settings()
        s2 = read_yaml_settings()
        # Both should succeed and return same content
        assert s1.keys() == s2.keys()


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Metric Insertion
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetricInsertion:
    """insert_metrics, get_history, time-range filtering."""

    def test_insert_and_query_metrics(self):
        db, path = _make_db()
        try:
            db.insert_metrics([("cpu_percent", 72.5, None)])
            rows = db.get_history("cpu_percent", range_hours=1, resolution=1)
            assert len(rows) >= 1
            assert rows[0]["value"] == 72.5
        finally:
            _cleanup(path)

    def test_insert_multiple_metrics(self):
        db, path = _make_db()
        try:
            db.insert_metrics([
                ("cpu_percent", 10.0, None),
                ("mem_percent", 55.0, None),
                ("disk_percent", 80.0, None),
            ])
            cpu = db.get_history("cpu_percent", range_hours=1, resolution=1)
            mem = db.get_history("mem_percent", range_hours=1, resolution=1)
            disk = db.get_history("disk_percent", range_hours=1, resolution=1)
            assert len(cpu) >= 1
            assert len(mem) >= 1
            assert len(disk) >= 1
        finally:
            _cleanup(path)

    def test_empty_history_returns_empty_list(self):
        db, path = _make_db()
        try:
            rows = db.get_history("nonexistent_metric", range_hours=1)
            assert rows == []
        finally:
            _cleanup(path)

    def test_time_range_filtering(self):
        """Metrics outside the range_hours window should be excluded.

        Uses raw=True to force querying the metrics table directly
        (range_hours > 1 normally routes to metrics_1m rollup table).
        """
        db, path = _make_db()
        try:
            now = int(time.time())
            old_ts = now - 7200  # 2 hours ago

            with db._lock:
                conn = db._get_conn()
                conn.execute(
                    "INSERT INTO metrics (timestamp, metric, value) VALUES (?,?,?)",
                    (old_ts, "old_metric", 1.0),
                )
                conn.execute(
                    "INSERT INTO metrics (timestamp, metric, value) VALUES (?,?,?)",
                    (now, "old_metric", 2.0),
                )
                conn.commit()

            # 1-hour window should only get the recent one
            rows = db.get_history("old_metric", range_hours=1, resolution=1)
            assert len(rows) == 1
            assert rows[0]["value"] == 2.0

            # 3-hour window (raw=True to query metrics table) should get both
            rows = db.get_history("old_metric", range_hours=3, resolution=1, raw=True)
            assert len(rows) == 2
        finally:
            _cleanup(path)

    def test_aggregation_by_resolution(self):
        """Values within the same resolution bucket should be averaged."""
        db, path = _make_db()
        try:
            now = int(time.time())
            with db._lock:
                conn = db._get_conn()
                conn.execute(
                    "INSERT INTO metrics (timestamp, metric, value) VALUES (?,?,?)",
                    (now, "agg_test", 30.0),
                )
                conn.execute(
                    "INSERT INTO metrics (timestamp, metric, value) VALUES (?,?,?)",
                    (now, "agg_test", 70.0),
                )
                conn.commit()

            rows = db.get_history("agg_test", range_hours=1, resolution=3600)
            assert len(rows) == 1
            assert rows[0]["value"] == 50.0  # AVG(30, 70)
        finally:
            _cleanup(path)

    def test_metrics_with_tags(self):
        db, path = _make_db()
        try:
            db.insert_metrics([("tagged_metric", 42.0, "host=node01")])
            rows = db.get_history("tagged_metric", range_hours=1, resolution=1)
            assert len(rows) >= 1
        finally:
            _cleanup(path)

    def test_trend_returns_dict(self):
        db, path = _make_db()
        try:
            db.insert_metrics([("trend_test", 50.0, None)])
            result = db.get_trend("trend_test", range_hours=1, projection_hours=1)
            assert isinstance(result, dict)
        finally:
            _cleanup(path)

    def test_prune_history(self):
        """prune_history should not raise on an empty or populated DB."""
        db, path = _make_db()
        try:
            db.prune_history()  # Empty — should not crash
            db.insert_metrics([("prune_test", 1.0, None)])
            db.prune_history()  # With data — should not crash
        finally:
            _cleanup(path)

    # ── Audit integration (uses same delegation pattern) ─────────────────────

    def test_audit_log_and_query(self):
        db, path = _make_db()
        try:
            db.audit_log("login", "admin", "success", "127.0.0.1")
            rows = db.get_audit(limit=10)
            assert len(rows) == 1
            assert rows[0]["username"] == "admin"
            assert rows[0]["action"] == "login"
        finally:
            _cleanup(path)

    def test_audit_filters(self):
        db, path = _make_db()
        try:
            db.audit_log("login", "admin", "ok", "127.0.0.1")
            db.audit_log("settings", "bob", "changed theme", "10.0.0.1")

            rows = db.get_audit(username_filter="bob")
            assert all(r["username"] == "bob" for r in rows)

            rows = db.get_audit(action_filter="login")
            assert all(r["action"] == "login" for r in rows)
        finally:
            _cleanup(path)
