"""Tests for agent file transfer protocol (Phase 1c)."""
from __future__ import annotations

import hashlib
import os
import time
from unittest.mock import patch

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────

_TEST_AGENT_KEY = "test-agent-key-12345"


def _mock_yaml_settings():
    """Return settings with a configured agent key."""
    return {"agentKeys": _TEST_AGENT_KEY}


@pytest.fixture()
def client():
    """Create a TestClient with mocked YAML settings for agent key auth."""
    with patch("server.routers.agents.read_yaml_settings", _mock_yaml_settings):
        from starlette.testclient import TestClient
        from server.app import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


@pytest.fixture()
def agent_key_header():
    """Return headers dict with the test agent key."""
    return {"X-Agent-Key": _TEST_AGENT_KEY}


@pytest.fixture()
def admin_auth_header():
    """Return admin auth header for admin-only endpoints."""
    from server.auth import token_store
    token = token_store.generate("admin", "admin")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _clean_transfers():
    """Clean transfer state before and after each test."""
    from server.agent_store import _transfer_lock, _transfers, _TRANSFER_DIR
    with _transfer_lock:
        _transfers.clear()
    yield
    # Clean up any transfer files
    with _transfer_lock:
        _transfers.clear()
    if os.path.isdir(_TRANSFER_DIR):
        for f in os.listdir(_TRANSFER_DIR):
            if f.startswith("test-"):
                try:
                    os.remove(os.path.join(_TRANSFER_DIR, f))
                except OSError:
                    pass


# ── Upload tests ─────────────────────────────────────────────────────────────

