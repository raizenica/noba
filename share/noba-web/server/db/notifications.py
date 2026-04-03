# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – DB notification functions."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time

logger = logging.getLogger("noba")


def insert_notification(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    level: str,
    title: str,
    message: str,
    username: str | None = None,
) -> None:
    """Insert a notification."""
    try:
        with lock:
            conn.execute(
                "INSERT INTO notifications (timestamp, level, title, message, username) "
                "VALUES (?,?,?,?,?)",
                (int(time.time()), level, title, message, username),
            )
            conn.commit()
    except Exception as e:
        logger.error("insert_notification failed: %s", e)


def get_notifications(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username: str | None = None,
    unread_only: bool = False,
    limit: int = 50,
) -> list[dict]:
    """Query notifications with optional filters."""
    try:
        clauses: list[str] = []
        params: list = []
        if username:
            clauses.append("(username = ? OR username IS NULL)")
            params.append(username)
        if unread_only:
            clauses.append("read = 0")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with lock:
            rows = conn.execute(
                "SELECT id, timestamp, level, title, message, read, username "
                f"FROM notifications{where} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()
        return [
            {
                "id": r[0], "timestamp": r[1], "level": r[2],
                "title": r[3], "message": r[4], "read": bool(r[5]),
                "username": r[6],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("get_notifications failed: %s", e)
        return []


def mark_notification_read(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    notif_id: int,
    username: str,
) -> None:
    """Mark a single notification as read."""
    try:
        with lock:
            conn.execute(
                "UPDATE notifications SET read = 1 "
                "WHERE id = ? AND (username = ? OR username IS NULL)",
                (notif_id, username),
            )
            conn.commit()
    except Exception as e:
        logger.error("mark_notification_read failed: %s", e)


def mark_all_notifications_read(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username: str,
) -> None:
    """Mark all notifications for a user as read."""
    try:
        with lock:
            conn.execute(
                "UPDATE notifications SET read = 1 "
                "WHERE (username = ? OR username IS NULL) AND read = 0",
                (username,),
            )
            conn.commit()
    except Exception as e:
        logger.error("mark_all_notifications_read failed: %s", e)


def get_unread_count(
    conn: sqlite3.Connection,
    lock: threading.Lock,
    username: str,
) -> int:
    """Return count of unread notifications for a user."""
    try:
        with lock:
            r = conn.execute(
                "SELECT COUNT(*) FROM notifications "
                "WHERE (username = ? OR username IS NULL) AND read = 0",
                (username,),
            ).fetchone()
        return r[0] if r else 0
    except Exception as e:
        logger.error("get_unread_count failed: %s", e)
        return 0


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS notifications (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp  INTEGER NOT NULL,
            level      TEXT NOT NULL,
            title      TEXT NOT NULL,
            message    TEXT,
            read       INTEGER NOT NULL DEFAULT 0,
            username   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(username, read);
    """)


class _NotificationsMixin:
    def insert_notification(self, level: str, title: str, message: str,
                            username: str | None = None) -> None:
        insert_notification(self._get_conn(), self._lock, level, title, message,
                            username=username)

    def get_notifications(self, username: str | None = None,
                          unread_only: bool = False, limit: int = 50) -> list[dict]:
        return get_notifications(self._get_read_conn(), self._read_lock, username=username,
                                 unread_only=unread_only, limit=limit)

    def mark_notification_read(self, notif_id: int, username: str) -> None:
        mark_notification_read(self._get_conn(), self._lock, notif_id, username)

    def mark_all_notifications_read(self, username: str) -> None:
        mark_all_notifications_read(self._get_conn(), self._lock, username)

    def get_unread_count(self, username: str) -> int:
        return get_unread_count(self._get_read_conn(), self._read_lock, username)
