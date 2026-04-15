# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Containers, processes, game servers, WoL."""
from __future__ import annotations

import json
import logging
import socket
import threading
import time

import psutil

from .util import _cache, _run, validate_service_name

logger = logging.getLogger("noba")

# ── Process history ───────────────────────────────────────────────────────────
_process_history: list[dict] = []
_process_history_lock = threading.Lock()
_PROCESS_HISTORY_MAX = 60  # Keep 60 snapshots (5 min at 5s intervals)


# ── Services ──────────────────────────────────────────────────────────────────
def get_service_status(svc: str) -> tuple[str, bool]:
    svc = svc.strip()
    if not validate_service_name(svc):
        return "invalid", False
    for scope, is_user in (["--user"], True), ([], False):
        cmd = ["systemctl"] + ([scope] if isinstance(scope, str) else scope) + [
            "show", "-p", "ActiveState,LoadState", svc
        ]
        out = _run(cmd, timeout=2)
        d = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        if d.get("LoadState") not in (None, "", "not-found"):
            state = d.get("ActiveState", "unknown")
            if state == "inactive" and svc.endswith(".service"):
                t = _run(
                    ["systemctl"] + ([scope] if isinstance(scope, str) else scope) + [
                        "show", "-p", "ActiveState",
                        svc.replace(".service", ".timer"),
                    ],
                    timeout=1,
                )
                if "ActiveState=active" in t:
                    return "timer-active", is_user
            return state, is_user
    return "not-found", False


# ── Containers ────────────────────────────────────────────────────────────────
def get_containers() -> list:
    for cmd in (
        ["podman", "ps", "-a", "--format", "json"],
        ["docker", "ps", "-a", "--format", "{{json .}}"],
    ):
        out = _run(cmd, timeout=4, cache_key=" ".join(cmd), cache_ttl=10)
        if not out:
            continue
        try:
            items = (
                json.loads(out)
                if out.lstrip().startswith("[")
                else [json.loads(line) for line in out.splitlines() if line.strip()]
            )
            res = []
            for c in items[:16]:
                name = c.get("Names", c.get("Name", "?"))
                if isinstance(name, list):
                    name = name[0] if name else "?"
                cid = (c.get("Id", c.get("ID", "")) or "")[:12]
                res.append({
                    "id":     cid,
                    "name":   name,
                    "image":  c.get("Image", c.get("Repository", "?")).split("/")[-1][:32],
                    "state":  ((c.get("State",  c.get("Status",  "?")) or "?").lower().split() or ["?"])[0],
                    "status": ((c.get("Status", c.get("State",   "?")) or "?").lower().split() or ["?"])[0],
                })
            return res
        except Exception:
            continue
    return []


def bust_container_cache() -> None:
    _cache.bust("ps")


# ── Docker updates ────────────────────────────────────────────────────────────
def check_docker_updates() -> list[dict]:
    """Check running containers for available image updates."""
    import hashlib
    results = []
    # Get running containers with their image digests
    out = _run(["docker", "ps", "--format", "{{.Names}}|{{.Image}}"], timeout=10, ignore_rc=True)
    if not out:
        return results
    for line in out.splitlines():
        if "|" not in line:
            continue
        name, image = line.split("|", 1)
        try:
            # Get local digest
            local = _run(["docker", "image", "inspect", image, "--format", "{{.Id}}"], timeout=5)
            # Try to get remote digest (without pulling)
            remote = _run(["docker", "manifest", "inspect", image, "--verbose"], timeout=15, ignore_rc=True)
            has_update = False
            if remote and local:
                # Simple heuristic: if manifest inspect succeeds and content differs
                remote_hash = hashlib.md5(remote.encode()).hexdigest()[:12]  # noqa: S324
                has_update = remote_hash not in local
            results.append({
                "name": name,
                "image": image,
                "has_update": has_update,
            })
        except Exception:
            results.append({"name": name, "image": image, "has_update": False})
    return results


# ── Wake-on-LAN ─────────────────────────────────────────────────────────────
def send_wol(mac: str) -> bool:
    mac = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(mac) != 12:
        return False
    try:
        mac_bytes = bytes.fromhex(mac)
        magic = b"\xff" * 6 + mac_bytes * 16
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(magic, ("<broadcast>", 9))
        return True
    except Exception:
        return False


# ── Process history ───────────────────────────────────────────────────────────
def snapshot_top_processes() -> dict:
    """Capture current top CPU and memory consumers and store in rolling history."""
    try:
        procs = [
            (p.info["name"] or "", p.info["cpu_percent"] or 0.0, p.info["memory_percent"] or 0.0, p.info.get("pid", 0))
            for p in psutil.process_iter(["name", "cpu_percent", "memory_percent", "pid"])
        ]
        top_cpu = sorted(procs, key=lambda x: x[1], reverse=True)[:5]
        top_mem = sorted(procs, key=lambda x: x[2], reverse=True)[:5]
        snapshot = {
            "time": int(time.time()),
            "cpu": [{"name": p[0][:20], "pid": p[3], "val": round(p[1], 1)} for p in top_cpu],
            "mem": [{"name": p[0][:20], "pid": p[3], "val": round(p[2], 1)} for p in top_mem],
        }
        with _process_history_lock:
            _process_history.append(snapshot)
            if len(_process_history) > _PROCESS_HISTORY_MAX:
                _process_history.pop(0)
        return snapshot
    except Exception:
        return {}


def get_process_history() -> list[dict]:
    """Return the rolling process history."""
    with _process_history_lock:
        return list(_process_history)


# ── Game server probe ────────────────────────────────────────────────────────
def probe_game_server(host: str, port: int) -> dict:
    try:
        t0 = time.time()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(3)
            s.connect((host, port))
        ms = round((time.time() - t0) * 1000)
        return {"host": host, "port": port, "status": "online", "ms": ms}
    except Exception:
        return {"host": host, "port": port, "status": "offline", "ms": 0}


def query_source_server(host: str, port: int) -> dict:
    """Query a Valve Source engine game server using A2S_INFO protocol."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(3)
            # A2S_INFO request: 4 bytes header (0xFFFFFFFF) + 'T' + "Source Engine Query\0"
            request = b'\xff\xff\xff\xff\x54Source Engine Query\x00'
            s.sendto(request, (host, port))
            data, _ = s.recvfrom(4096)
            if len(data) < 6:
                return {"host": host, "port": port, "status": "offline"}
            # Parse response (skip 4-byte header + 1 byte type)
            pos = 5
            # Protocol version
            pos += 1
            # Server name (null-terminated string)
            end = data.index(b'\x00', pos)
            name = data[pos:end].decode('utf-8', errors='replace')
            pos = end + 1
            # Map (null-terminated)
            end = data.index(b'\x00', pos)
            map_name = data[pos:end].decode('utf-8', errors='replace')
            pos = end + 1
            # Game dir (skip)
            end = data.index(b'\x00', pos)
            pos = end + 1
            # Game name (skip)
            end = data.index(b'\x00', pos)
            pos = end + 1
            # Players, max players
            players = data[pos]
            max_players = data[pos + 1]
            return {
                "host": host, "port": port, "status": "online",
                "name": name, "map": map_name,
                "players": players, "max_players": max_players,
            }
    except Exception:
        return {"host": host, "port": port, "status": "offline"}
