# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Integration tests for the admin router (share/noba-web/server/routers/admin.py)."""
from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, patch


# ===========================================================================
# GET /api/settings
# ===========================================================================

class TestSettingsGet:
    """Settings retrieval — any authenticated user, secrets redacted for non-admins."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/settings")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/settings", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/settings", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/settings", headers=admin_headers)
        assert resp.status_code == 200

    def test_non_admin_gets_redacted_secrets(self, client, viewer_headers):
        with patch("server.routers.admin.read_yaml_settings", return_value={
            "siteName": "NOBA",
            "smtpPassword": "hunter2",
            "apiKey": "secret123",
        }):
            resp = client.get("/api/settings", headers=viewer_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["siteName"] == "NOBA"
            assert data["smtpPassword"] == "***"
            assert data["apiKey"] == "***"

    def test_admin_gets_full_secrets(self, client, admin_headers):
        with patch("server.routers.admin.read_yaml_settings", return_value={
            "siteName": "NOBA",
            "smtpPassword": "hunter2",
            "apiKey": "secret123",
        }):
            resp = client.get("/api/settings", headers=admin_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["siteName"] == "NOBA"
            # Secrets are masked for ALL roles (write-only)
            assert data["smtpPassword"] == "***"
            assert data["apiKey"] == "***"


# ===========================================================================
# POST /api/settings
# ===========================================================================

class TestSettingsPost:
    """Settings update — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/settings", json={"siteName": "X"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/settings", json={"siteName": "X"}, headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/settings", json={"siteName": "X"}, headers=operator_headers)
        assert resp.status_code == 403

    def test_admin_can_update(self, client, admin_headers):
        with patch("server.routers.admin.read_yaml_settings", return_value={}), \
             patch("server.routers.admin.write_yaml_settings", return_value=True), \
             patch("server.routers.admin.validate_integration_urls", return_value=[]):
            resp = client.post("/api/settings", json={"siteName": "NewName"}, headers=admin_headers)
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

    def test_invalid_urls_returns_400(self, client, admin_headers):
        with patch("server.routers.admin.validate_integration_urls",
                   return_value=["Bad URL for field foo"]):
            resp = client.post("/api/settings", json={"foo": "not-a-url"}, headers=admin_headers)
            assert resp.status_code == 400

    def test_write_failure_returns_500(self, client, admin_headers):
        with patch("server.routers.admin.read_yaml_settings", return_value={}), \
             patch("server.routers.admin.write_yaml_settings", return_value=False), \
             patch("server.routers.admin.validate_integration_urls", return_value=[]):
            resp = client.post("/api/settings", json={"siteName": "X"}, headers=admin_headers)
            assert resp.status_code == 500


# ===========================================================================
# POST /api/notifications/test
# ===========================================================================

class TestNotificationsTest:
    """Test notification dispatch — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/notifications/test")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/notifications/test", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/notifications/test", headers=operator_headers)
        assert resp.status_code == 403

    def test_admin_no_channels_configured(self, client, admin_headers):
        with patch("server.routers.admin.read_yaml_settings", return_value={}):
            resp = client.post("/api/notifications/test", headers=admin_headers)
            assert resp.status_code == 200
            assert "No notification channels" in resp.json()["message"]

    def test_admin_sends_notification(self, client, admin_headers):
        with patch("server.routers.admin.read_yaml_settings",
                   return_value={"notifications": {"email": {"enabled": True}}}), \
             patch("server.routers.admin.dispatch_notifications"):
            resp = client.post("/api/notifications/test", headers=admin_headers)
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"


# ===========================================================================
# GET /api/config/changelog
# ===========================================================================

class TestConfigChangelog:
    """Config changelog — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/config/changelog")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/config/changelog", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.get("/api/config/changelog", headers=operator_headers)
        assert resp.status_code == 403

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/config/changelog", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ===========================================================================
# GET /api/audit
# ===========================================================================

