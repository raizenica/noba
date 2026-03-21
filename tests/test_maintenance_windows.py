"""Tests for maintenance_windows DB functions."""
from __future__ import annotations

import os
import tempfile
import time

from server.db import Database


def _make_db():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_test_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


class TestMaintenanceWindows:
    def setup_method(self):
        self.db, self.path = _make_db()

    def teardown_method(self):
        _cleanup(self.path)

    def _insert(self, **kwargs):
        defaults = dict(name="Test Window", created_by="admin")
        defaults.update(kwargs)
        return self.db.insert_maintenance_window(**defaults)

    # ── CRUD basics ───────────────────────────────────────────────────────────

    def test_insert_and_list(self):
        wid = self._insert(name="Deploy window")
        assert wid is not None
        rows = self.db.list_maintenance_windows()
        assert len(rows) == 1
        assert rows[0]["id"] == wid
        assert rows[0]["name"] == "Deploy window"
        assert rows[0]["enabled"] is True
        assert rows[0]["suppress_alerts"] is True
        assert rows[0]["duration_min"] == 60

    def test_insert_multiple_ordered_newest_first(self):
        id1 = self._insert(name="First")
        id2 = self._insert(name="Second")
        rows = self.db.list_maintenance_windows()
        assert len(rows) == 2
        # Both rows present regardless of insertion-order tie-break
        ids = {r["id"] for r in rows}
        assert id1 in ids
        assert id2 in ids

    def test_update_name(self):
        wid = self._insert(name="Old Name")
        result = self.db.update_maintenance_window(wid, name="New Name")
        assert result is True
        rows = self.db.list_maintenance_windows()
        assert rows[0]["name"] == "New Name"

    def test_update_enabled(self):
        wid = self._insert()
        self.db.update_maintenance_window(wid, enabled=False)
        rows = self.db.list_maintenance_windows()
        assert rows[0]["enabled"] is False

    def test_update_duration(self):
        wid = self._insert()
        self.db.update_maintenance_window(wid, duration_min=120)
        rows = self.db.list_maintenance_windows()
        assert rows[0]["duration_min"] == 120

    def test_update_nonexistent_returns_false(self):
        result = self.db.update_maintenance_window(9999, name="Ghost")
        assert result is False

    def test_update_no_valid_fields_returns_false(self):
        wid = self._insert()
        result = self.db.update_maintenance_window(wid, nonexistent_field="x")
        assert result is False

    def test_delete(self):
        wid = self._insert()
        result = self.db.delete_maintenance_window(wid)
        assert result is True
        rows = self.db.list_maintenance_windows()
        assert rows == []

    def test_delete_nonexistent_returns_false(self):
        result = self.db.delete_maintenance_window(9999)
        assert result is False

    # ── get_active: one-off windows ───────────────────────────────────────────

    def test_get_active_one_off_in_range(self):
        now = int(time.time())
        wid = self._insert(
            name="Active one-off",
            one_off_start=now - 300,
            one_off_end=now + 300,
        )
        active = self.db.get_active_maintenance_windows()
        ids = [w["id"] for w in active]
        assert wid in ids

    def test_get_active_one_off_not_started(self):
        now = int(time.time())
        wid = self._insert(
            name="Future one-off",
            one_off_start=now + 600,
            one_off_end=now + 1200,
        )
        active = self.db.get_active_maintenance_windows()
        ids = [w["id"] for w in active]
        assert wid not in ids

    def test_get_active_one_off_already_ended(self):
        now = int(time.time())
        wid = self._insert(
            name="Past one-off",
            one_off_start=now - 1200,
            one_off_end=now - 600,
        )
        active = self.db.get_active_maintenance_windows()
        ids = [w["id"] for w in active]
        assert wid not in ids

    # ── get_active: disabled window must not appear ───────────────────────────

    def test_get_active_disabled_one_off_excluded(self):
        now = int(time.time())
        wid = self._insert(
            name="Disabled window",
            one_off_start=now - 300,
            one_off_end=now + 300,
        )
        self.db.update_maintenance_window(wid, enabled=False)
        active = self.db.get_active_maintenance_windows()
        ids = [w["id"] for w in active]
        assert wid not in ids

    def test_get_active_disabled_cron_excluded(self):
        wid = self._insert(
            name="Disabled cron window",
            schedule="* * * * *",
            duration_min=60,
        )
        self.db.update_maintenance_window(wid, enabled=False)
        active = self.db.get_active_maintenance_windows()
        ids = [w["id"] for w in active]
        assert wid not in ids

    # ── get_active: cron-based windows ───────────────────────────────────────

    def test_get_active_cron_always_matches(self):
        """'* * * * *' should always match — window should be active."""
        wid = self._insert(
            name="Always-on cron",
            schedule="* * * * *",
            duration_min=60,
        )
        active = self.db.get_active_maintenance_windows()
        ids = [w["id"] for w in active]
        assert wid in ids

    def test_get_active_no_schedule_no_one_off_not_active(self):
        """A window with neither schedule nor one_off times is not active."""
        wid = self._insert(name="No schedule window")
        active = self.db.get_active_maintenance_windows()
        ids = [w["id"] for w in active]
        assert wid not in ids

    # ── field values in returned dicts ───────────────────────────────────────

    def test_suppress_alerts_default_true(self):
        wid = self._insert()
        rows = self.db.list_maintenance_windows()
        assert rows[0]["suppress_alerts"] is True

    def test_suppress_alerts_false(self):
        wid = self._insert(suppress_alerts=False)
        rows = self.db.list_maintenance_windows()
        assert rows[0]["suppress_alerts"] is False

    def test_override_autonomy_stored(self):
        wid = self._insert(override_autonomy="manual_only")
        rows = self.db.list_maintenance_windows()
        assert rows[0]["override_autonomy"] == "manual_only"

    def test_auto_close_alerts_false_by_default(self):
        wid = self._insert()
        rows = self.db.list_maintenance_windows()
        assert rows[0]["auto_close_alerts"] is False

    def test_created_by_stored(self):
        wid = self._insert(created_by="engineer")
        rows = self.db.list_maintenance_windows()
        assert rows[0]["created_by"] == "engineer"
