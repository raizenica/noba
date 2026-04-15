# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Wake-on-LAN Scheduler -- Scheduled WoL with power-on verification.

Send Wake-on-LAN magic packets on a schedule and optionally verify
that the target host came online by pinging it.
"""
from __future__ import annotations

import json
import socket
import subprocess
import threading
import time
from pathlib import Path

PLUGIN_ID = "wol_scheduler"
PLUGIN_NAME = "WoL Scheduler"
PLUGIN_VERSION = "1.0.0"
PLUGIN_ICON = "fa-power-off"
PLUGIN_DESCRIPTION = "Scheduled Wake-on-LAN with power-on verification and status tracking."
PLUGIN_INTERVAL = 10

PLUGIN_CONFIG_SCHEMA = {
    "targets": {
        "type": "list",
        "label": "Targets (MAC|IP|Name, one per line)",
        "default": [],
    },
    "schedule_cron": {
        "type": "string",
        "label": "Schedule (HH:MM 24h format)",
        "default": "",
        "placeholder": "07:00",
    },
    "verify_ping": {
        "type": "boolean",
        "label": "Verify host online after wake",
        "default": True,
    },
    "verify_timeout": {
        "type": "number",
        "label": "Verification timeout (seconds)",
        "default": 120,
        "min": 30,
        "max": 600,
    },
    "broadcast_address": {
        "type": "string",
        "label": "Broadcast address",
        "default": "255.255.255.255",
    },
    "wol_port": {
        "type": "number",
        "label": "WoL UDP port",
        "default": 9,
        "min": 1,
        "max": 65535,
    },
}

_lock = threading.Lock()
_status: dict[str, dict] = {}
_last_scheduled: str = ""
_ctx = None

_STATUS_FILE = Path("~/.config/noba/plugins/config/wol_status.json").expanduser()


def _load_status() -> dict:
    try:
        if _STATUS_FILE.is_file():
            return json.loads(_STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_status() -> None:
    try:
        _STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATUS_FILE.write_text(json.dumps(_status, indent=1), encoding="utf-8")
    except Exception:
        pass


def _parse_target(target_str: str) -> dict:
    """Parse 'MAC|IP|Name' target string."""
    parts = [p.strip() for p in target_str.split("|")]
    result = {"mac": "", "ip": "", "name": ""}
    if len(parts) >= 1:
        result["mac"] = parts[0]
    if len(parts) >= 2:
        result["ip"] = parts[1]
    if len(parts) >= 3:
        result["name"] = parts[2]
    else:
        result["name"] = result["mac"]
    return result


def _send_wol(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> bool:
    """Send a Wake-on-LAN magic packet."""
    try:
        # Normalize MAC address
        mac_clean = mac.replace(":", "").replace("-", "").replace(".", "")
        if len(mac_clean) != 12:
            return False
        mac_bytes = bytes.fromhex(mac_clean)
        # Magic packet: 6x 0xFF + 16x MAC
        packet = b'\xff' * 6 + mac_bytes * 16
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(packet, (broadcast, port))
        return True
    except Exception:
        return False


def _ping_host(ip: str, timeout: int = 3) -> bool:
    """Ping a host to check if it's online."""
    if not ip:
        return False
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), ip],
            capture_output=True, timeout=timeout + 2,
        )
        return result.returncode == 0
    except Exception:
        return False


def _verify_target(target: dict, cfg: dict) -> None:
    """Wait for a target to come online after WoL."""
    ip = target["ip"]
    name = target["name"]
    timeout = int(cfg.get("verify_timeout", 120))
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _ping_host(ip):
            with _lock:
                _status[name] = {
                    "state": "online",
                    "woke_at": _status.get(name, {}).get("woke_at", time.time()),
                    "verified_at": time.time(),
                }
                _save_status()
            return
        time.sleep(5)
    with _lock:
        _status[name] = {
            "state": "timeout",
            "woke_at": _status.get(name, {}).get("woke_at", time.time()),
            "error": f"Did not respond within {timeout}s",
        }
        _save_status()