class TestAudit:
    """Audit log — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/audit")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/audit", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.get("/api/audit", headers=operator_headers)
        assert resp.status_code == 403

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/audit", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_query_params_accepted(self, client, admin_headers):
        resp = client.get("/api/audit?limit=10&user=admin&action=login&from=0&to=9999999999",
                          headers=admin_headers)
        assert resp.status_code == 200


# ===========================================================================
# GET /api/config/backup
# ===========================================================================

class TestConfigBackup:
    """Config backup download — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/config/backup")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/config/backup", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.get("/api/config/backup", headers=operator_headers)
        assert resp.status_code == 403

    def test_admin_can_download(self, client, admin_headers):
        resp = client.get("/api/config/backup", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/x-yaml"
        assert "noba-config-backup.yaml" in resp.headers.get("content-disposition", "")


# ===========================================================================
# POST /api/config/restore
# ===========================================================================

class TestConfigRestore:
    """Config restore from upload — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/config/restore", content=b"key: value")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/config/restore", content=b"key: value", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/config/restore", content=b"key: value", headers=operator_headers)
        assert resp.status_code == 403

    def test_empty_body_returns_400(self, client, admin_headers):
        resp = client.post("/api/config/restore", content=b"", headers=admin_headers)
        assert resp.status_code == 400

    def test_too_large_returns_413(self, client, admin_headers):
        resp = client.post("/api/config/restore", content=b"x" * (513 * 1024), headers=admin_headers)
        assert resp.status_code == 413

    def test_invalid_yaml_returns_400(self, client, admin_headers):
        resp = client.post("/api/config/restore", content=b"{{{{invalid", headers=admin_headers)
        assert resp.status_code == 400

    def test_non_mapping_yaml_returns_400(self, client, admin_headers):
        resp = client.post("/api/config/restore", content=b"- list\n- items", headers=admin_headers)
        assert resp.status_code == 400

    def test_admin_can_restore_valid_yaml(self, client, admin_headers):
        resp = client.post("/api/config/restore",
                           content=b"siteName: Restored\nbackupDest: /tmp/test\n",
                           headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ===========================================================================
# GET /api/backup/status
# ===========================================================================

class TestBackupStatus:
    """Backup status — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/backup/status")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/backup/status", headers=viewer_headers)
        assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/backup/status", headers=operator_headers)
        assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/backup/status", headers=admin_headers)
        assert resp.status_code == 200

    def test_returns_nas_and_cloud_keys(self, client, admin_headers):
        resp = client.get("/api/backup/status", headers=admin_headers)
        data = resp.json()
        assert "nas" in data
        assert "cloud" in data

    def test_with_state_files(self, client, admin_headers):
        # State file content mocked
        with patch("server.routers.admin._read_state_file",
                   side_effect=lambda path: {
                       "exit_code": "0", "snapshot": "20260301-030000",
                       "duration": "120", "timestamp": "2026-03-01T03:02:00",
                   } if "backup-to-nas" in path else {}):
            resp = client.get("/api/backup/status", headers=admin_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["nas"] is not None
            assert data["nas"]["exit_code"] == 0


# ===========================================================================
# POST /api/backup/report
# ===========================================================================

class TestBackupReport:
    """Backup report email — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/backup/report")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/backup/report", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/backup/report", headers=operator_headers)
        assert resp.status_code == 403

    def test_no_state_returns_404(self, client, admin_headers):
        with patch("server.routers.admin._read_state_file", return_value={}):
            resp = client.post("/api/backup/report", headers=admin_headers)
            assert resp.status_code == 404

    def test_email_not_configured_returns_400(self, client, admin_headers):
        with patch("server.routers.admin._read_state_file",
                   return_value={"exit_code": "0"}), \
             patch("server.routers.admin.read_yaml_settings",
                   return_value={"notifications": {}}):
            resp = client.post("/api/backup/report", headers=admin_headers)
            assert resp.status_code == 400

    def test_admin_sends_report(self, client, admin_headers):
        with patch("server.routers.admin._read_state_file",
                   return_value={"exit_code": "0", "snapshot": "20260301-030000"}), \
             patch("server.routers.admin.read_yaml_settings",
                   return_value={"notifications": {"email": {"enabled": True}}}), \
             patch("server.routers.admin.dispatch_notifications"):
            resp = client.post("/api/backup/report", headers=admin_headers)
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"


# ===========================================================================
# GET /api/backup/history
# ===========================================================================

class TestBackupHistory:
    """Backup history — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/backup/history")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        with patch("server.routers.admin._get_backup_dest", return_value=None):
            resp = client.get("/api/backup/history", headers=viewer_headers)
            assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        with patch("server.routers.admin._get_backup_dest", return_value=None):
            resp = client.get("/api/backup/history", headers=operator_headers)
            assert resp.status_code == 200

    def test_no_dest_returns_empty(self, client, admin_headers):
        with patch("server.routers.admin._get_backup_dest", return_value=None):
            resp = client.get("/api/backup/history", headers=admin_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["snapshots"] == []
            assert data["dest"] == ""

    def test_with_snapshots(self, client, admin_headers):
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_dir = os.path.join(tmpdir, "20260301-030000")
            os.makedirs(snap_dir)
            with patch("server.routers.admin._get_backup_dest", return_value=tmpdir):
                resp = client.get("/api/backup/history", headers=admin_headers)
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["snapshots"]) == 1
                assert data["snapshots"][0]["name"] == "20260301-030000"


# ===========================================================================
# GET /api/backup/snapshots/{name}/browse
# ===========================================================================

class TestSnapshotBrowse:
    """Snapshot browsing — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/backup/snapshots/20260301-030000/browse")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_dir = os.path.join(tmpdir, "20260301-030000")
            os.makedirs(snap_dir)
            with patch("server.routers.admin._get_backup_dest", return_value=tmpdir):
                resp = client.get("/api/backup/snapshots/20260301-030000/browse",
                                  headers=viewer_headers)
                assert resp.status_code == 200

    def test_no_dest_returns_404(self, client, admin_headers):
        with patch("server.routers.admin._get_backup_dest", return_value=None):
            resp = client.get("/api/backup/snapshots/20260301-030000/browse",
                              headers=admin_headers)
            assert resp.status_code == 404

    def test_invalid_snapshot_name_returns_400(self, client, admin_headers):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("server.routers.admin._get_backup_dest", return_value=tmpdir):
                resp = client.get("/api/backup/snapshots/../../etc/passwd/browse",
                                  headers=admin_headers)
                assert resp.status_code in (400, 404, 422)

    def test_browse_directory(self, client, admin_headers):
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_dir = os.path.join(tmpdir, "20260301-030000")
            os.makedirs(os.path.join(snap_dir, "subdir"))
            with open(os.path.join(snap_dir, "file.txt"), "w") as f:
                f.write("hello")
            with patch("server.routers.admin._get_backup_dest", return_value=tmpdir):
                resp = client.get("/api/backup/snapshots/20260301-030000/browse",
                                  headers=admin_headers)
                assert resp.status_code == 200
                data = resp.json()
                assert data["type"] == "dir"
                names = [e["name"] for e in data["entries"]]
                assert "subdir" in names
                assert "file.txt" in names

    def test_browse_file(self, client, admin_headers):
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_dir = os.path.join(tmpdir, "20260301-030000")
            os.makedirs(snap_dir)
            fpath = os.path.join(snap_dir, "test.txt")
            with open(fpath, "w") as f:
                f.write("content")
            with patch("server.routers.admin._get_backup_dest", return_value=tmpdir):
                resp = client.get("/api/backup/snapshots/20260301-030000/browse?path=test.txt",
                                  headers=admin_headers)
                assert resp.status_code == 200
                data = resp.json()
                assert data["type"] == "file"
                assert data["name"] == "test.txt"

    def test_nonexistent_path_returns_404(self, client, admin_headers):
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_dir = os.path.join(tmpdir, "20260301-030000")
            os.makedirs(snap_dir)
            with patch("server.routers.admin._get_backup_dest", return_value=tmpdir):
                resp = client.get("/api/backup/snapshots/20260301-030000/browse?path=nope",
                                  headers=admin_headers)
                assert resp.status_code == 404


# ===========================================================================
# GET /api/backup/snapshots/diff
# ===========================================================================

class TestSnapshotDiff:
    """Snapshot diff — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/backup/snapshots/diff?a=20260301-030000&b=20260302-030000")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ("20260301-030000", "20260302-030000"):
                os.makedirs(os.path.join(tmpdir, name))
            with patch("server.routers.admin._get_backup_dest", return_value=tmpdir):
                resp = client.get("/api/backup/snapshots/diff?a=20260301-030000&b=20260302-030000",
                                  headers=viewer_headers)
                assert resp.status_code == 200

    def test_no_dest_returns_404(self, client, admin_headers):
        with patch("server.routers.admin._get_backup_dest", return_value=None):
            resp = client.get("/api/backup/snapshots/diff?a=20260301-030000&b=20260302-030000",
                              headers=admin_headers)
            assert resp.status_code == 404

    def test_invalid_snapshot_returns_400(self, client, admin_headers):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("server.routers.admin._get_backup_dest", return_value=tmpdir):
                resp = client.get("/api/backup/snapshots/diff?a=bad&b=alsobad",
                                  headers=admin_headers)
                assert resp.status_code == 400

    def test_diff_detects_added_and_removed(self, client, admin_headers):
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_a = os.path.join(tmpdir, "20260301-030000")
            snap_b = os.path.join(tmpdir, "20260302-030000")
            os.makedirs(snap_a)
            os.makedirs(snap_b)
            with open(os.path.join(snap_a, "old.txt"), "w") as f:
                f.write("old")
            with open(os.path.join(snap_b, "new.txt"), "w") as f:
                f.write("new")
            with patch("server.routers.admin._get_backup_dest", return_value=tmpdir):
                resp = client.get("/api/backup/snapshots/diff?a=20260301-030000&b=20260302-030000",
                                  headers=admin_headers)
                assert resp.status_code == 200
                data = resp.json()
                assert "old.txt" in data["removed"]
                assert "new.txt" in data["added"]


# ===========================================================================
# GET /api/backup/file-versions
# ===========================================================================

class TestFileVersions:
    """File versions across snapshots — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/backup/file-versions?path=test.txt")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        with patch("server.routers.admin._get_backup_dest", return_value=None):
            resp = client.get("/api/backup/file-versions?path=test.txt", headers=viewer_headers)
            assert resp.status_code == 404  # no dest configured

    def test_no_path_returns_400(self, client, admin_headers):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("server.routers.admin._get_backup_dest", return_value=tmpdir):
                resp = client.get("/api/backup/file-versions", headers=admin_headers)
                assert resp.status_code == 400

    def test_lists_versions(self, client, admin_headers):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ("20260301-030000", "20260302-030000"):
                snap = os.path.join(tmpdir, name)
                os.makedirs(snap)
                with open(os.path.join(snap, "data.txt"), "w") as f:
                    f.write(f"content-{name}")
            with patch("server.routers.admin._get_backup_dest", return_value=tmpdir):
                resp = client.get("/api/backup/file-versions?path=data.txt",
                                  headers=admin_headers)
                assert resp.status_code == 200
                data = resp.json()
                assert data["path"] == "data.txt"
                assert len(data["versions"]) == 2


# ===========================================================================
# POST /api/backup/restore
# ===========================================================================

class TestBackupRestore:
    """File restore from backup — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/backup/restore", json={"snapshot": "x", "path": "y"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/backup/restore",
                           json={"snapshot": "x", "path": "y"},
                           headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/backup/restore",
                           json={"snapshot": "x", "path": "y"},
                           headers=operator_headers)
        assert resp.status_code == 403

    def test_no_dest_returns_404(self, client, admin_headers):
        with patch("server.routers.admin._get_backup_dest", return_value=None):
            resp = client.post("/api/backup/restore",
                               json={"snapshot": "20260301-030000", "path": "file.txt"},
                               headers=admin_headers)
            assert resp.status_code == 404

    def test_invalid_snapshot_returns_400(self, client, admin_headers):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("server.routers.admin._get_backup_dest", return_value=tmpdir):
                resp = client.post("/api/backup/restore",
                                   json={"snapshot": "bad", "path": "file.txt"},
                                   headers=admin_headers)
                assert resp.status_code == 400

    def test_restore_directory_returns_400(self, client, admin_headers):
        with tempfile.TemporaryDirectory() as tmpdir:
            snap = os.path.join(tmpdir, "20260301-030000")
            subdir = os.path.join(snap, "subdir")
            os.makedirs(subdir)
            with patch("server.routers.admin._get_backup_dest", return_value=tmpdir):
                resp = client.post("/api/backup/restore",
                                   json={"snapshot": "20260301-030000", "path": "subdir"},
                                   headers=admin_headers)
                assert resp.status_code == 400

    def test_forbidden_path_returns_403(self, client, admin_headers):
        with tempfile.TemporaryDirectory() as tmpdir:
            snap = os.path.join(tmpdir, "20260301-030000")
            os.makedirs(snap)
            fpath = os.path.join(snap, "shadow")
            with open(fpath, "w") as f:
                f.write("root:x:...")
            with patch("server.routers.admin._get_backup_dest", return_value=tmpdir), \
                 patch("server.routers.admin.read_yaml_settings", return_value={"backupSources": []}):
                resp = client.post("/api/backup/restore",
                                   json={"snapshot": "20260301-030000", "path": "shadow",
                                          "dest": "/etc/shadow"},
                                   headers=admin_headers)
                assert resp.status_code == 403

    def test_admin_can_restore_file(self, client, admin_headers):
        with tempfile.TemporaryDirectory() as tmpdir:
            snap = os.path.join(tmpdir, "20260301-030000")
            os.makedirs(snap)
            src = os.path.join(snap, "data.txt")
            with open(src, "w") as f:
                f.write("restored content")
            dest = os.path.join(tmpdir, "restored", "data.txt")
            with patch("server.routers.admin._get_backup_dest", return_value=tmpdir), \
                 patch("server.routers.admin.read_yaml_settings",
                       return_value={"backupSources": []}):
                resp = client.post("/api/backup/restore",
                                   json={"snapshot": "20260301-030000",
                                          "path": "data.txt",
                                          "dest": dest},
                                   headers=admin_headers)
                assert resp.status_code == 200
                assert resp.json()["status"] == "ok"
                assert os.path.exists(dest)


