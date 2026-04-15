# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Speedtest Tracker -- Periodic internet speed tests with history.

Runs speedtest-cli periodically and stores results for trending.
Displays download/upload speeds and latency on a dashboard card.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

PLUGIN_ID = "speedtest_tracker"
PLUGIN_NAME = "Speedtest Tracker"
PLUGIN_VERSION = "1.0.0"
PLUGIN_ICON = "fa-tachometer-alt"
PLUGIN_DESCRIPTION = "Periodic internet speed tests with download/upload history and latency tracking."
PLUGIN_INTERVAL = 30

PLUGIN_CONFIG_SCHEMA = {
    "test_interval_minutes": {
        "type": "number",
        "label": "Test interval (minutes)",
        "default": 60,
        "min": 5,
        "max": 1440,
    },
    "server_id": {
        "type": "string",
        "label": "Server ID",
        "default": "",
        "placeholder": "Auto-select (leave empty)",
    },
    "download_threshold": {
        "type": "number",
        "label": "Min download alert (Mbps)",
        "default": 0,
        "min": 0,
    },
    "upload_threshold": {
        "type": "number",
        "label": "Min upload alert (Mbps)",
        "default": 0,
        "min": 0,
    },
    "max_history": {
        "type": "number",
        "label": "Max results to keep",
        "default": 100,
        "min": 10,
        "max": 1000,
    },
}

_lock = threading.Lock()
_results: list[dict] = []
_latest: dict = {}
_error: str = ""
_last_test: float = 0
_ctx = None

# Persistent storage for results
_RESULTS_FILE = Path("~/.config/noba/plugins/config/speedtest_history.json").expanduser()


def _load_history() -> list[dict]:
    try:
        if _RESULTS_FILE.is_file():
            data = json.loads(_RESULTS_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _save_history(results: list[dict]) -> None:
    try:
        _RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RESULTS_FILE.write_text(json.dumps(results, indent=1), encoding="utf-8")
    except Exception:
        pass


def _run_speedtest(cfg: dict) -> dict | None:
    """Run speedtest-cli and return parsed results."""
    cmd = ["speedtest-cli", "--json"]
    server_id = cfg.get("server_id", "")
    if server_id:
        cmd.extend(["--server", str(server_id)])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        return {
            "download": round(data.get("download", 0) / 1_000_000, 2),
            "upload": round(data.get("upload", 0) / 1_000_000, 2),
            "ping": round(data.get("ping", 0), 1),
            "server": data.get("server", {}).get("sponsor", "Unknown"),
            "timestamp": time.time(),
        }
    except FileNotFoundError:
        return {"error": "speedtest-cli not installed. Run: pip install speedtest-cli"}
    except subprocess.TimeoutExpired:
        return {"error": "Speedtest timed out after 120s"}
    except Exception as e:
        return {"error": str(e)}


def _test_loop(cfg: dict) -> None:
    """Background loop that runs periodic speed tests."""
    global _last_test  # noqa: PLW0603
    interval = max(int(cfg.get("test_interval_minutes", 60)), 5) * 60
    max_hist = int(cfg.get("max_history", 100))

    while True:
        now = time.time()
        if now - _last_test >= interval:
            result = _run_speedtest(cfg)
            if result:
                with _lock:
                    global _latest, _error  # noqa: PLW0603
                    if "error" in result:
                        _error = result["error"]
                    else:
                        _latest = result
                        _error = ""
                        _results.append(result)
                        if len(_results) > max_hist:
                            _results[:] = _results[-max_hist:]
                        _save_history(_results)
            _last_test = now
        time.sleep(30)


def register(ctx) -> None:
    """Initialize speedtest tracker."""
    global _ctx  # noqa: PLW0603
    _ctx = ctx
    cfg = ctx.get_config()

    # Load history
    with _lock:
        loaded = _load_history()
        _results.extend(loaded)

    t = threading.Thread(target=_test_loop, args=(cfg,), daemon=True, name="speedtest-tracker")
    t.start()


def collect() -> dict:
    """Return latest speedtest results."""
    with _lock:
        cfg = _ctx.get_config() if _ctx else {}
        dl_thresh = float(cfg.get("download_threshold", 0))
        ul_thresh = float(cfg.get("upload_threshold", 0))

        alerts = []
        if _latest and dl_thresh > 0 and _latest.get("download", 0) < dl_thresh:
            alerts.append(f"Download {_latest['download']} Mbps below {dl_thresh} threshold")
        if _latest and ul_thresh > 0 and _latest.get("upload", 0) < ul_thresh:
            alerts.append(f"Upload {_latest['upload']} Mbps below {ul_thresh} threshold")

        return {
            "latest": dict(_latest) if _latest else {},
            "history": [
                {"dl": r["download"], "ul": r["upload"], "ping": r["ping"], "ts": r["timestamp"]}
                for r in _results[-24:]
            ],
            "alerts": alerts,
            "error": _error,
            "total_tests": len(_results),
        }


def render(data: dict) -> str:
    """Render dashboard card HTML."""
    error = data.get("error", "")
    if error:
        return f'<div style="color:var(--danger);font-size:.8rem">{error}</div>'
    latest = data.get("latest", {})
    if not latest:
        return '<div style="color:var(--text-muted);font-size:.8rem">Running first speed test...</div>'

    dl = latest.get("download", 0)
    ul = latest.get("upload", 0)
    ping = latest.get("ping", 0)
    server = latest.get("server", "")

    alerts_html = ""
    for a in data.get("alerts", []):
        alerts_html += f'<div style="color:var(--warning);font-size:.7rem;margin-top:2px">{a}</div>'

    return (
        f'<div style="display:flex;gap:1rem;align-items:center;margin-bottom:.3rem">'
        f'<div style="text-align:center"><div style="font-size:1.4rem;font-weight:700;color:var(--success)">{dl}</div>'
        f'<div style="font-size:.6rem;color:var(--text-muted)">DOWN Mbps</div></div>'
        f'<div style="text-align:center"><div style="font-size:1.4rem;font-weight:700;color:var(--accent)">{ul}</div>'
        f'<div style="font-size:.6rem;color:var(--text-muted)">UP Mbps</div></div>'
        f'<div style="text-align:center"><div style="font-size:1rem;font-weight:600">{ping}ms</div>'
        f'<div style="font-size:.6rem;color:var(--text-muted)">PING</div></div>'
        f'</div>'
        f'<div style="font-size:.65rem;color:var(--text-dim)">Server: {server}</div>'
        f'{alerts_html}'
    )


def teardown() -> None:
    pass
