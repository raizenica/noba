"""Tests for the database module: metrics, audit, history, trends."""
import os
import tempfile
import time

from server.db import Database


def _make_db():
    """Create a fresh in-memory-style temp DB for each test."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_test_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


class TestMetrics:
    def test_insert_and_query(self):
        db, path = _make_db()
        try:
            db.insert_metrics([("cpu_percent", 55.0, None)])
            rows = db.get_history("cpu_percent", range_hours=1, resolution=1)
            assert len(rows) >= 1
            assert rows[0]["value"] == 55.0
        finally:
            _cleanup(path)

    def test_empty_history(self):
        db, path = _make_db()
        try:
            rows = db.get_history("nonexistent", range_hours=1)
            assert rows == []
        finally:
            _cleanup(path)

    def test_aggregation(self):
        db, path = _make_db()
        try:
            now = int(time.time())
            # Insert multiple values in same time slot
            with db._lock:
                conn = db._get_conn()
                conn.execute(
                    "INSERT INTO metrics (timestamp, metric, value, tags) VALUES (?,?,?,?)",
                    (now, "cpu_percent", 40.0, None),
                )
                conn.execute(
                    "INSERT INTO metrics (timestamp, metric, value, tags) VALUES (?,?,?,?)",
                    (now, "cpu_percent", 60.0, None),
                )
                conn.commit()
            rows = db.get_history("cpu_percent", range_hours=1, resolution=3600)
            assert len(rows) == 1
            assert rows[0]["value"] == 50.0  # AVG(40, 60)
        finally:
            _cleanup(path)


class TestAudit:
    def test_audit_log_and_retrieve(self):
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
            db.audit_log("login", "admin", "success", "127.0.0.1")
            db.audit_log("logout", "bob", "", "127.0.0.1")

            # Filter by username
            rows = db.get_audit(username_filter="admin")
            assert len(rows) == 1
            assert rows[0]["username"] == "admin"

            # Filter by action
            rows = db.get_audit(action_filter="logout")
            assert len(rows) == 1
            assert rows[0]["username"] == "bob"
        finally:
            _cleanup(path)

    def test_audit_detail_truncation(self):
        db, path = _make_db()
        try:
            long_detail = "x" * 1000
            db.audit_log("test", "admin", long_detail)
            rows = db.get_audit(limit=1)
            assert len(rows[0]["details"]) <= 513  # 512 + ellipsis
        finally:
            _cleanup(path)


class TestAnomaly:
    def test_anomaly_detection(self):
        db, path = _make_db()
        try:
            now = int(time.time())
            # Insert enough points for anomaly detection
            with db._lock:
                conn = db._get_conn()
                for i in range(20):
                    val = 50.0 if i != 10 else 200.0  # spike at point 10
                    conn.execute(
                        "INSERT INTO metrics (timestamp, metric, value, tags) VALUES (?,?,?,?)",
                        (now - (20 - i) * 60, "cpu_percent", val, None),
                    )
                conn.commit()
            rows = db.get_history("cpu_percent", range_hours=1, resolution=60, anomaly=True)
            assert len(rows) >= 4  # need at least 4 for anomaly
            # At least one point should have anomaly fields
            has_bands = any("upper_band" in r for r in rows)
            assert has_bands
        finally:
            _cleanup(path)


class TestTrend:
    def test_insufficient_data(self):
        db, path = _make_db()
        try:
            result = db.get_trend("cpu_percent")
            assert "error" in result
        finally:
            _cleanup(path)

    def test_trend_with_data(self):
        db, path = _make_db()
        try:
            now = int(time.time())
            with db._lock:
                conn = db._get_conn()
                for i in range(50):
                    conn.execute(
                        "INSERT INTO metrics (timestamp, metric, value, tags) VALUES (?,?,?,?)",
                        (now - (50 - i) * 300, "disk_percent", 50.0 + i * 0.5, None),
                    )
                conn.commit()
            result = db.get_trend("disk_percent", range_hours=24)
            assert "slope" in result
            assert result["slope"] > 0  # upward trend
            assert "r_squared" in result
            assert "trend" in result
            assert "projection" in result
        finally:
            _cleanup(path)


class TestPruning:
    def test_prune_history(self):
        db, path = _make_db()
        try:
            old_ts = int(time.time()) - 999 * 86400  # way in the past
            with db._lock:
                conn = db._get_conn()
                conn.execute(
                    "INSERT INTO metrics (timestamp, metric, value, tags) VALUES (?,?,?,?)",
                    (old_ts, "cpu_percent", 50.0, None),
                )
                conn.commit()
            db.prune_history()
            rows = db.get_history("cpu_percent", range_hours=999 * 24)
            assert len(rows) == 0
        finally:
            _cleanup(path)


class TestAutomations:
    def test_insert_and_list(self):
        db, path = _make_db()
        try:
            ok = db.insert_automation("a1", "Test Auto", "script", {"command": "echo hi"})
            assert ok
            autos = db.list_automations()
            assert len(autos) == 1
            assert autos[0]["name"] == "Test Auto"
            assert autos[0]["type"] == "script"
            assert autos[0]["config"]["command"] == "echo hi"
            assert autos[0]["enabled"] is True
        finally:
            _cleanup(path)

    def test_get_automation(self):
        db, path = _make_db()
        try:
            db.insert_automation("a2", "Hook", "webhook", {"url": "http://x.com"})
            auto = db.get_automation("a2")
            assert auto is not None
            assert auto["name"] == "Hook"
            assert db.get_automation("nonexistent") is None
        finally:
            _cleanup(path)

    def test_update_automation(self):
        db, path = _make_db()
        try:
            db.insert_automation("a3", "Old", "script", {"command": "ls"})
            ok = db.update_automation("a3", name="New", enabled=False)
            assert ok
            auto = db.get_automation("a3")
            assert auto["name"] == "New"
            assert auto["enabled"] is False
        finally:
            _cleanup(path)

    def test_delete_automation(self):
        db, path = _make_db()
        try:
            db.insert_automation("a4", "Del", "service", {"service": "sshd"})
            assert db.delete_automation("a4")
            assert db.get_automation("a4") is None
            assert not db.delete_automation("a4")
        finally:
            _cleanup(path)

    def test_list_type_filter(self):
        db, path = _make_db()
        try:
            db.insert_automation("s1", "Script1", "script", {})
            db.insert_automation("w1", "Webhook1", "webhook", {"url": "http://x"})
            assert len(db.list_automations(type_filter="script")) == 1
            assert len(db.list_automations(type_filter="webhook")) == 1
            assert len(db.list_automations()) == 2
        finally:
            _cleanup(path)

    def test_duplicate_id_ignored(self):
        db, path = _make_db()
        try:
            db.insert_automation("dup", "First", "script", {})
            db.insert_automation("dup", "Second", "webhook", {"url": "http://x"})
            auto = db.get_automation("dup")
            assert auto["name"] == "First"
        finally:
            _cleanup(path)


class TestJobRunsTriggerFilter:
    def test_trigger_prefix_filter(self):
        db, path = _make_db()
        try:
            db.insert_job_run("a1", "workflow:wf1:step0", "user1")
            db.insert_job_run("a2", "workflow:wf1:step1", "user1")
            db.insert_job_run("a3", "schedule:0 3 * * *", "scheduler")
            db.insert_job_run("a4", "workflow:wf2:step0", "user2")

            # Filter by workflow wf1
            runs = db.get_job_runs(trigger_prefix="workflow:wf1")
            assert len(runs) == 2
            triggers = [r["trigger"] for r in runs]
            assert all("workflow:wf1" in t for t in triggers)

            # Filter by schedule
            runs = db.get_job_runs(trigger_prefix="schedule:")
            assert len(runs) == 1
            assert runs[0]["trigger"] == "schedule:0 3 * * *"

            # No match
            runs = db.get_job_runs(trigger_prefix="alert:")
            assert len(runs) == 0
        finally:
            _cleanup(path)

    def test_trigger_prefix_with_status(self):
        db, path = _make_db()
        try:
            run_id = db.insert_job_run("a1", "workflow:wf1:step0", "user1")
            db.update_job_run(run_id, "done", exit_code=0)
            db.insert_job_run("a2", "workflow:wf1:step1", "user1")

            runs = db.get_job_runs(trigger_prefix="workflow:wf1", status="done")
            assert len(runs) == 1
            assert runs[0]["status"] == "done"
        finally:
            _cleanup(path)
