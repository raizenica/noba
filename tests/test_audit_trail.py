# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for extended audit trail fields in heal_ledger."""
from __future__ import annotations

import sqlite3
import threading

import pytest


@pytest.fixture()
def audit_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lock = threading.Lock()
    # Create heal_ledger with all columns
    conn.executescript("""
        CREATE TABLE heal_ledger (
            id INTEGER PRIMARY KEY,
            correlation_key TEXT,
            rule_id TEXT,
            condition TEXT,
            target TEXT,
            action_type TEXT,
            action_params TEXT,
            escalation_step INTEGER,
            action_success INTEGER,
            verified INTEGER,
            duration_s REAL,
            metrics_before TEXT,
            metrics_after TEXT,
            trust_level TEXT,
            source TEXT,
            approval_id INTEGER,
            created_at INTEGER,
            risk_level TEXT,
            snapshot_id INTEGER,
            rollback_status TEXT,
            dependency_root TEXT,
            suppressed_by TEXT,
            maintenance_window_id INTEGER,
            instance_id TEXT
        );
    """)
    return conn, lock


class TestExtendedAuditFields:
    def test_insert_with_risk_level(self, audit_db):
        from server.db.healing import insert_heal_outcome
        conn, lock = audit_db
        rid = insert_heal_outcome(
            conn, lock,
            correlation_key="test:cpu", rule_id="r1", condition="cpu>90",
            target="host1", action_type="service_restart",
            action_params="{}", escalation_step=0,
            action_success=True, verified=True, duration_s=1.5,
            trust_level="execute", source="alert",
            risk_level="low",
        )
        row = conn.execute("SELECT risk_level FROM heal_ledger WHERE id=?", (rid,)).fetchone()
        assert row["risk_level"] == "low"

    def test_insert_with_rollback_status(self, audit_db):
        from server.db.healing import insert_heal_outcome
        conn, lock = audit_db
        rid = insert_heal_outcome(
            conn, lock,
            correlation_key="test:mem", rule_id="r2", condition="mem>85",
            target="host1", action_type="scale_container",
            action_params="{}", escalation_step=0,
            action_success=True, verified=False, duration_s=2.0,
            trust_level="execute", source="alert",
            rollback_status="rolled_back", snapshot_id=42,
        )
        row = conn.execute("SELECT rollback_status, snapshot_id FROM heal_ledger WHERE id=?", (rid,)).fetchone()
        assert row["rollback_status"] == "rolled_back"
        assert row["snapshot_id"] == 42

    def test_insert_with_dependency_root(self, audit_db):
        from server.db.healing import insert_heal_outcome
        conn, lock = audit_db
        rid = insert_heal_outcome(
            conn, lock,
            correlation_key="test:disk", rule_id="r3", condition="disk>90",
            target="plex", action_type="restart_container",
            action_params="{}", escalation_step=0,
            action_success=None, verified=None, duration_s=0,
            trust_level="notify", source="alert",
            dependency_root="truenas", suppressed_by="truenas",
        )
        row = conn.execute("SELECT dependency_root, suppressed_by FROM heal_ledger WHERE id=?", (rid,)).fetchone()
        assert row["dependency_root"] == "truenas"
        assert row["suppressed_by"] == "truenas"

    def test_insert_without_extended_fields(self, audit_db):
        """Existing code that doesn't pass new fields should still work."""
        from server.db.healing import insert_heal_outcome
        conn, lock = audit_db
        rid = insert_heal_outcome(
            conn, lock,
            correlation_key="test:x", rule_id="r4", condition="x>1",
            target="svc", action_type="restart_service",
            action_params="{}", escalation_step=0,
            action_success=True, verified=True, duration_s=0.5,
            trust_level="execute", source="alert",
        )
        row = conn.execute("SELECT risk_level, snapshot_id FROM heal_ledger WHERE id=?", (rid,)).fetchone()
        assert row["risk_level"] is None
        assert row["snapshot_id"] is None