def wake_target(target_str: str, cfg: dict) -> str:
    """Wake a single target. Returns status message."""
    target = _parse_target(target_str)
    broadcast = cfg.get("broadcast_address", "255.255.255.255")
    port = int(cfg.get("wol_port", 9))

    ok = _send_wol(target["mac"], broadcast, port)
    if not ok:
        return f"Failed to send WoL to {target['mac']}"

    with _lock:
        _status[target["name"]] = {
            "state": "waking",
            "woke_at": time.time(),
        }

    if cfg.get("verify_ping", True) and target["ip"]:
        t = threading.Thread(
            target=_verify_target, args=(target, cfg),
            daemon=True, name=f"wol-verify-{target['name']}",
        )
        t.start()
    else:
        with _lock:
            _status[target["name"]]["state"] = "sent"

    return f"WoL sent to {target['name']} ({target['mac']})"


def _schedule_loop(cfg: dict) -> None:
    """Background loop that checks schedule and sends WoL."""
    global _last_scheduled  # noqa: PLW0603
    schedule = cfg.get("schedule_cron", "").strip()
    if not schedule:
        return
    targets = cfg.get("targets", [])
    if not targets:
        return

    while True:
        now = time.localtime()
        current_hm = f"{now.tm_hour:02d}:{now.tm_min:02d}"
        if current_hm == schedule and _last_scheduled != current_hm:
            _last_scheduled = current_hm
            for target_str in targets:
                if target_str:
                    wake_target(target_str, cfg)
        elif current_hm != schedule:
            _last_scheduled = ""
        time.sleep(30)


def register(ctx) -> None:
    """Start WoL scheduler."""
    global _ctx  # noqa: PLW0603
    _ctx = ctx
    cfg = ctx.get_config()

    # Load saved status
    with _lock:
        _status.update(_load_status())

    # Register manual wake route

    async def api_wol_wake(target: str):
        c = ctx.get_config()
        msg = wake_target(target, c)
        return {"status": "ok", "message": msg}

    ctx.add_route("/api/plugins/wol/wake", api_wol_wake, methods=["POST"])

    # Start schedule loop
    if cfg.get("schedule_cron"):
        t = threading.Thread(
            target=_schedule_loop, args=(cfg,),
            daemon=True, name="wol-scheduler",
        )
        t.start()


def collect() -> dict:
    """Return WoL status for all targets."""
    with _lock:
        cfg = _ctx.get_config() if _ctx else {}
        targets = cfg.get("targets", [])
        target_info = []
        for ts in targets:
            if not ts:
                continue
            parsed = _parse_target(ts)
            name = parsed["name"]
            status = _status.get(name, {"state": "unknown"})
            target_info.append({
                "name": name,
                "mac": parsed["mac"],
                "ip": parsed["ip"],
                **status,
            })
        return {
            "targets": target_info,
            "schedule": cfg.get("schedule_cron", ""),
        }


def render(data: dict) -> str:
    """Render dashboard card HTML."""
    targets = data.get("targets", [])
    schedule = data.get("schedule", "")

    if not targets:
        return '<div style="color:var(--text-muted);font-size:.8rem">No WoL targets configured.</div>'

    html = ""
    if schedule:
        html += f'<div style="font-size:.7rem;color:var(--text-dim);margin-bottom:.4rem">Schedule: {schedule}</div>'

    for t in targets:
        state = t.get("state", "unknown")
        color = {
            "online": "var(--success)",
            "waking": "var(--warning)",
            "sent": "var(--accent)",
            "timeout": "var(--danger)",
        }.get(state, "var(--text-muted)")
        icon = {
            "online": "fa-check-circle",
            "waking": "fa-spinner fa-spin",
            "sent": "fa-paper-plane",
            "timeout": "fa-exclamation-triangle",
        }.get(state, "fa-question-circle")
        html += (
            f'<div style="display:flex;align-items:center;gap:.5rem;padding:3px 0;font-size:.78rem">'
            f'<i class="fas {icon}" style="color:{color};width:1rem;text-align:center"></i>'
            f'<span style="flex:1">{t["name"]}</span>'
            f'<span style="font-size:.65rem;color:{color}">{state}</span>'
            f'</div>'
        )
    return html


def teardown() -> None:
    pass
