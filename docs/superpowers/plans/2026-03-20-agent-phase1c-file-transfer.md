# Agent Enhancement Phase 1c: File Operations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add file transfer between server and agents — pull files from agents (file_transfer) and push files to agents (file_push). Uses chunked HTTP with SHA256 verification. Max 50MB per transfer, 256KB chunks.

**Architecture:** File transfers are triggered by commands but use dedicated HTTP endpoints for the actual data. Agent uploads chunks to `/api/agent/file-upload`, downloads from `/api/agent/file-download/{id}`. Server stores transfers in a temp directory with cleanup after 1 hour. Both directions are SHA256-verified.

**Tech Stack:** Python stdlib (agent), FastAPI + tempfile (server), existing auth patterns

**Spec:** `docs/superpowers/specs/2026-03-20-agent-enhancement-design.md` — Phase 1c section

---

## File Structure

### Server-side:
- Modify: `share/noba-web/server/agent_store.py` — add transfer state tracking
- Modify: `share/noba-web/server/routers/system.py` — add file-upload, file-download, transfer-initiate endpoints
- Modify: `share/noba-web/server/app.py` — cleanup task for orphaned transfers

### Agent-side:
- Modify: `share/noba-agent/agent.py` — add `_cmd_file_transfer` (upload) and `_cmd_file_push` (download) handlers

### Tests:
- Create: `tests/test_agent_file_transfer.py` — upload, download, checksum, cleanup

---

### Task 1: Add transfer state management

**Files:**
- Modify: `share/noba-web/server/agent_store.py`

- [ ] **Step 1: Add transfer stores**

```python
import os
import tempfile

# File transfer state
_TRANSFER_DIR = os.path.join(tempfile.gettempdir(), "noba-transfers")
_MAX_TRANSFER_SIZE = 50 * 1024 * 1024  # 50MB
_CHUNK_SIZE = 256 * 1024  # 256KB
_TRANSFER_MAX_AGE = 3600  # 1 hour cleanup

# Active transfers: transfer_id -> {hostname, filename, checksum, total_chunks,
#                                    received_chunks: set, created_at, direction}
_transfers: dict[str, dict] = {}
_transfer_lock = threading.Lock()
```

- [ ] **Step 2: Ensure transfer directory exists on import**

```python
os.makedirs(_TRANSFER_DIR, exist_ok=True)
```

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/server/agent_store.py
git commit -m "feat(agent): add file transfer state management"
```

---

### Task 2: File upload endpoint (Agent → Server)

**Files:**
- Modify: `share/noba-web/server/routers/system.py`

- [ ] **Step 1: Add the file-upload endpoint**

This receives chunked uploads from agents. Each chunk is a separate POST with headers identifying the transfer.

```python
from .agent_store import (
    _transfers, _transfer_lock, _TRANSFER_DIR,
    _MAX_TRANSFER_SIZE, _CHUNK_SIZE, _TRANSFER_MAX_AGE,
)

