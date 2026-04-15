# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for concurrent database access."""
from __future__ import annotations

import threading


def test_concurrent_metric_inserts(tmp_path):
    """Multiple threads can insert metrics without data corruption."""
    from server.db.core import Database

    db_path = str(tmp_path / "subdir" / "test.db")
    db = Database(db_path)
    errors = []

    def insert_batch(thread_id: int) -> None:
        try:
            for i in range(10):
                db.insert_metrics([
                    (f"cpu_{thread_id}", float(i), None),
                ])
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=insert_batch, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent inserts raised exceptions: {errors}"

    # Verify data was actually written for thread 0
    history = db.get_history("cpu_0", range_hours=24, raw=True)
    assert len(history) > 0


def test_concurrent_inserts_all_threads_write(tmp_path):
    """All threads successfully write their data."""
    from server.db.core import Database

    db = Database(str(tmp_path / "test.db"))
    errors = []

    def insert_batch(thread_id: int) -> None:
        try:
            for i in range(5):
                db.insert_metrics([
                    (f"metric_t{thread_id}", float(i * thread_id + 1), None),
                ])
        except Exception as e:
            errors.append(e)

    num_threads = 5
    threads = [threading.Thread(target=insert_batch, args=(i,)) for i in range(1, num_threads + 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent inserts raised exceptions: {errors}"

    # Verify each thread's metric key was written
    for thread_id in range(1, num_threads + 1):
        history = db.get_history(f"metric_t{thread_id}", range_hours=24, raw=True)
        assert len(history) > 0, f"No history found for thread {thread_id}"


def test_concurrent_read_write(tmp_path):
    """Concurrent reads and writes do not cause errors."""
    from server.db.core import Database

    db = Database(str(tmp_path / "test.db"))
    errors = []

    # Pre-populate some data
    db.insert_metrics([("shared_metric", 42.0, None)])

    def writer(thread_id: int) -> None:
        try:
            for i in range(5):
                db.insert_metrics([(f"write_{thread_id}", float(i), None)])
        except Exception as e:
            errors.append(("write", thread_id, e))

    def reader(thread_id: int) -> None:
        try:
            for _ in range(5):
                db.get_history("shared_metric", range_hours=24, raw=True)
        except Exception as e:
            errors.append(("read", thread_id, e))

    threads = []
    for i in range(3):
        threads.append(threading.Thread(target=writer, args=(i,)))
        threads.append(threading.Thread(target=reader, args=(i,)))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent read/write raised exceptions: {errors}"


def test_database_accepts_custom_path(tmp_path):
    """Database can be instantiated with a custom file path."""
    from server.db.core import Database

    custom_path = str(tmp_path / "custom" / "mydb.db")
    db = Database(custom_path)

    # Basic sanity: insert and retrieve
    db.insert_metrics([("test_key", 99.0, None)])
    history = db.get_history("test_key", range_hours=1, raw=True)
    assert len(history) > 0
    assert history[0]["value"] == 99.0