# ===========================================================================
# _check_restore_path helper
# ===========================================================================

class TestCheckRestorePath:
    """_check_restore_path uses path separator to avoid prefix false-positives."""

    def test_etc_blocked(self):
        from server.routers.admin import _check_restore_path
        assert _check_restore_path("/etc/passwd") is False

    def test_etc_itself_blocked(self):
        from server.routers.admin import _check_restore_path
        assert _check_restore_path("/etc") is False

    def test_etc2_not_blocked(self):
        """'/etc2/foo' must NOT be blocked — starts with /etc but is not under /etc."""
        from server.routers.admin import _check_restore_path
        assert _check_restore_path("/etc2/foo") is True

    def test_usr_blocked(self):
        from server.routers.admin import _check_restore_path
        assert _check_restore_path("/usr/local/bin/foo") is False

    def test_home_allowed(self):
        from server.routers.admin import _check_restore_path
        assert _check_restore_path("/home/user/documents/file.txt") is True

    def test_var_run_blocked(self):
        from server.routers.admin import _check_restore_path
        assert _check_restore_path("/var/run/service.pid") is False


# ===========================================================================
# GET /api/backup/config-history
# ===========================================================================

class TestConfigHistory:
    """Config version history — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/backup/config-history")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/backup/config-history", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.get("/api/backup/config-history", headers=operator_headers)
        assert resp.status_code == 403

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/backup/config-history", headers=admin_headers)
        assert resp.status_code == 200
        assert "versions" in resp.json()


# ===========================================================================
# GET /api/backup/config-history/{filename}
# ===========================================================================

class TestConfigHistoryDownload:
    """Config version download — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/backup/config-history/config.yaml")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/backup/config-history/config.yaml", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.get("/api/backup/config-history/config.yaml", headers=operator_headers)
        assert resp.status_code == 403

    def test_invalid_filename_returns_400(self, client, admin_headers):
        resp = client.get("/api/backup/config-history/../../etc/passwd", headers=admin_headers)
        assert resp.status_code in (400, 404, 422)

    def test_valid_bak_filename_pattern(self, client, admin_headers):
        # File won't exist but the pattern should be accepted
        resp = client.get("/api/backup/config-history/config.yaml.bak.1234567890",
                          headers=admin_headers)
        assert resp.status_code == 404  # accepted pattern, file just doesn't exist