@router.post("/api/agent/file-upload")
async def api_agent_file_upload(request: Request):
    """Receive a file chunk from an agent."""
    # Auth
    key = request.headers.get("X-Agent-Key", "")
    if not _validate_agent_key(key):
        raise HTTPException(401, "Invalid agent key")

    transfer_id = request.headers.get("X-Transfer-Id", "")
    chunk_index = int(request.headers.get("X-Chunk-Index", "-1"))
    total_chunks = int(request.headers.get("X-Total-Chunks", "0"))
    filename = request.headers.get("X-Filename", "unknown")
    checksum = request.headers.get("X-File-Checksum", "")  # sha256:hex
    hostname = request.headers.get("X-Agent-Hostname", "unknown")

    if not transfer_id or chunk_index < 0 or total_chunks <= 0:
        raise HTTPException(400, "Missing transfer headers")

    body = await request.body()
    if len(body) > _CHUNK_SIZE + 1024:  # Allow small overhead
        raise HTTPException(413, "Chunk too large")

    # Initialize transfer on first chunk
    with _transfer_lock:
        if transfer_id not in _transfers:
            _transfers[transfer_id] = {
                "hostname": hostname,
                "filename": filename,
                "checksum": checksum,
                "total_chunks": total_chunks,
                "received_chunks": set(),
                "created_at": int(time.time()),
                "direction": "upload",  # agent -> server
            }

    # Write chunk to disk
    chunk_path = os.path.join(_TRANSFER_DIR, f"{transfer_id}.chunk{chunk_index}")
    with open(chunk_path, "wb") as f:
        f.write(body)

    with _transfer_lock:
        _transfers[transfer_id]["received_chunks"].add(chunk_index)
        received = len(_transfers[transfer_id]["received_chunks"])
        complete = received == total_chunks

    result = {"status": "ok", "received": chunk_index, "progress": f"{received}/{total_chunks}"}

    # If all chunks received, reassemble and verify
    if complete:
        final_path = os.path.join(_TRANSFER_DIR, f"{transfer_id}_{filename}")
        with open(final_path, "wb") as out:
            for i in range(total_chunks):
                cp = os.path.join(_TRANSFER_DIR, f"{transfer_id}.chunk{i}")
                with open(cp, "rb") as chunk_f:
                    out.write(chunk_f.read())
                os.remove(cp)  # Clean up chunk

        # Verify checksum
        if checksum.startswith("sha256:"):
            expected = checksum.split(":", 1)[1]
            import hashlib
            h = hashlib.sha256()
            with open(final_path, "rb") as f:
                while True:
                    block = f.read(65536)
                    if not block:
                        break
                    h.update(block)
            actual = h.hexdigest()
            if actual != expected:
                os.remove(final_path)
                with _transfer_lock:
                    _transfers.pop(transfer_id, None)
                raise HTTPException(422, f"Checksum mismatch: expected {expected}, got {actual}")

        with _transfer_lock:
            _transfers[transfer_id]["final_path"] = final_path
            _transfers[transfer_id]["complete"] = True

        result["complete"] = True
        result["path"] = final_path

    return result
```

- [ ] **Step 2: Run lint**

```bash
ruff check share/noba-web/server/routers/system.py --fix
```

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/server/routers/system.py
git commit -m "feat(agent): add /api/agent/file-upload endpoint"
```

---

### Task 3: File download endpoint (Server → Agent)

**Files:**
- Modify: `share/noba-web/server/routers/system.py`

- [ ] **Step 1: Add file-download endpoint**

```python
from starlette.responses import FileResponse

@router.get("/api/agent/file-download/{transfer_id}")
async def api_agent_file_download(transfer_id: str, request: Request):
    """Serve a file to an agent for file_push command."""
    key = request.headers.get("X-Agent-Key", "")
    if not _validate_agent_key(key):
        raise HTTPException(401, "Invalid agent key")

    with _transfer_lock:
        transfer = _transfers.get(transfer_id)
    if not transfer:
        raise HTTPException(404, "Transfer not found")
    if transfer.get("direction") != "download":
        raise HTTPException(400, "Not a download transfer")

    file_path = transfer.get("final_path", "")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(404, "File not found")

    return FileResponse(
        file_path,
        filename=transfer.get("filename", "download"),
        media_type="application/octet-stream",
        headers={"X-File-Checksum": transfer.get("checksum", "")},
    )
```

- [ ] **Step 2: Add transfer initiation endpoint (admin uploads for push)**

```python
@router.post("/api/agents/{hostname}/transfer")
async def api_agent_transfer(hostname: str, request: Request, auth=Depends(_require_admin)):
    """Initiate a file push to an agent. Admin uploads the file first."""
    import secrets

    username, _ = auth
    ip = _client_ip(request)

    # Get destination path from query param
    dest_path = request.query_params.get("path", "")
    if not dest_path:
        raise HTTPException(400, "Destination path required (?path=...)")

    body = await request.body()
    if len(body) > _MAX_TRANSFER_SIZE:
        raise HTTPException(413, f"File too large (max {_MAX_TRANSFER_SIZE // 1024 // 1024}MB)")

    # Compute checksum
    import hashlib
    checksum = f"sha256:{hashlib.sha256(body).hexdigest()}"

    # Store file
    transfer_id = secrets.token_hex(16)
    filename = os.path.basename(dest_path) or "file"
    file_path = os.path.join(_TRANSFER_DIR, f"{transfer_id}_{filename}")
    with open(file_path, "wb") as f:
        f.write(body)

    with _transfer_lock:
        _transfers[transfer_id] = {
            "hostname": hostname,
            "filename": filename,
            "checksum": checksum,
            "final_path": file_path,
            "created_at": int(time.time()),
            "direction": "download",  # server -> agent
            "dest_path": dest_path,
            "complete": True,
        }

    # Queue file_push command for the agent
    cmd_id = secrets.token_hex(8)
    cmd = {
        "id": cmd_id,
        "type": "file_push",
        "params": {"path": dest_path, "transfer_id": transfer_id},
        "queued_by": username,
        "queued_at": int(time.time()),
    }

    # Try WebSocket first, fall back to queue
    delivered = False
    with _agent_ws_lock:
        ws = _agent_websockets.get(hostname)
    if ws:
        try:
            await ws.send_json({"type": "command", "cmd": "file_push", **cmd})
            delivered = True
        except Exception:
            pass
    if not delivered:
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)

    db.audit_log("agent_file_push", username,
                 f"host={hostname} path={dest_path} id={transfer_id}", ip)
    return {"status": "queued", "transfer_id": transfer_id, "cmd_id": cmd_id}
```

