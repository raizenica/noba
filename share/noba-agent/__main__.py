#!/usr/bin/env python3
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""NOBA Agent — Zero-dependency system telemetry collector.

Collects CPU, memory, disk, network, temperature, and top process metrics
and reports them to the NOBA Command Center via authenticated HTTP POST.

Works on any Linux system with Python 3.6+ and NO external dependencies.
Uses /proc and /sys directly. Optionally uses psutil if available for
cross-platform support (FreeBSD, macOS).

Usage:
    python3 agent.pyz --server http://noba:8080 --key YOUR_API_KEY
    python3 agent.pyz --config /etc/noba-agent.yaml
    python3 agent.pyz --dry-run     # Print metrics, don't send
    python3 agent.pyz --once        # Single report then exit
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import sys
import time

# ── Configuration ────────────────────────────────────────────────────────────
VERSION = "3.0.1"
DEFAULT_INTERVAL = 30
DEFAULT_CONFIG = (
    os.path.join(os.environ.get("PROGRAMDATA", "C:\\ProgramData"), "noba-agent", "agent.yaml")
    if platform.system().lower() == "windows"
    else "/etc/noba-agent.yaml"
)

# ── Submodule imports ─────────────────────────────────────────────────────────
# noqa: E402 — imports intentionally after VERSION constant (needed for _set_version)
import metrics as _metrics_mod  # noqa: E402
_metrics_mod._set_version(VERSION)

import queue as _queue  # noqa: E402
from metrics import collect_metrics  # noqa: E402
from commands import (  # noqa: E402
    execute_commands,
    collect_stream_data,
    has_active_streams,
    probe_capabilities,
    report,
)
from websocket import _WebSocketClient  # noqa: E402, F401
from terminal import _pty_open, _pty_input, _pty_resize, _pty_close, _pty_close_all  # noqa: E402
from healing import HealRuntime  # noqa: E402
from rdp import _rdp_start, _rdp_stop, _rdp_inject_input, _rdp_frame_queue, _rdp_active, _rdp_clipboard_get, _rdp_clipboard_paste  # noqa: E402, F401

# ── Capability probe interval ────────────────────────────────────────────────
_last_capability_probe: float = 0
_CAPABILITY_PROBE_INTERVAL = 21600  # 6 hours


def load_config(path: str | None = None) -> dict:
    """Load config from YAML file, simple key:value file, or environment."""
    cfg = {
        "server": os.environ.get("NOBA_SERVER", ""),
        "api_key": os.environ.get("NOBA_AGENT_KEY", ""),
        "interval": int(os.environ.get("NOBA_AGENT_INTERVAL", str(DEFAULT_INTERVAL))),
        "hostname": os.environ.get("NOBA_AGENT_HOSTNAME", ""),
        "tags": os.environ.get("NOBA_AGENT_TAGS", ""),
    }
    if path and os.path.exists(path):
        try:
            import yaml
            with open(path) as f:
                file_cfg = yaml.safe_load(f) or {}
            for k, v in file_cfg.items():
                if v is not None and str(v):
                    cfg[k] = v
        except ImportError:
            # Fallback: parse simple key: value without yaml
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if ":" in line and not line.startswith("#"):
                        k, v = line.split(":", 1)
                        cfg[k.strip()] = v.strip()
    if isinstance(cfg.get("interval"), str):
        cfg["interval"] = int(cfg["interval"])
    return cfg


