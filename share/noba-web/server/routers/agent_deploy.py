"""Noba – Agent deployment, file transfer, uninstall, and update endpoints."""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import secrets
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse

from ..agent_store import (
    _agent_cmd_lock, _agent_cmd_results, _agent_commands,
    _agent_data, _agent_data_lock,
    _agent_websockets, _agent_ws_lock,
    _CHUNK_SIZE, _MAX_TRANSFER_SIZE, _TRANSFER_DIR,
    _transfer_lock, _transfers,
)
from ..constants import (
    DEPLOY_ERROR_TRUNCATE,
    DEPLOY_OUTPUT_TRUNCATE,
)
from ..deps import (
    _client_ip, _read_body,
    _require_admin, _safe_int, db,
    handle_errors,
)
from . import agents as _agents_mod
from .agents import _validate_agent_key

logger = __import__("logging").getLogger("noba")

_WEB_DIR = Path(__file__).resolve().parent.parent.parent  # share/noba-web/

router = APIRouter(tags=["agents"])


# ── Uninstall / Delete endpoints ─────────────────────────────────────────────

@router.post("/api/agents/{hostname}/uninstall")
@handle_errors
async def api_agent_uninstall(hostname: str, request: Request, auth=Depends(_require_admin)):
    """Queue uninstall command and mark agent for removal."""
    username, _ = auth
    ip = _client_ip(request)
    cmd_id = secrets.token_hex(8)
    cmd = {"id": cmd_id, "type": "uninstall_agent", "params": {"confirm": True},
           "queued_by": username, "queued_at": int(time.time())}
    with _agent_cmd_lock:
        _agent_commands.setdefault(hostname, []).append(cmd)
    db.audit_log("agent_uninstall", username, f"host={hostname} id={cmd_id}", ip)
    return {"status": "queued", "id": cmd_id}


@router.delete("/api/agents/{hostname}")
@handle_errors
def api_agent_delete(hostname: str, request: Request, auth=Depends(_require_admin)):
    """Remove an agent from the dashboard (DB + in-memory). Admin only."""
    username, _ = auth
    ip = _client_ip(request)
    with _agent_data_lock:
        _agent_data.pop(hostname, None)
    with _agent_cmd_lock:
        _agent_commands.pop(hostname, None)
        _agent_cmd_results.pop(hostname, None)
    with _agent_ws_lock:
        _agent_websockets.pop(hostname, None)
    db.delete_agent(hostname)
    db.audit_log("agent_delete", username, f"host={hostname}", ip)
    return {"status": "ok"}


# ── Update / Install script endpoints ────────────────────────────────────────

@router.get("/api/agent/update")
@handle_errors
def api_agent_update(request: Request) -> FileResponse:
    """Serve the latest agent.pyz for self-update. Auth via X-Agent-Key."""
    key = request.headers.get("X-Agent-Key", "")
    if not key:
        raise HTTPException(401, "Missing X-Agent-Key")
    cfg = _agents_mod.read_yaml_settings()
    valid_keys = [k.strip() for k in cfg.get("agentKeys", "").split(",") if k.strip()]
    if not valid_keys or key not in valid_keys:
        raise HTTPException(403, "Invalid agent key")
    agent_path = _WEB_DIR.parent / "noba-agent.pyz"
    if not agent_path.exists():
        raise HTTPException(404, "Agent file not found")
    return FileResponse(agent_path, media_type="application/zip")


@router.get("/api/agent/install-script")
@handle_errors
def api_agent_install_script(request: Request) -> Response:
    """Generate a one-liner install script. Auth via X-Agent-Key."""
    key = request.headers.get("X-Agent-Key", "") or request.query_params.get("key", "")
    if not key:
        raise HTTPException(401, "Missing agent key")
    cfg = _agents_mod.read_yaml_settings()
    valid_keys = [k.strip() for k in cfg.get("agentKeys", "").split(",") if k.strip()]
    if not valid_keys or key not in valid_keys:
        raise HTTPException(403, "Invalid agent key")
    host = request.headers.get("X-Forwarded-Host", request.headers.get("Host", "localhost:8080"))
    scheme = request.headers.get("X-Forwarded-Proto", "http")
    server_url = f"{scheme}://{host}"
    script = f"""#!/bin/bash
# NOBA Agent -- Auto-installer
set -e
INSTALL_DIR="/opt/noba-agent"
SERVER="{server_url}"
KEY="{key}"
HOSTNAME="$(hostname)"

echo "[noba] Installing agent on $HOSTNAME..."
sudo mkdir -p "$INSTALL_DIR"
curl -sf "$SERVER/api/agent/update" -H "X-Agent-Key: $KEY" -o "$INSTALL_DIR/agent.pyz"
sudo chmod +x "$INSTALL_DIR/agent.pyz"

# Install psutil if possible
command -v apt-get &>/dev/null && sudo apt-get install -y python3-psutil 2>/dev/null || true
command -v dnf &>/dev/null && sudo dnf install -y python3-psutil 2>/dev/null || true

# Write config
sudo tee /etc/noba-agent.yaml > /dev/null <<EOF
server: $SERVER
api_key: $KEY
interval: 30
hostname: $HOSTNAME
EOF

# Install systemd service
sudo tee /etc/systemd/system/noba-agent.service > /dev/null <<EOF
[Unit]
Description=NOBA Agent
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
ExecStart=$(command -v python3) $INSTALL_DIR/agent.pyz --config /etc/noba-agent.yaml
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now noba-agent
echo "[noba] Agent installed and running on $HOSTNAME"
"""
    return Response(content=script, media_type="text/x-shellscript",
                    headers={"Content-Disposition": "inline"})


