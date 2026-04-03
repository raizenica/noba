# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba -- Database migration framework.

Provides schema version tracking, migrations with up/down functions,
and automatic migration application on startup.

Usage:
    from server.db.migrations import run_migrations, db
    run_migrations(db)  # Applies all pending migrations
"""
from __future__ import annotations

import logging
import sqlite3
import threading

logger = logging.getLogger("noba")

# ── Migration definitions ─────────────────────────────────────────────────────
# Each migration has:
# - version: integer version number (sequential, starting from 1)
# - up: SQL to apply the migration
# - down: SQL to rollback the migration (for debugging/recovery)

MIGRATIONS: list[dict] = [
    {
        "version": 1,
        "name": "initial_schema",
        "up": """
            -- Core infrastructure tables
            CREATE TABLE IF NOT EXISTS tokens (
                token_hash TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric TEXT NOT NULL,
                value REAL NOT NULL,
                host TEXT DEFAULT '',
                timestamp INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_metrics_metric_ts ON metrics(metric, timestamp);
            CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(timestamp);
        """,
        "down": """
            DROP INDEX IF EXISTS idx_metrics_ts;
            DROP INDEX IF EXISTS idx_metrics_metric_ts;
            DROP TABLE IF EXISTS metrics;
            DROP TABLE IF EXISTS users;
            DROP TABLE IF EXISTS tokens;
        """,
    },
    {
        "version": 2,
        "name": "agents_and_alerts",
        "up": """
            -- Agent registry
            CREATE TABLE IF NOT EXISTS agents (
                hostname TEXT PRIMARY KEY,
                ip TEXT NOT NULL,
                platform TEXT,
                arch TEXT,
                agent_version TEXT,
                last_seen INTEGER NOT NULL,
                config TEXT
            );
            -- Alert history
            CREATE TABLE IF NOT EXISTS alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id TEXT NOT NULL,
                condition TEXT,
                target TEXT,
                severity TEXT,
                metrics TEXT,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_alerts_rule ON alert_history(rule_id);
            CREATE INDEX IF NOT EXISTS idx_alerts_created ON alert_history(created_at);
        """,
        "down": """
            DROP INDEX IF EXISTS idx_alerts_created;
            DROP INDEX IF EXISTS idx_alerts_rule;
            DROP TABLE IF EXISTS alert_history;
            DROP TABLE IF EXISTS agents;
        """,
    },
    {
        "version": 3,
        "name": "automations_and_healing",
        "up": """
            -- Automations
            CREATE TABLE IF NOT EXISTS automations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                config TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                created_at INTEGER NOT NULL
            );
            -- Job runs
            CREATE TABLE IF NOT EXISTS job_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                automation_id TEXT,
                trigger TEXT,
                triggered_by TEXT,
                status TEXT,
                started_at INTEGER,
                finished_at INTEGER,
                output TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_job_runs_automation ON job_runs(automation_id);
            -- Healing ledger
            CREATE TABLE IF NOT EXISTS heal_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                correlation_key TEXT NOT NULL,
                rule_id TEXT,
                target TEXT,
                action_type TEXT,
                action_success INTEGER,
                verified INTEGER,
                duration_s REAL,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_heal_correlation ON heal_outcomes(correlation_key);
            CREATE INDEX IF NOT EXISTS idx_heal_rule ON heal_outcomes(rule_id);
        """,
        "down": """
            DROP INDEX IF EXISTS idx_heal_rule;
            DROP INDEX IF EXISTS idx_heal_correlation;
            DROP TABLE IF EXISTS heal_outcomes;
            DROP INDEX IF EXISTS idx_job_runs_automation;
            DROP TABLE IF EXISTS job_runs;
            DROP TABLE IF EXISTS automations;
        """,
    },
    {
        "version": 4,
        "name": "audit_and_trust",
        "up": """
            -- Audit log
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                username TEXT,
                details TEXT,
                ip TEXT,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
            CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
            -- Trust states for healing
            CREATE TABLE IF NOT EXISTS trust_states (
                rule_id TEXT PRIMARY KEY,
                current_level TEXT NOT NULL,
                ceiling TEXT NOT NULL,
                promoted_at INTEGER,
                demoted_at INTEGER,
                last_evaluated INTEGER
            );
        """,
        "down": """
            DROP TABLE IF EXISTS trust_states;
            DROP INDEX IF EXISTS idx_audit_created;
            DROP INDEX IF EXISTS idx_audit_action;
            DROP TABLE IF EXISTS audit_log;
        """,
    },
    {
        "version": 5,
        "name": "endpoints_and_baselines",
        "up": """
            -- Endpoint monitors
            CREATE TABLE IF NOT EXISTS endpoint_monitors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                target TEXT,
                interval INTEGER DEFAULT 300,
                enabled INTEGER DEFAULT 1,
                created_at INTEGER NOT NULL
            );
            -- Config baselines for drift detection
            CREATE TABLE IF NOT EXISTS baselines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_group TEXT NOT NULL,
                config_type TEXT NOT NULL,
                checksum TEXT,
                content TEXT,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_baselines_group ON baselines(agent_group);
        """,
        "down": """
            DROP INDEX IF EXISTS idx_baselines_group;
            DROP TABLE IF EXISTS baselines;
            DROP TABLE IF EXISTS endpoint_monitors;
        """,
    },
]

_SCHEMA_VERSION_TABLE = "schema_version"


def _ensure_version_table(conn: sqlite3.Connection) -> int:
    """Ensure schema_version table exists and return current version."""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {_SCHEMA_VERSION_TABLE} (
            version INTEGER PRIMARY KEY,
            applied_at INTEGER NOT NULL
        )
    """)
    row = conn.execute(
        f"SELECT version FROM {_SCHEMA_VERSION_TABLE} ORDER BY version DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else 0


def _apply_migration(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    migration: dict,
) -> bool:
    """Apply a single migration. Returns True on success."""
    version = migration["version"]
    name = migration["name"]
    up_sql = migration["up"]

    try:
        with lock:
            # Execute migration SQL
            conn.executescript(up_sql)
            # Record version
            conn.execute(
                f"INSERT INTO {_SCHEMA_VERSION_TABLE} (version, applied_at) VALUES (?, ?)",
                (version, int(__import__("time").time())),
            )
            conn.commit()
        logger.info("Applied migration: %s (v%d)", name, version)
        return True
    except sqlite3.Error as e:
        logger.error("Migration %s (v%d) failed: %s", name, version, e)
        return False


def run_migrations(conn: sqlite3.Connection, lock: threading.Lock) -> bool:
    """Run all pending migrations. Returns True if all succeeded."""
    try:
        current = _ensure_version_table(conn)
        pending = [m for m in MIGRATIONS if m["version"] > current]

        if not pending:
            logger.debug("Database schema is up to date (v%d)", current)
            return True

        logger.info("Running %d pending migration(s) (current: v%d)", len(pending), current)

        all_success = True
        for migration in pending:
            if not _apply_migration(conn, lock, migration):
                all_success = False
                break

        if all_success:
            logger.info("All migrations applied successfully (now at v%d)", MIGRATIONS[-1]["version"])
        else:
            logger.error("Migration stopped due to error")

        return all_success

    except Exception as e:
        logger.error("Migration framework error: %s", e)
        return False


def get_current_version(conn: sqlite3.Connection) -> int:
    """Get the current schema version."""
    try:
        return _ensure_version_table(conn)
    except Exception:
        return 0


def rollback_migration(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    target_version: int = 0,
) -> bool:
    """Rollback migrations to target_version (default: 0 = all).
    
    WARNING: This is for emergency recovery only. Use with caution.
    """
    try:
        current = _ensure_version_table(conn)
        if target_version >= current:
            logger.warning("No rollback needed (current: v%d, target: v%d)", current, target_version)
            return True

        # Get migrations to rollback (in reverse order)
        to_rollback = [m for m in reversed(MIGRATIONS) if m["version"] > target_version and m["version"] <= current]

        if not to_rollback:
            logger.warning("No migrations found to rollback")
            return True

        logger.warning("Rolling back %d migration(s) (from v%d to v%d)", len(to_rollback), current, target_version)

        for migration in to_rollback:
            version = migration["version"]
            name = migration["name"]
            down_sql = migration["down"]

            try:
                with lock:
                    conn.executescript(down_sql)
                    conn.execute(
                        f"DELETE FROM {_SCHEMA_VERSION_TABLE} WHERE version = ?",
                        (version,),
                    )
                    conn.commit()
                logger.info("Rolled back migration: %s (v%d)", name, version)
            except sqlite3.Error as e:
                logger.error("Rollback of %s (v%d) failed: %s", name, version, e)
                return False

        logger.info("Rollback completed (now at v%d)", target_version)
        return True

    except Exception as e:
        logger.error("Rollback framework error: %s", e)
        return False