# ===========================================================================
# GET /api/backup/restic
# ===========================================================================

class TestResticStatus:
    """Restic repository status — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/backup/restic")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        with patch("server.routers.admin.read_yaml_settings", return_value={}):
            resp = client.get("/api/backup/restic", headers=viewer_headers)
            assert resp.status_code == 200
            assert resp.json()["configured"] is False

    def test_not_configured(self, client, admin_headers):
        with patch("server.routers.admin.read_yaml_settings", return_value={}):
            resp = client.get("/api/backup/restic", headers=admin_headers)
            assert resp.status_code == 200
            assert resp.json()["configured"] is False

    def test_restic_not_installed(self, client, admin_headers):
        with patch("server.routers.admin.read_yaml_settings",
                   return_value={"resticRepo": "/backup/repo"}), \
             patch("subprocess.run", side_effect=FileNotFoundError):
            resp = client.get("/api/backup/restic", headers=admin_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["configured"] is True
            assert "not installed" in data["error"]

    def test_restic_with_snapshots(self, client, admin_headers):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps([
            {"short_id": "abc123", "time": "2026-03-01T03:00:00Z",
             "hostname": "noba", "paths": ["/data"]},
        ])
        with patch("server.routers.admin.read_yaml_settings",
                   return_value={"resticRepo": "/backup/repo"}), \
             patch("subprocess.run", return_value=mock_result):
            resp = client.get("/api/backup/restic", headers=admin_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["configured"] is True
            assert len(data["snapshots"]) == 1
            assert data["snapshots"][0]["id"] == "abc123"


# ===========================================================================
# GET /api/backup/schedules
# ===========================================================================

class TestBackupSchedules:
    """Backup schedules — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/backup/schedules")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/backup/schedules", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_operator_can_access(self, client, operator_headers):
        resp = client.get("/api/backup/schedules", headers=operator_headers)
        assert resp.status_code == 200