def _ws_thread(server: str, api_key: str, hostname: str, ctx: dict) -> None:
    """Background thread: maintain WebSocket connection for instant commands."""
    import urllib.parse
    from websocket import _WebSocketClient as WSClient

    ws_url = server.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url.rstrip('/')}/api/agent/ws?key={urllib.parse.quote(api_key)}"

    backoff = 5
    max_backoff = 60

    while not ctx.get("_stop"):
        ws = None
        try:
            ws = WSClient(ws_url)
            ws.connect()
            print(f"[agent] WebSocket connected to {server}")
            backoff = 5

            ws.send_json({
                "type": "identify",
                "hostname": hostname,
                "agent_version": VERSION,
            })

            while not ctx.get("_stop"):
                # ── Drain RDP frame queue before blocking on recv ──────────────
                # The capture thread (if active) enqueues frames here so that only
                # the main loop touches the socket, avoiding concurrent send races.
                while True:
                    try:
                        frame = _rdp_frame_queue.get_nowait()
                        ws.send_json(frame)
                    except _queue.Empty:
                        break

                # Use a short timeout when RDP is active so frames are sent promptly
                recv_timeout = 0.2 if _rdp_active.is_set() else 30
                msg = ws.recv_json(timeout=recv_timeout)
                if msg is None:
                    if not _rdp_active.is_set():
                        ws.send_json({"type": "ping"})
                    continue

                if msg.get("type") == "command":
                    cmd_obj = {
                        "type": msg.get("cmd", ""),
                        "id": msg.get("id", ""),
                        "params": msg.get("params", {}),
                    }
                    cmd_ctx = {
                        **ctx,
                        "_current_cmd_id": msg.get("id", ""),
                        "_ws_send": lambda m: ws.send_json(m),
                    }
                    results = execute_commands([cmd_obj], cmd_ctx)
                    for r in results:
                        # Rename r["type"] to "cmd" to avoid overwriting
                        # the message type "result" with the command type
                        payload = {"type": "result", "cmd": r.get("type", "")}
                        payload.update({k: v for k, v in r.items() if k != "type"})
                        ws.send_json(payload)

                elif msg.get("type") == "pty_open":
                    sid = msg.get("session", "")
                    cols = msg.get("cols", 80)
                    rows = msg.get("rows", 24)
                    pty_role = msg.get("role", "operator")
                    result = _pty_open(sid, lambda m: ws.send_json(m), cols, rows, role=pty_role)
                    ws.send_json(result)

                elif msg.get("type") == "pty_input":
                    _pty_input(msg.get("session", ""), msg.get("data", ""))

                elif msg.get("type") == "pty_resize":
                    _pty_resize(msg.get("session", ""), msg.get("cols", 80), msg.get("rows", 24))

                elif msg.get("type") == "pty_close":
                    _pty_close(msg.get("session", ""))
                    ws.send_json({"type": "pty_exit", "session": msg.get("session", ""), "code": 0})

                elif msg.get("type") == "rdp_start":
                    _rdp_start(
                        quality=int(msg.get("quality", 70)),
                        fps=int(msg.get("fps", 5)),
                    )

                elif msg.get("type") == "rdp_stop":
                    _rdp_stop()

                elif msg.get("type") == "rdp_input":
                    _rdp_inject_input(msg)

                elif msg.get("type") == "rdp_clipboard_paste":
                    _rdp_clipboard_paste(msg.get("text", ""))

                elif msg.get("type") == "rdp_clipboard_get":
                    text = _rdp_clipboard_get()
                    resp: dict = {"type": "rdp_clipboard", "text": text}
                    if "_req_id" in msg:
                        resp["_req_id"] = msg["_req_id"]
                    ws.send_json(resp)

                elif msg.get("type") == "pong":
                    pass

        except Exception as exc:
            _rdp_stop()
            _pty_close_all()
            if not ctx.get("_stop"):
                print(f"[agent] WebSocket error: {exc}", file=sys.stderr)
        finally:
            if ws:
                ws.close()

        if ctx.get("_stop"):
            break

        time.sleep(backoff)
        backoff = min(backoff * 2, max_backoff)