- [ ] **Step 3: Commit**

```bash
git add share/noba-web/server/routers/system.py
git commit -m "feat(agent): add file-download + transfer-initiate endpoints"
```

---

### Task 4: Agent file_transfer handler (upload to server)

**Files:**
- Modify: `share/noba-agent/agent.py`

- [ ] **Step 1: Implement `_cmd_file_transfer`**

```python
def _cmd_file_transfer(params: dict, ctx: dict) -> dict:
    """Upload a file from agent to server in chunks."""
    path = params.get("path", "")
    if not path:
        return {"status": "error", "error": "No path provided"}
    err = _safe_path(path)
    if err:
        return {"status": "error", "error": err}
    if not os.path.isfile(path):
        return {"status": "error", "error": f"Not a file: {path}"}

    file_size = os.path.getsize(path)
    max_size = 50 * 1024 * 1024  # 50MB
    if file_size > max_size:
        return {"status": "error", "error": f"File too large: {file_size} > {max_size}"}

    # Compute SHA256
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(65536)
            if not block:
                break
            h.update(block)
    checksum = f"sha256:{h.hexdigest()}"

    # Chunk and upload
    import secrets as _secrets
    chunk_size = 256 * 1024
    total_chunks = (file_size + chunk_size - 1) // chunk_size or 1
    transfer_id = _secrets.token_hex(16)
    server = ctx.get("server", "")
    api_key = ctx.get("api_key", "")
    url = f"{server.rstrip('/')}/api/agent/file-upload"
    hostname = socket.gethostname()

    errors = []
    for i in range(total_chunks):
        with open(path, "rb") as f:
            f.seek(i * chunk_size)
            chunk = f.read(chunk_size)

        headers = {
            "Content-Type": "application/octet-stream",
            "X-Agent-Key": api_key,
            "X-Transfer-Id": transfer_id,
            "X-Chunk-Index": str(i),
            "X-Total-Chunks": str(total_chunks),
            "X-Filename": os.path.basename(path),
            "X-File-Checksum": checksum,
            "X-Agent-Hostname": hostname,
        }
        req = urllib.request.Request(url, data=chunk, headers=headers, method="POST")

        retries = 0
        while retries < 3:
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    if resp.status == 200:
                        break
                    errors.append(f"Chunk {i}: HTTP {resp.status}")
            except Exception as e:
                errors.append(f"Chunk {i} attempt {retries}: {e}")
            retries += 1

        if retries >= 3:
            return {"status": "error", "error": f"Failed to upload chunk {i}: {errors[-1]}"}

    return {
        "status": "ok",
        "transfer_id": transfer_id,
        "path": path,
        "size": file_size,
        "chunks": total_chunks,
        "checksum": checksum,
    }
```

- [ ] **Step 2: Register handler**

Add to the `handlers` dict in `execute_commands()`:
```python
"file_transfer": _cmd_file_transfer,
```

- [ ] **Step 3: Commit**

```bash
git add share/noba-agent/agent.py
git commit -m "feat(agent): implement file_transfer (upload to server)"
```

---

### Task 5: Agent file_push handler (download from server)

**Files:**
- Modify: `share/noba-agent/agent.py`

- [ ] **Step 1: Implement `_cmd_file_push`**