# ===========================================================================
# POST /api/backup/schedule
# ===========================================================================

class TestBackupScheduleCreate:
    """Create backup schedule — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/backup/schedule", json={"type": "backup"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/backup/schedule", json={"type": "backup"}, headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/backup/schedule", json={"type": "backup"}, headers=operator_headers)
        assert resp.status_code == 403

    def test_invalid_type_returns_400(self, client, admin_headers):
        resp = client.post("/api/backup/schedule", json={"type": "invalid"}, headers=admin_headers)
        assert resp.status_code == 400

    def test_admin_can_create(self, client, admin_headers):
        resp = client.post("/api/backup/schedule",
                           json={"type": "backup", "schedule": "0 3 * * *", "name": "Nightly"},
                           headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "id" in data


# ===========================================================================
# GET /api/backup/progress
# ===========================================================================

class TestBackupProgress:
    """Backup progress — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/backup/progress")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/backup/progress", headers=viewer_headers)
        assert resp.status_code == 200

    def test_no_active_jobs(self, client, admin_headers):
        with patch("server.routers.admin.job_runner") as mock_runner:
            mock_runner.get_active_ids.return_value = []
            resp = client.get("/api/backup/progress", headers=admin_headers)
            assert resp.status_code == 200
            assert resp.json()["running"] is False


# ===========================================================================
# GET /api/backup/health
# ===========================================================================

class TestBackupHealth:
    """Backup health check — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/backup/health")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        with patch("server.routers.admin.read_yaml_settings", return_value={}):
            resp = client.get("/api/backup/health", headers=viewer_headers)
            assert resp.status_code == 200

    def test_not_configured(self, client, admin_headers):
        with patch("server.routers.admin.read_yaml_settings", return_value={}):
            resp = client.get("/api/backup/health", headers=admin_headers)
            assert resp.status_code == 200
            assert resp.json()["accessible"] is False

    def test_accessible_dest(self, client, admin_headers):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("server.routers.admin.read_yaml_settings",
                       return_value={"backupDest": tmpdir}):
                resp = client.get("/api/backup/health", headers=admin_headers)
                assert resp.status_code == 200
                data = resp.json()
                assert data["accessible"] is True
                assert "total_gb" in data
                assert "free_gb" in data


# ===========================================================================
# GET /api/log-viewer
# ===========================================================================

class TestLogViewer:
    """Log viewer — operator+ required."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/log-viewer")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/log-viewer", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_can_access(self, client, operator_headers):
        with patch("server.routers.admin._run_cmd", return_value="no errors"):
            resp = client.get("/api/log-viewer", headers=operator_headers)
            assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        with patch("server.routers.admin._run_cmd", return_value="no errors"):
            resp = client.get("/api/log-viewer", headers=admin_headers)
            assert resp.status_code == 200

    def test_syserr_type(self, client, admin_headers):
        with patch("server.routers.admin._run_cmd", return_value="kernel: something"):
            resp = client.get("/api/log-viewer?type=syserr", headers=admin_headers)
            assert resp.status_code == 200

    def test_action_type(self, client, admin_headers):
        with patch("server.routers.admin._read_file", return_value="action log content"), \
             patch("server.routers.admin.strip_ansi", side_effect=lambda x: x):
            resp = client.get("/api/log-viewer?type=action", headers=admin_headers)
            assert resp.status_code == 200

    def test_backup_type(self, client, admin_headers):
        with patch("server.routers.admin._read_file", return_value="backup log"), \
             patch("server.routers.admin.strip_ansi", side_effect=lambda x: x):
            resp = client.get("/api/log-viewer?type=backup", headers=admin_headers)
            assert resp.status_code == 200

    def test_unknown_type(self, client, admin_headers):
        resp = client.get("/api/log-viewer?type=unknown", headers=admin_headers)
        assert resp.status_code == 200
        assert "Unknown" in resp.text