def main() -> None:
    parser = argparse.ArgumentParser(description="NOBA Agent — System Telemetry Collector")
    parser.add_argument("--server", help="NOBA server URL (e.g., http://noba:8080)")
    parser.add_argument("--key", help="Agent API key")
    parser.add_argument("--interval", type=int, help=f"Collection interval in seconds (default: {DEFAULT_INTERVAL})")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Config file path")
    parser.add_argument("--hostname", help="Override hostname")
    parser.add_argument("--once", action="store_true", help="Collect and report once, then exit")
    parser.add_argument("--dry-run", action="store_true", help="Collect and print, don't send")
    parser.add_argument("--version", action="version", version=f"NOBA Agent {VERSION}")
    args = parser.parse_args()

    cfg = load_config(args.config if os.path.exists(args.config or "") else None)
    server = args.server or cfg.get("server", "")
    api_key = args.key or cfg.get("api_key", "")
    interval = args.interval or cfg.get("interval", DEFAULT_INTERVAL)
    hostname_override = args.hostname or cfg.get("hostname", "")

    if not server and not args.dry_run:
        print("Error: --server or NOBA_SERVER required", file=sys.stderr)
        sys.exit(1)

    try:
        import psutil
        backend = f"psutil {psutil.__version__}"
    except ImportError:
        backend = "/proc (zero-dep)"

    print(f"[agent] NOBA Agent v{VERSION} on {hostname_override or socket.gethostname()}")
    print(f"[agent] Backend: {backend}")
    print(f"[agent] Server: {server or '(dry-run)'}")
    print(f"[agent] Interval: {interval}s")

    consecutive_failures = 0
    max_backoff = 300  # 5 minutes max between retries
    cmd_results = []  # Results from previous cycle's commands
    heal_runtime = HealRuntime()
    ctx = {"server": server, "api_key": api_key, "interval": interval}

    # Start WebSocket thread for real-time commands
    ws_ctx = {**ctx, "_stop": False}
    if server and not args.dry_run and not args.once:
        import threading
        agent_hostname = hostname_override or socket.gethostname()
        ws_t = threading.Thread(
            target=_ws_thread,
            args=(server, api_key, agent_hostname, ws_ctx),
            daemon=True,
        )
        ws_t.start()
        print("[agent] WebSocket thread started")

    while True:
        try:
            metrics = collect_metrics()
            if hostname_override:
                metrics["hostname"] = hostname_override
            if cfg.get("tags"):
                metrics["tags"] = cfg["tags"]
            # Attach command results from previous cycle
            if cmd_results:
                metrics["_cmd_results"] = cmd_results
                cmd_results = []
            # Attach any buffered stream data
            stream_data = collect_stream_data()
            if stream_data:
                metrics["_stream_data"] = stream_data
            # Attach heal reports from previous cycle
            heal_reports = heal_runtime.drain_reports()
            if heal_reports:
                metrics["_heal_reports"] = heal_reports

            # Attach capability manifest periodically (every 6h or on first report)
            global _last_capability_probe
            now_ts = time.time()
            if now_ts - _last_capability_probe > _CAPABILITY_PROBE_INTERVAL:
                try:
                    metrics["_capabilities"] = probe_capabilities()
                    _last_capability_probe = now_ts
                except Exception as e:
                    print(f"[agent] Capability probe failed: {e}", file=sys.stderr)

            if args.dry_run:
                print(json.dumps(metrics, indent=2))
                break

            ok, resp_body = report(server, api_key, metrics)
            if ok:
                if consecutive_failures > 0:
                    print(f"[agent] Connection restored after {consecutive_failures} failures")
                consecutive_failures = 0
                # Execute any pending commands from server
                commands = resp_body.get("commands", [])
                if commands:
                    print(f"[agent] Received {len(commands)} command(s)")
                    cmd_results = execute_commands(commands, ctx)
                    # Check if interval was changed
                    if ctx.get("interval") != interval:
                        interval = ctx["interval"]
                        print(f"[agent] Interval changed to {interval}s")
                # Update heal policy from server
                heal_policy = resp_body.get("heal_policy", {})
                if heal_policy:
                    heal_runtime.update_policy(heal_policy)
                # Evaluate heal rules against current metrics
                heal_runtime.evaluate(metrics, ctx)
            else:
                consecutive_failures += 1
                if consecutive_failures <= 3 or consecutive_failures % 10 == 0:
                    print(f"[agent] Report failed (attempt {consecutive_failures})", file=sys.stderr)

            if args.once:
                sys.exit(0 if ok else 1)

            # Backoff on repeated failures
            if consecutive_failures > 3:
                backoff = min(interval * (2 ** min(consecutive_failures - 3, 5)), max_backoff)
                time.sleep(backoff)
            elif has_active_streams():
                # When streaming logs, report every 2 seconds for near-real-time delivery
                time.sleep(2)
            else:
                time.sleep(interval)

        except KeyboardInterrupt:
            ws_ctx["_stop"] = True
            print("\n[agent] Stopped")
            break
        except Exception as e:
            consecutive_failures += 1
            if consecutive_failures <= 3:
                print(f"[agent] Error: {e}", file=sys.stderr)
            if args.once:
                sys.exit(1)
            time.sleep(min(interval * 2, max_backoff))


if __name__ == "__main__":
    main()