```python
def _cmd_file_push(params: dict, ctx: dict) -> dict:
    """Download a file from server and write to destination path."""
    dest_path = params.get("path", "")
    transfer_id = params.get("transfer_id", "")
    if not dest_path:
        return {"status": "error", "error": "No destination path provided"}
    if not transfer_id:
        return {"status": "error", "error": "No transfer_id provided"}
    err = _safe_path(dest_path)
    if err:
        return {"status": "error", "error": err}

    server = ctx.get("server", "")
    api_key = ctx.get("api_key", "")
    url = f"{server.rstrip('/')}/api/agent/file-download/{transfer_id}"

    req = urllib.request.Request(
        url,
        headers={"X-Agent-Key": api_key},
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                return {"status": "error", "error": f"HTTP {resp.status}"}

            expected_checksum = resp.headers.get("X-File-Checksum", "")
            data = resp.read()

            # Verify checksum
            if expected_checksum.startswith("sha256:"):
                actual = hashlib.sha256(data).hexdigest()
                expected = expected_checksum.split(":", 1)[1]
                if actual != expected:
                    return {"status": "error", "error": f"Checksum mismatch: {actual} != {expected}"}

            # Backup existing file
            if os.path.exists(dest_path):
                try:
                    os.makedirs(_BACKUP_DIR, exist_ok=True)
                    import shutil
                    bname = os.path.basename(dest_path) + f".{int(time.time())}.bak"
                    shutil.copy2(dest_path, os.path.join(_BACKUP_DIR, bname))
                except Exception:
                    pass

            # Write file
            parent = os.path.dirname(dest_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(dest_path, "wb") as f:
                f.write(data)

            return {
                "status": "ok",
                "path": dest_path,
                "size": len(data),
                "checksum": expected_checksum,
            }
    except Exception as e:
        return {"status": "error", "error": str(e)}
```

- [ ] **Step 2: Register handler**

```python
"file_push": _cmd_file_push,
```

- [ ] **Step 3: Commit**

```bash
git add share/noba-agent/agent.py
git commit -m "feat(agent): implement file_push (download from server)"
```

---

### Task 6: Transfer cleanup

**Files:**
- Modify: `share/noba-web/server/app.py`

- [ ] **Step 1: Add background cleanup task**

In the lifespan startup, add a background task that cleans up old transfers every 15 minutes:

```python
import asyncio

async def _cleanup_transfers():
    """Remove orphaned transfers older than 1 hour."""
    while True:
        await asyncio.sleep(900)  # 15 minutes
        now = int(time.time())
        with _transfer_lock:
            expired = [tid for tid, t in _transfers.items()
                       if now - t.get("created_at", 0) > _TRANSFER_MAX_AGE]
            for tid in expired:
                transfer = _transfers.pop(tid)
                # Clean up files
                final = transfer.get("final_path", "")
                if final and os.path.exists(final):
                    try:
                        os.remove(final)
                    except OSError:
                        pass
                # Clean up orphaned chunks
                for f in os.listdir(_TRANSFER_DIR):
                    if f.startswith(tid):
                        try:
                            os.remove(os.path.join(_TRANSFER_DIR, f))
                        except OSError:
                            pass
        if expired:
            print(f"[cleanup] Removed {len(expired)} expired transfer(s)")
```

Start it in the lifespan:
```python
asyncio.create_task(_cleanup_transfers())
```

- [ ] **Step 2: Commit**

```bash
git add share/noba-web/server/app.py
git commit -m "feat(agent): add transfer cleanup background task"
```

---

### Task 7: Tests

**Files:**
- Create: `tests/test_agent_file_transfer.py`

- [ ] **Step 1: Write transfer tests**

```python
"""Tests for agent file transfer protocol."""
from __future__ import annotations

import hashlib
import os
import tempfile

import pytest


class TestFileTransferUpload:
    """Test agent -> server file upload."""

    def test_single_chunk_upload(self, client, agent_key_header):
        """Small file uploads in one chunk."""
        # Create test content
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

    def test_multi_chunk_upload(self, client, agent_key_header):
        """File uploaded in multiple chunks reassembles correctly."""
        # Create content larger than one chunk
        content = os.urandom(1024)  # 1KB test data
        checksum = f"sha256:{hashlib.sha256(content).hexdigest()}"
        chunk_size = 512
        chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]

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
            resp = client.post("/api/agent/file-upload", content=chunk, headers=headers)
            assert resp.status_code == 200

    def test_checksum_mismatch_rejected(self, client, agent_key_header):
        """Upload with wrong checksum is rejected."""
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


class TestFileTransferDownload:
    """Test server -> agent file download."""

    def test_download_nonexistent(self, client, agent_key_header):
        """Download of non-existent transfer returns 404."""
        resp = client.get("/api/agent/file-download/nonexistent",
                          headers=agent_key_header)
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_agent_file_transfer.py -v
pytest tests/ -v  # Full suite
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_file_transfer.py
git commit -m "test(agent): add file transfer upload/download tests"
```