# ===========================================================================
# GET /api/action-log
# ===========================================================================

class TestActionLog:
    """Action log — operator+ required."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/action-log")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/action-log", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_can_access(self, client, operator_headers):
        with patch("server.routers.admin._read_file", return_value="log data"), \
             patch("server.routers.admin.strip_ansi", side_effect=lambda x: x):
            resp = client.get("/api/action-log", headers=operator_headers)
            assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        with patch("server.routers.admin._read_file", return_value="log data"), \
             patch("server.routers.admin.strip_ansi", side_effect=lambda x: x):
            resp = client.get("/api/action-log", headers=admin_headers)
            assert resp.status_code == 200


# ===========================================================================
# GET /api/reports/bandwidth
# ===========================================================================

class TestBandwidthReport:
    """Bandwidth report — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/reports/bandwidth")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/reports/bandwidth", headers=viewer_headers)
        assert resp.status_code == 200

    def test_returns_report_data(self, client, admin_headers):
        resp = client.get("/api/reports/bandwidth", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_rx" in data
        assert "total_tx" in data
        assert "hourly" in data

    def test_range_param(self, client, admin_headers):
        resp = client.get("/api/reports/bandwidth?range=48", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["range_hours"] == 48


# ===========================================================================
# GET /api/reports/anomalies
# ===========================================================================

class TestAnomalyReport:
    """Anomaly detection report — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/reports/anomalies")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/reports/anomalies", headers=viewer_headers)
        assert resp.status_code == 200

    def test_returns_report_structure(self, client, admin_headers):
        resp = client.get("/api/reports/anomalies", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "range_hours" in data
        assert "anomaly_count" in data
        assert "metrics" in data


# ===========================================================================
# POST /api/reports/custom
# ===========================================================================

class TestCustomReport:
    """Custom report generation — operator required."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/reports/custom", json={"metrics": ["cpu_percent"]})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/reports/custom",
                           json={"metrics": ["cpu_percent"], "title": "Test"},
                           headers=viewer_headers)
        assert resp.status_code == 403

    def test_returns_report_structure(self, client, admin_headers):
        resp = client.post("/api/reports/custom",
                           json={"metrics": ["cpu_percent", "mem_percent"], "range_hours": 12,
                                 "title": "My Report"},
                           headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "My Report"
        assert data["range_hours"] == 12
        assert "generated_at" in data
        assert "metrics" in data


# ===========================================================================
# GET /api/grafana/dashboard
# ===========================================================================

class TestGrafanaDashboard:
    """Grafana dashboard template — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/grafana/dashboard")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/grafana/dashboard", headers=viewer_headers)
        assert resp.status_code == 200

    def test_returns_dashboard_structure(self, client, admin_headers):
        resp = client.get("/api/grafana/dashboard", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "dashboard" in data
        assert "datasource" in data
        assert len(data["dashboard"]["panels"]) >= 4


# ===========================================================================
# GET /api/plugins/available
# ===========================================================================

class TestPluginsAvailable:
    """Available plugins catalog — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/plugins/available")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        with patch("server.routers.admin.read_yaml_settings", return_value={}), \
             patch.object(
                 __import__("server.routers.admin", fromlist=["plugin_manager"]).plugin_manager,
                 "get_available", return_value=[]):
            resp = client.get("/api/plugins/available", headers=viewer_headers)
            assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        with patch("server.routers.admin.read_yaml_settings", return_value={}), \
             patch.object(
                 __import__("server.routers.admin", fromlist=["plugin_manager"]).plugin_manager,
                 "get_available", return_value=[]):
            resp = client.get("/api/plugins/available", headers=operator_headers)
            assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        with patch("server.routers.admin.read_yaml_settings", return_value={}), \
             patch.object(
                 __import__("server.routers.admin", fromlist=["plugin_manager"]).plugin_manager,
                 "get_available", return_value=[]):
            resp = client.get("/api/plugins/available", headers=admin_headers)
            assert resp.status_code == 200


# ===========================================================================
# GET /api/plugins/bundled
# ===========================================================================