# ── Deploy endpoint ──────────────────────────────────────────────────────────

@router.post("/api/agents/deploy")
@handle_errors
async def api_agent_deploy(request: Request, auth=Depends(_require_admin)):
    """Remote deploy: SSH into a node and install the agent."""
    username, _ = auth
    ip = _client_ip(request)
    body = await _read_body(request)
    target_host = body.get("host", "")
    ssh_user = body.get("ssh_user", "")
    ssh_pass = body.get("ssh_pass", "")
    target_port = _safe_int(body.get("ssh_port", 22), 22)
    if target_port < 1 or target_port > 65535:
        target_port = 22

    if not target_host or not ssh_user:
        raise HTTPException(400, "host and ssh_user are required")

    if not re.match(r'^[a-zA-Z0-9._:-]+$', target_host):
        raise HTTPException(400, "Invalid hostname")
    if not re.match(r'^[a-zA-Z0-9._-]+$', ssh_user) or len(ssh_user) > 64:
        raise HTTPException(400, "Invalid ssh_user")

    cfg = _agents_mod.read_yaml_settings()
    agent_keys = cfg.get("agentKeys", "")
    if not agent_keys:
        raise HTTPException(400, "No agent keys configured. Set agentKeys in settings first.")
    agent_key = agent_keys.split(",")[0].strip()

    # Validate server_url from config rather than trusting the Host header
    server_url = cfg.get("serverUrl", "").strip()
    if not server_url:
        host_header = request.headers.get("Host", "localhost:8080")
        server_url = f"http://{host_header}"
    if not re.match(r'^https?://[a-zA-Z0-9._:/-]+$', server_url):
        raise HTTPException(400, "Invalid serverUrl configuration")

    agent_path = _WEB_DIR.parent / "noba-agent.pyz"
    if not agent_path.exists():
        raise HTTPException(500, "Agent file not found on server")

    import shutil
    if ssh_pass and not shutil.which("sshpass"):
        raise HTTPException(400, "sshpass not installed on server. Use the install script method instead.")

    target = f"{ssh_user}@{target_host}"
    env = {**os.environ, "SSHPASS": ssh_pass} if ssh_pass else os.environ

    # Build list-form commands (no shell=True) to prevent shell injection
    _ssh_common = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]
    if ssh_pass:
        scp_cmd = ["sshpass", "-e", "scp", "-P", str(target_port)] + _ssh_common
        ssh_cmd = ["sshpass", "-e", "ssh", "-p", str(target_port)] + _ssh_common
    else:
        scp_cmd = ["scp", "-P", str(target_port)] + _ssh_common
        ssh_cmd = ["ssh", "-p", str(target_port)] + _ssh_common

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            scp_cmd + [str(agent_path), f"{target}:/tmp/noba-agent.pyz"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if result.returncode != 0:
            return {"status": "error", "step": "copy", "error": result.stderr[:DEPLOY_ERROR_TRUNCATE]}

        install_cmds = f"""
sudo mkdir -p /opt/noba-agent
sudo cp /tmp/noba-agent.pyz /opt/noba-agent/agent.pyz
sudo chmod +x /opt/noba-agent/agent.pyz
command -v apt-get >/dev/null && sudo apt-get install -y python3-psutil 2>/dev/null || true
command -v dnf >/dev/null && sudo dnf install -y python3-psutil 2>/dev/null || true
sudo tee /etc/noba-agent.yaml > /dev/null <<AGENTCFG
server: {server_url}
api_key: {agent_key}
interval: 30
hostname: $(hostname)
AGENTCFG
sudo tee /etc/systemd/system/noba-agent.service > /dev/null <<SVC
[Unit]
Description=NOBA Agent
After=network-online.target
[Service]
Type=simple
ExecStart=$(command -v python3 || echo /usr/bin/python3) /opt/noba-agent/agent.pyz --config /etc/noba-agent.yaml
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
SVC
sudo systemctl daemon-reload
sudo systemctl enable --now noba-agent 2>&1
systemctl is-active noba-agent
"""
        result = await asyncio.to_thread(
            subprocess.run,
            ssh_cmd + [target, "bash", "-s"],
            input=install_cmds, capture_output=True, text=True,
            timeout=60, env=env,
        )
        success = "active" in result.stdout
        db.audit_log("agent_deploy", username, f"host={target_host} user={ssh_user} ok={success}", ip)
        return {
            "status": "ok" if success else "error",
            "host": target_host,
            "output": result.stdout[:DEPLOY_OUTPUT_TRUNCATE],
            "error": result.stderr[:DEPLOY_ERROR_TRUNCATE] if not success else "",
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "SSH connection timed out"}
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── File transfer endpoints (Phase 1c) ──────────────────────────────────────

@router.post("/api/agent/file-upload")
@handle_errors
async def api_agent_file_upload(request: Request):
    """Receive a file chunk from an agent."""
    key = request.headers.get("X-Agent-Key", "")
    if not _validate_agent_key(key):
        raise HTTPException(401, "Invalid agent key")

    transfer_id = request.headers.get("X-Transfer-Id", "")
    chunk_index_raw = request.headers.get("X-Chunk-Index", "-1")
    total_chunks_raw = request.headers.get("X-Total-Chunks", "0")
    filename = os.path.basename(request.headers.get("X-Filename", "unknown"))
    if not filename or filename.startswith("."):
        filename = "unknown"
    checksum = request.headers.get("X-File-Checksum", "")
    hostname = request.headers.get("X-Agent-Hostname", "unknown")

    try:
        chunk_index = int(chunk_index_raw)
        total_chunks = int(total_chunks_raw)
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid chunk headers")

    if not transfer_id or chunk_index < 0 or total_chunks <= 0:
        raise HTTPException(400, "Missing transfer headers")

    body = await request.body()
    if len(body) > _CHUNK_SIZE + 1024:
        raise HTTPException(413, "Chunk too large")

    # Initialize transfer on first chunk
    async with _transfer_lock:
        if transfer_id not in _transfers:
            _transfers[transfer_id] = {
                "hostname": hostname,
                "filename": filename,
                "checksum": checksum,
                "total_chunks": total_chunks,
                "received_chunks": set(),
                "created_at": int(time.time()),
                "direction": "upload",
            }

    # Write chunk to disk
    chunk_path = os.path.join(_TRANSFER_DIR, f"{transfer_id}.chunk{chunk_index}")
    with open(chunk_path, "wb") as f:
        f.write(body)

    async with _transfer_lock:
        _transfers[transfer_id]["received_chunks"].add(chunk_index)
        received = len(_transfers[transfer_id]["received_chunks"])
        complete = received == total_chunks

    result: dict = {"status": "ok", "received": chunk_index, "progress": f"{received}/{total_chunks}"}

    # If all chunks received, reassemble and verify
    if complete:
        final_path = os.path.join(_TRANSFER_DIR, f"{transfer_id}_{filename}")
        with open(final_path, "wb") as out:
            for i in range(total_chunks):
                cp = os.path.join(_TRANSFER_DIR, f"{transfer_id}.chunk{i}")
                with open(cp, "rb") as chunk_f:
                    out.write(chunk_f.read())
                os.remove(cp)

        # Verify checksum
        if checksum.startswith("sha256:"):
            expected = checksum.split(":", 1)[1]
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
                async with _transfer_lock:
                    _transfers.pop(transfer_id, None)
                raise HTTPException(422, f"Checksum mismatch: expected {expected}, got {actual}")

        async with _transfer_lock:
            _transfers[transfer_id]["final_path"] = final_path
            _transfers[transfer_id]["complete"] = True

        result["complete"] = True
        result["path"] = final_path

    return result


@router.get("/api/agent/file-download/{transfer_id}")
@handle_errors
async def api_agent_file_download(transfer_id: str, request: Request):
    """Serve a file to an agent for file_push command."""
    key = request.headers.get("X-Agent-Key", "")
    if not _validate_agent_key(key):
        raise HTTPException(401, "Invalid agent key")

    async with _transfer_lock:
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


@router.post("/api/agents/{hostname}/transfer")
@handle_errors
async def api_agent_transfer(hostname: str, request: Request, auth=Depends(_require_admin)):
    """Initiate a file push to an agent. Admin uploads the file first."""
    username, _ = auth
    ip = _client_ip(request)

    dest_path = request.query_params.get("path", "")
    if not dest_path:
        raise HTTPException(400, "Destination path required (?path=...)")

    body = await request.body()
    if len(body) > _MAX_TRANSFER_SIZE:
        raise HTTPException(413, f"File too large (max {_MAX_TRANSFER_SIZE // 1024 // 1024}MB)")

    checksum = f"sha256:{hashlib.sha256(body).hexdigest()}"

    transfer_id = secrets.token_hex(16)
    filename = os.path.basename(dest_path) or "file"
    file_path = os.path.join(_TRANSFER_DIR, f"{transfer_id}_{filename}")
    with open(file_path, "wb") as f:
        f.write(body)

    async with _transfer_lock:
        _transfers[transfer_id] = {
            "hostname": hostname,
            "filename": filename,
            "checksum": checksum,
            "final_path": file_path,
            "created_at": int(time.time()),
            "direction": "download",
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
        except HTTPException:
            raise
        except Exception:
            pass
    if not delivered:
        with _agent_cmd_lock:
            _agent_commands.setdefault(hostname, []).append(cmd)

    db.audit_log("agent_file_push", username,
                 f"host={hostname} path={dest_path} id={transfer_id}", ip)
    return {"status": "queued", "transfer_id": transfer_id, "cmd_id": cmd_id}