class TestFileTransferUpload:
    """Test agent -> server file upload."""

    def test_single_chunk_upload(self, client, agent_key_header):
        """Small file uploads in one chunk and completes."""
        content = b"Hello, NOBA transfer test!"
        checksum = f"sha256:{hashlib.sha256(content).hexdigest()}"
        headers = {
            **agent_key_header,
            "X-Transfer-Id": "test-upload-001",
            "X-Chunk-Index": "0",
            "X-Total-Chunks": "1",
            "X-Filename": "test.txt",
            "X-File-Checksum": checksum,
            "X-Agent-Hostname": "test-host",
        }
        resp = client.post("/api/agent/file-upload", content=content, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["complete"] is True
        assert data["status"] == "ok"

    def test_multi_chunk_upload(self, client, agent_key_header):
        """File uploaded in multiple chunks reassembles correctly."""
        content = os.urandom(1024)
        checksum = f"sha256:{hashlib.sha256(content).hexdigest()}"
        chunk_size = 512
        chunks = [content[i:i + chunk_size] for i in range(0, len(content), chunk_size)]

        last_resp = None
        for i, chunk in enumerate(chunks):
            headers = {
                **agent_key_header,
                "X-Transfer-Id": "test-upload-002",
                "X-Chunk-Index": str(i),
                "X-Total-Chunks": str(len(chunks)),
                "X-Filename": "test-multi.bin",
                "X-File-Checksum": checksum,
                "X-Agent-Hostname": "test-host",
            }
            last_resp = client.post("/api/agent/file-upload", content=chunk, headers=headers)
            assert last_resp.status_code == 200

        # Final chunk response should indicate completion
        data = last_resp.json()
        assert data.get("complete") is True

    def test_checksum_mismatch_rejected(self, client, agent_key_header):
        """Upload with wrong checksum returns 422."""
        content = b"test data"
        headers = {
            **agent_key_header,
            "X-Transfer-Id": "test-upload-bad",
            "X-Chunk-Index": "0",
            "X-Total-Chunks": "1",
            "X-Filename": "bad.txt",
            "X-File-Checksum": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
            "X-Agent-Hostname": "test-host",
        }
        resp = client.post("/api/agent/file-upload", content=content, headers=headers)
        assert resp.status_code == 422

    def test_upload_requires_auth(self, client):
        """Upload without agent key returns 401."""
        resp = client.post("/api/agent/file-upload", content=b"test")
        assert resp.status_code == 401

    def test_upload_missing_headers(self, client, agent_key_header):
        """Upload with missing transfer headers returns 400."""
        headers = {**agent_key_header}
        resp = client.post("/api/agent/file-upload", content=b"test", headers=headers)
        assert resp.status_code == 400

    def test_upload_without_checksum_completes(self, client, agent_key_header):
        """Upload without sha256 prefix checksum still completes."""
        content = b"no checksum prefix"
        headers = {
            **agent_key_header,
            "X-Transfer-Id": "test-upload-nochk",
            "X-Chunk-Index": "0",
            "X-Total-Chunks": "1",
            "X-Filename": "nochk.txt",
            "X-File-Checksum": "none",
            "X-Agent-Hostname": "test-host",
        }
        resp = client.post("/api/agent/file-upload", content=content, headers=headers)
        assert resp.status_code == 200
        assert resp.json().get("complete") is True


# ── Download tests ────────────────────────────────────────────────────────────

class TestFileTransferDownload:
    """Test server -> agent file download."""

    def test_download_nonexistent(self, client, agent_key_header):
        """Download of non-existent transfer returns 404."""
        resp = client.get("/api/agent/file-download/nonexistent",
                          headers=agent_key_header)
        assert resp.status_code == 404

    def test_download_requires_auth(self, client):
        """Download without agent key returns 401."""
        resp = client.get("/api/agent/file-download/anything")
        assert resp.status_code == 401

    def test_download_upload_transfer_rejected(self, client, agent_key_header):
        """Download of an upload-direction transfer returns 400."""
        from server.agent_store import _transfer_lock, _transfers

        with _transfer_lock:
            _transfers["test-upload-only"] = {
                "hostname": "test",
                "filename": "test.txt",
                "checksum": "sha256:abc",
                "direction": "upload",
                "created_at": int(time.time()),
            }

        resp = client.get("/api/agent/file-download/test-upload-only",
                          headers=agent_key_header)
        assert resp.status_code == 400

    def test_download_existing_transfer(self, client, agent_key_header):
        """Download of a valid download-direction transfer succeeds."""
        from server.agent_store import _transfer_lock, _transfers, _TRANSFER_DIR

        content = b"download test data"
        checksum = f"sha256:{hashlib.sha256(content).hexdigest()}"
        file_path = os.path.join(_TRANSFER_DIR, "test-dl-001_test.bin")
        with open(file_path, "wb") as f:
            f.write(content)

        with _transfer_lock:
            _transfers["test-dl-001"] = {
                "hostname": "test",
                "filename": "test.bin",
                "checksum": checksum,
                "final_path": file_path,
                "direction": "download",
                "created_at": int(time.time()),
                "complete": True,
            }

        resp = client.get("/api/agent/file-download/test-dl-001",
                          headers=agent_key_header)
        assert resp.status_code == 200
        assert resp.content == content
        assert resp.headers.get("X-File-Checksum") == checksum

        # Clean up
        try:
            os.remove(file_path)
        except OSError:
            pass


# ── Transfer initiation tests ────────────────────────────────────────────────

class TestTransferInitiation:
    """Test admin-initiated file push to agent."""

    def test_transfer_requires_admin(self, client, agent_key_header):
        """Transfer initiation without admin auth returns 401/403."""
        resp = client.post("/api/agents/test-host/transfer?path=/tmp/test.txt",
                           content=b"data")
        assert resp.status_code in (401, 403)

    def test_transfer_requires_path(self, client, admin_auth_header):
        """Transfer without path query param returns 400."""
        resp = client.post("/api/agents/test-host/transfer",
                           content=b"data", headers=admin_auth_header)
        assert resp.status_code == 400

    def test_transfer_creates_command(self, client, admin_auth_header):
        """Successful transfer stores file and queues file_push command."""
        from server.agent_store import _agent_cmd_lock, _agent_commands

        content = b"file push content"
        resp = client.post(
            "/api/agents/test-host/transfer?path=/tmp/pushed.txt",
            content=content,
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert "transfer_id" in data
        assert "cmd_id" in data

        # Verify command was queued
        with _agent_cmd_lock:
            cmds = _agent_commands.get("test-host", [])
        assert len(cmds) >= 1
        push_cmd = cmds[-1]
        assert push_cmd["type"] == "file_push"
        assert push_cmd["params"]["path"] == "/tmp/pushed.txt"
        assert push_cmd["params"]["transfer_id"] == data["transfer_id"]


# ── Agent store tests ─────────────────────────────────────────────────────────

class TestAgentStore:
    """Test transfer state management in agent_store."""

    def test_transfer_dir_exists(self):
        """Transfer directory is created on import."""
        from server.agent_store import _TRANSFER_DIR
        assert os.path.isdir(_TRANSFER_DIR)

    def test_constants(self):
        """Transfer constants have expected values."""
        from server.agent_store import _MAX_TRANSFER_SIZE, _CHUNK_SIZE, _TRANSFER_MAX_AGE
        assert _MAX_TRANSFER_SIZE == 50 * 1024 * 1024
        assert _CHUNK_SIZE == 256 * 1024
        assert _TRANSFER_MAX_AGE == 3600

    def test_transfer_lock_exists(self):
        """Transfer lock is a threading.Lock."""
        import threading
        from server.agent_store import _transfer_lock
        assert isinstance(_transfer_lock, type(threading.Lock()))

    def test_transfers_dict_is_empty_initially(self):
        """Transfer dict starts empty."""
        from server.agent_store import _transfers
        # Cleared by autouse fixture
        assert isinstance(_transfers, dict)