class TestPluginsBundled:
    """Bundled plugins catalog — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/plugins/bundled")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        with patch.object(
                __import__("server.routers.admin", fromlist=["plugin_manager"]).plugin_manager,
                "get_bundled_catalog", return_value=[]):
            resp = client.get("/api/plugins/bundled", headers=viewer_headers)
            assert resp.status_code == 200

    def test_operator_can_access(self, client, operator_headers):
        with patch.object(
                __import__("server.routers.admin", fromlist=["plugin_manager"]).plugin_manager,
                "get_bundled_catalog", return_value=[]):
            resp = client.get("/api/plugins/bundled", headers=operator_headers)
            assert resp.status_code == 200

    def test_admin_can_access(self, client, admin_headers):
        with patch.object(
                __import__("server.routers.admin", fromlist=["plugin_manager"]).plugin_manager,
                "get_bundled_catalog", return_value=[]):
            resp = client.get("/api/plugins/bundled", headers=admin_headers)
            assert resp.status_code == 200


# ===========================================================================
# POST /api/plugins/install
# ===========================================================================

class TestPluginsInstall:
    """Plugin install — admin only."""

    def test_no_auth_returns_401(self, client):
        resp = client.post("/api/plugins/install", json={"filename": "x.py"})
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/plugins/install", json={"filename": "x.py"}, headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/plugins/install", json={"filename": "x.py"}, headers=operator_headers)
        assert resp.status_code == 403

    def test_missing_filename_returns_400(self, client, admin_headers):
        resp = client.post("/api/plugins/install", json={}, headers=admin_headers)
        assert resp.status_code == 400

    def test_remote_missing_url_returns_400(self, client, admin_headers):
        resp = client.post("/api/plugins/install",
                           json={"filename": "x.py", "bundled": False},
                           headers=admin_headers)
        assert resp.status_code == 400

    def test_bundled_install(self, client, admin_headers):
        with patch.object(
                __import__("server.routers.admin", fromlist=["plugin_manager"]).plugin_manager,
                "install_bundled", return_value=True):
            resp = client.post("/api/plugins/install",
                               json={"filename": "test-plugin.py", "bundled": True},
                               headers=admin_headers)
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"


# ===========================================================================
# GET/POST /api/plugins/{plugin_id}/config
# ===========================================================================

class TestPluginConfig:
    """Plugin configuration — admin only."""

    def test_get_no_auth_returns_401(self, client):
        resp = client.get("/api/plugins/myplugin/config")
        assert resp.status_code == 401

    def test_get_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/plugins/myplugin/config", headers=viewer_headers)
        assert resp.status_code == 403

    def test_post_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/plugins/myplugin/config", json={}, headers=viewer_headers)
        assert resp.status_code == 403

    def test_post_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/plugins/myplugin/config", json={}, headers=operator_headers)
        assert resp.status_code == 403

    def test_get_no_schema_returns_404(self, client, admin_headers):
        with patch.object(
                __import__("server.routers.admin", fromlist=["plugin_manager"]).plugin_manager,
                "get_plugin_config", return_value=({}, None)):
            resp = client.get("/api/plugins/myplugin/config", headers=admin_headers)
            assert resp.status_code == 404

    def test_get_with_schema(self, client, admin_headers):
        schema = {"fields": [{"name": "token", "type": "string"}]}
        with patch.object(
                __import__("server.routers.admin", fromlist=["plugin_manager"]).plugin_manager,
                "get_plugin_config", return_value=({"token": "abc"}, schema)):
            resp = client.get("/api/plugins/myplugin/config", headers=admin_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["config"]["token"] == "abc"
            assert data["schema"] == schema

    def test_post_validation_errors_returns_400(self, client, admin_headers):
        with patch.object(
                __import__("server.routers.admin", fromlist=["plugin_manager"]).plugin_manager,
                "set_plugin_config", return_value=["Field 'token' is required"]):
            resp = client.post("/api/plugins/myplugin/config",
                               json={"token": ""},
                               headers=admin_headers)
            assert resp.status_code == 400

    def test_post_success(self, client, admin_headers):
        with patch.object(
                __import__("server.routers.admin", fromlist=["plugin_manager"]).plugin_manager,
                "set_plugin_config", return_value=[]):
            resp = client.post("/api/plugins/myplugin/config",
                               json={"token": "new-val"},
                               headers=admin_headers)
            assert resp.status_code == 200


# ===========================================================================
# GET /api/plugins/managed
# ===========================================================================

class TestPluginsManaged:
    """Managed plugins list — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/plugins/managed")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        with patch.object(
                __import__("server.routers.admin", fromlist=["plugin_manager"]).plugin_manager,
                "get_managed", return_value=[]):
            resp = client.get("/api/plugins/managed", headers=viewer_headers)
            assert resp.status_code == 200


# ===========================================================================
# POST /api/plugins/{name}/enable, /disable, /reload
# ===========================================================================

