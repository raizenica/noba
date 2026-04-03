# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the backup verification feature (Feature 4)."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tarfile
import tempfile

# Ensure the agent module is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "share", "noba-agent"))

from server.db import Database


def _make_db():
    """Create a fresh temp DB for each test."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_test_bv_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


# ── Database layer tests ─────────────────────────────────────────────────────

class TestRecordVerification:
    def test_record_and_list(self):
        db, path = _make_db()
        try:
            vid = db.record_backup_verification(
                backup_path="/mnt/nas/backup.tar.gz",
                hostname="host-a",
                verification_type="checksum",
                status="ok",
                details=json.dumps({"sha256": "abc123", "size": 1024}),
            )
            assert vid is not None

            results = db.list_backup_verifications()
            assert len(results) == 1
            assert results[0]["backup_path"] == "/mnt/nas/backup.tar.gz"
            assert results[0]["hostname"] == "host-a"
            assert results[0]["verification_type"] == "checksum"
            assert results[0]["status"] == "ok"
            assert results[0]["details"]["sha256"] == "abc123"
            assert results[0]["verified_at"] is not None
        finally:
            _cleanup(path)

    def test_filter_by_hostname(self):
        db, path = _make_db()
        try:
            db.record_backup_verification("/a", "host-a", "checksum", "ok")
            db.record_backup_verification("/b", "host-b", "checksum", "ok")
            a_only = db.list_backup_verifications(hostname="host-a")
            assert len(a_only) == 1
            assert a_only[0]["hostname"] == "host-a"
        finally:
            _cleanup(path)

    def test_limit(self):
        db, path = _make_db()
        try:
            for i in range(10):
                db.record_backup_verification(f"/path/{i}", "host-a", "checksum", "ok")
            results = db.list_backup_verifications(limit=5)
            assert len(results) == 5
        finally:
            _cleanup(path)

    def test_record_failed_verification(self):
        db, path = _make_db()
        try:
            vid = db.record_backup_verification(
                backup_path="/mnt/nas/corrupt.db",
                hostname="host-a",
                verification_type="db_integrity",
                status="error",
                details=json.dumps({"integrity_check": "corrupt"}),
            )
            assert vid is not None
            results = db.list_backup_verifications()
            assert results[0]["status"] == "error"
        finally:
            _cleanup(path)

    def test_ordering_is_newest_first(self):
        db, path = _make_db()
        try:
            import time
            db.record_backup_verification("/old", "host-a", "checksum", "ok")
            time.sleep(0.05)
            db.record_backup_verification("/new", "host-a", "checksum", "ok")
            results = db.list_backup_verifications()
            assert results[0]["backup_path"] == "/new"
            assert results[1]["backup_path"] == "/old"
        finally:
            _cleanup(path)


class TestBackup321Status:
    def test_create_and_retrieve(self):
        db, path = _make_db()
        try:
            row_id = db.update_backup_321_status(
                "nas-daily",
                copies=3,
                media_types=["ssd", "nas", "cloud"],
                has_offsite=True,
            )
            assert row_id is not None

            status = db.get_backup_321_status()
            assert len(status) == 1
            assert status[0]["backup_name"] == "nas-daily"
            assert status[0]["copies"] == 3
            assert len(status[0]["media_types"]) == 3
            assert status[0]["has_offsite"] is True
        finally:
            _cleanup(path)

    def test_update_existing(self):
        db, path = _make_db()
        try:
            db.update_backup_321_status("nas-daily", copies=1)
            db.update_backup_321_status("nas-daily", copies=3)
            status = db.get_backup_321_status()
            assert len(status) == 1
            assert status[0]["copies"] == 3
        finally:
            _cleanup(path)

    def test_partial_update_preserves_fields(self):
        db, path = _make_db()
        try:
            db.update_backup_321_status(
                "nas-daily", copies=2,
                media_types=["ssd", "nas"], has_offsite=False,
            )
            db.update_backup_321_status("nas-daily", has_offsite=True)
            status = db.get_backup_321_status()
            assert status[0]["copies"] == 2
            assert status[0]["has_offsite"] is True
            assert len(status[0]["media_types"]) == 2
        finally:
            _cleanup(path)

    def test_multiple_backups(self):
        db, path = _make_db()
        try:
            db.update_backup_321_status("nas-daily", copies=3)
            db.update_backup_321_status("cloud-weekly", copies=2)
            status = db.get_backup_321_status()
            assert len(status) == 2
            names = {s["backup_name"] for s in status}
            assert names == {"nas-daily", "cloud-weekly"}
        finally:
            _cleanup(path)

    def test_empty_status(self):
        db, path = _make_db()
        try:
            status = db.get_backup_321_status()
            assert status == []
        finally:
            _cleanup(path)


# ── Agent-side verification logic tests ──────────────────────────────────────

class TestAgentVerifyBackup:
    def test_checksum_valid_file(self):
        from commands import _cmd_verify_backup

        fd, fpath = tempfile.mkstemp(prefix="noba_test_bv_")
        try:
            os.write(fd, b"test backup data")
            os.close(fd)

            result = _cmd_verify_backup(
                {"path": fpath, "verification_type": "checksum"}, {}
            )
            assert result["status"] == "ok"
            assert result["verification_type"] == "checksum"
            assert result["path"] == fpath
            assert "sha256" in result["details"]
            assert result["details"]["size"] == 16

            # Verify the checksum is correct
            expected = hashlib.sha256(b"test backup data").hexdigest()
            assert result["details"]["sha256"] == expected
        finally:
            try:
                os.unlink(fpath)
            except OSError:
                pass

    def test_checksum_missing_file(self):
        from commands import _cmd_verify_backup

        result = _cmd_verify_backup(
            {"path": "/nonexistent/backup.tar.gz", "verification_type": "checksum"}, {}
        )
        assert result["status"] == "error"

    def test_restore_test_valid_tar(self):
        from commands import _cmd_verify_backup

        fd, fpath = tempfile.mkstemp(suffix=".tar.gz", prefix="noba_test_bv_")
        os.close(fd)
        try:
            with tarfile.open(fpath, "w:gz") as tf:
                # Add a few test files
                for name in ["config.yaml", "data/db.sqlite", "README"]:
                    info = tarfile.TarInfo(name=name)
                    info.size = 10
                    tf.addfile(info, fileobj=__import__("io").BytesIO(b"0123456789"))

            result = _cmd_verify_backup(
                {"path": fpath, "verification_type": "restore_test"}, {}
            )
            assert result["status"] == "ok"
            assert result["verification_type"] == "restore_test"
            assert result["details"]["file_count"] == 3
            assert result["details"]["readable"] is True
            assert "config.yaml" in result["details"]["sample_files"]
        finally:
            os.unlink(fpath)

    def test_restore_test_not_a_tar(self):
        from commands import _cmd_verify_backup

        fd, fpath = tempfile.mkstemp(prefix="noba_test_bv_")
        os.write(fd, b"not a tar file")
        os.close(fd)
        try:
            result = _cmd_verify_backup(
                {"path": fpath, "verification_type": "restore_test"}, {}
            )
            assert result["status"] == "error"
        finally:
            os.unlink(fpath)

    def test_db_integrity_valid_db(self):
        from commands import _cmd_verify_backup

        fd, fpath = tempfile.mkstemp(suffix=".db", prefix="noba_test_bv_")
        os.close(fd)
        try:
            conn = sqlite3.connect(fpath)
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)")
            conn.execute("INSERT INTO test VALUES (1, 'hello')")
            conn.commit()
            conn.close()

            result = _cmd_verify_backup(
                {"path": fpath, "verification_type": "db_integrity"}, {}
            )
            assert result["status"] == "ok"
            assert result["verification_type"] == "db_integrity"
            assert result["details"]["integrity_check"] == "ok"
        finally:
            os.unlink(fpath)

    def test_db_integrity_not_a_db(self):
        from commands import _cmd_verify_backup

        fd, fpath = tempfile.mkstemp(prefix="noba_test_bv_")
        os.write(fd, b"not a database file at all")
        os.close(fd)
        try:
            result = _cmd_verify_backup(
                {"path": fpath, "verification_type": "db_integrity"}, {}
            )
            # SQLite may return error or "not a database"
            assert result["status"] == "error" or "not a database" in str(result.get("details", ""))
        finally:
            os.unlink(fpath)

    def test_missing_path_parameter(self):
        from commands import _cmd_verify_backup

        result = _cmd_verify_backup({}, {})
        assert result["status"] == "error"
        assert "path" in result["error"].lower()

    def test_unknown_verification_type(self):
        from commands import _cmd_verify_backup

        fd, fpath = tempfile.mkstemp(prefix="noba_test_bv_")
        os.write(fd, b"data")
        os.close(fd)
        try:
            result = _cmd_verify_backup(
                {"path": fpath, "verification_type": "nonexistent"}, {}
            )
            assert result["status"] == "error"
        finally:
            os.unlink(fpath)


# ── Agent config validation tests ────────────────────────────────────────────

class TestAgentConfigValidation:
    def test_verify_backup_in_risk_levels(self):
        from server.agent_config import RISK_LEVELS
        assert "verify_backup" in RISK_LEVELS
        assert RISK_LEVELS["verify_backup"] == "medium"

    def test_validate_params_valid(self):
        from server.agent_config import validate_command_params
        result = validate_command_params("verify_backup", {
            "path": "/mnt/nas/backup.tar.gz",
            "verification_type": "checksum",
        })
        assert result is None  # No error

    def test_validate_params_empty_path(self):
        from server.agent_config import validate_command_params
        result = validate_command_params("verify_backup", {"path": ""})
        assert result is not None

    def test_validate_params_invalid_type(self):
        from server.agent_config import validate_command_params
        result = validate_command_params("verify_backup", {
            "path": "/some/path",
            "verification_type": "invalid_type",
        })
        assert result is not None

    def test_validate_params_traversal_blocked(self):
        from server.agent_config import validate_command_params
        result = validate_command_params("verify_backup", {
            "path": "/etc/../etc/shadow",
            "verification_type": "checksum",
        })
        assert result is not None