class TestPluginEnableDisableReload:
    """Plugin enable/disable/reload — admin only."""

    def test_enable_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/plugins/myplugin/enable", headers=viewer_headers)
        assert resp.status_code == 403

    def test_enable_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/plugins/myplugin/enable", headers=operator_headers)
        assert resp.status_code == 403

    def test_disable_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/plugins/myplugin/disable", headers=viewer_headers)
        assert resp.status_code == 403

    def test_disable_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/plugins/myplugin/disable", headers=operator_headers)
        assert resp.status_code == 403

    def test_reload_viewer_returns_403(self, client, viewer_headers):
        resp = client.post("/api/plugins/reload", headers=viewer_headers)
        assert resp.status_code == 403

    def test_reload_operator_returns_403(self, client, operator_headers):
        resp = client.post("/api/plugins/reload", headers=operator_headers)
        assert resp.status_code == 403

    def test_enable_not_found_returns_404(self, client, admin_headers):
        with patch.object(
                __import__("server.routers.admin", fromlist=["plugin_manager"]).plugin_manager,
                "enable_plugin", return_value=False):
            resp = client.post("/api/plugins/nonexistent/enable", headers=admin_headers)
            assert resp.status_code == 404

    def test_enable_success(self, client, admin_headers):
        with patch.object(
                __import__("server.routers.admin", fromlist=["plugin_manager"]).plugin_manager,
                "enable_plugin", return_value=True):
            resp = client.post("/api/plugins/myplugin/enable", headers=admin_headers)
            assert resp.status_code == 200
            assert resp.json()["enabled"] is True

    def test_disable_success(self, client, admin_headers):
        with patch.object(
                __import__("server.routers.admin", fromlist=["plugin_manager"]).plugin_manager,
                "disable_plugin", return_value=True):
            resp = client.post("/api/plugins/myplugin/disable", headers=admin_headers)
            assert resp.status_code == 200
            assert resp.json()["enabled"] is False

    def test_reload_success(self, client, admin_headers):
        pm = __import__("server.routers.admin", fromlist=["plugin_manager"]).plugin_manager
        with patch.object(pm, "reload"), \
             patch.object(type(pm), "count", new_callable=lambda: property(lambda self: 3)):
            resp = client.post("/api/plugins/reload", headers=admin_headers)
            assert resp.status_code == 200


# ===========================================================================
# GET /api/runbooks, /api/runbooks/{id}
# ===========================================================================

class TestRunbooks:
    """Runbooks — any authenticated user."""

    def test_list_no_auth_returns_401(self, client):
        resp = client.get("/api/runbooks")
        assert resp.status_code == 401

    def test_list_viewer_can_access(self, client, viewer_headers):
        with patch("server.routers.admin.read_yaml_settings", return_value={}):
            resp = client.get("/api/runbooks", headers=viewer_headers)
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)

    def test_list_returns_runbooks(self, client, admin_headers):
        runbooks = [{"id": "rb1", "name": "Deploy"}, {"id": "rb2", "name": "Rollback"}]
        with patch("server.routers.admin.read_yaml_settings",
                   return_value={"runbooks": runbooks}):
            resp = client.get("/api/runbooks", headers=admin_headers)
            assert resp.status_code == 200
            assert len(resp.json()) == 2

    def test_detail_no_auth_returns_401(self, client):
        resp = client.get("/api/runbooks/rb1")
        assert resp.status_code == 401

    def test_detail_found(self, client, admin_headers):
        runbooks = [{"id": "rb1", "name": "Deploy"}]
        with patch("server.routers.admin.read_yaml_settings",
                   return_value={"runbooks": runbooks}):
            resp = client.get("/api/runbooks/rb1", headers=admin_headers)
            assert resp.status_code == 200
            assert resp.json()["id"] == "rb1"

    def test_detail_not_found(self, client, admin_headers):
        with patch("server.routers.admin.read_yaml_settings",
                   return_value={"runbooks": []}):
            resp = client.get("/api/runbooks/nonexistent", headers=admin_headers)
            assert resp.status_code == 404


# ===========================================================================
# GET /api/graylog/search
# ===========================================================================

class TestGraylogSearch:
    """Graylog search — any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/graylog/search")
        assert resp.status_code == 401

    def test_viewer_returns_403(self, client, viewer_headers):
        resp = client.get("/api/graylog/search", headers=viewer_headers)
        assert resp.status_code == 403

    def test_not_configured_returns_404(self, client, admin_headers):
        with patch("server.routers.admin.read_yaml_settings", return_value={}):
            resp = client.get("/api/graylog/search", headers=admin_headers)
            assert resp.status_code == 404

    def test_configured_returns_results(self, client, admin_headers):
        with patch("server.routers.admin.read_yaml_settings",
                   return_value={"graylogUrl": "http://graylog:9000", "graylogToken": "tok"}), \
             patch("server.integrations.get_graylog",
                   return_value={"messages": [{"message": "test"}], "total": 1}):
            resp = client.get("/api/graylog/search?q=error&hours=2", headers=admin_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 1

    def test_returns_empty_on_none(self, client, admin_headers):
        with patch("server.routers.admin.read_yaml_settings",
                   return_value={"graylogUrl": "http://graylog:9000", "graylogToken": "tok"}), \
             patch("server.integrations.get_graylog", return_value=None):
            resp = client.get("/api/graylog/search", headers=admin_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["messages"] == []
            assert data["total"] == 0
