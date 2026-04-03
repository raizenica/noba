# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Monitoring integrations."""
from __future__ import annotations

import logging
import httpx
import re

try:
    from . import simple
    _http_get = simple._http_get
    _client = simple._client
except ImportError:
    from .base import ConfigError, TransientError, _client, _http_get
    # If simple not available, use base directly (shouldn't happen in tests)
from .base import ConfigError, TransientError


logger = logging.getLogger("noba")



# ── Uptime Kuma ───────────────────────────────────────────────────────────────
def get_kuma(url: str) -> list:
    if not url:
        return []
    try:
        r = _client.get(f"{url.rstrip('/')}/metrics", timeout=3)
        r.raise_for_status()
        lines = r.text.splitlines()
        monitors = []
        for line in lines:
            if line.startswith("monitor_status{"):
                m = re.search(r'monitor_name="([^"]+)"', line)
                if m:
                    val = int(float(line.split()[-1]))
                    monitors.append({
                        "name":   m.group(1),
                        "status": "Up" if val == 1 else ("Pending" if val == 2 else "Down"),
                    })
        return monitors
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}



# ── Scrutiny ────────────────────────────────────────────────────────────────
def get_scrutiny(url: str) -> dict | None:
    """Fetch disk health summary from a Scrutiny instance."""
    if not url:
        return None
    try:
        base = url.rstrip("/")
        data = _http_get(f"{base}/api/summary", timeout=10)
        summary = data.get("data", {}).get("summary", {})
        if not summary:
            return None
        device_list = []
        healthy = 0
        failed = 0
        warn = 0
        total_capacity = 0
        max_temp = 0
        # device_status: 0=passed, 1=warn, 2=failed, 3=unknown
        for _wwn, info in summary.items():
            dev = info.get("device", {})
            smart = info.get("smart", {})
            status = dev.get("device_status", 3)
            if status == 0:
                healthy += 1
            elif status == 1:
                warn += 1
            else:
                failed += 1
            temp = smart.get("temp") or 0
            hours = smart.get("power_on_hours") or 0
            cap = dev.get("capacity") or 0
            total_capacity += cap
            if temp > max_temp:
                max_temp = temp
            device_list.append({
                "name": dev.get("device_name", ""),
                "model": dev.get("model_name", ""),
                "serial": dev.get("serial_number", ""),
                "status": status,
                "temperature": temp,
                "capacity": cap,
                "powerOnHours": hours,
                "protocol": dev.get("device_protocol", ""),
            })
        device_list.sort(key=lambda d: d["name"])
        return {
            "devices": len(summary),
            "healthy": healthy,
            "failed": failed,
            "warn": warn,
            "totalCapacityBytes": total_capacity,
            "maxTemp": max_temp,
            "device_list": device_list,
        }
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





# ── Scrutiny Intelligence ───────────────────────────────────────────────────
def get_scrutiny_intelligence(url: str) -> list[dict] | None:
    """Fetch SMART attribute history and compute failure predictions."""
    if not url:
        return None
    base = url.rstrip("/")
    try:
        summary_data = _http_get(f"{base}/api/summary", timeout=10)
        summary = summary_data.get("data", {}).get("summary", {})
        if not summary:
            return None
        predictions = []
        for wwn, info in summary.items():
            dev = info.get("device", {})
            smart = info.get("smart", {})
            status = dev.get("device_status", 3)
            hours = smart.get("power_on_hours") or 0
            temp = smart.get("temp") or 0
            # Try to get detailed SMART history
            risk_score = 0
            growth_rate = 0.0
            estimated = ""
            try:
                detail = _http_get(f"{base}/api/device/{wwn}/details", timeout=8)
                results = detail.get("data", {}).get("smart_results", [])
                if len(results) >= 2:
                    # Check reallocated sectors (attr 5) trend
                    attr5_vals = []
                    for r in results:
                        attrs = r.get("attrs", {})
                        a5 = attrs.get("5", {})
                        if a5:
                            attr5_vals.append((r.get("date", ""), a5.get("raw_value", 0)))
                    if len(attr5_vals) >= 2 and attr5_vals[0][1] != attr5_vals[-1][1]:
                        total_growth = attr5_vals[-1][1] - attr5_vals[0][1]
                        # Simple rate (sectors per month estimate)
                        months = max(len(attr5_vals), 1)
                        growth_rate = round(total_growth / months, 1)
                        risk_score = min(100, int(growth_rate * 10 + (30 if status >= 2 else 0)))
                        if growth_rate > 0:
                            # Rough estimate: threshold ~4000 sectors
                            remaining = max(0, 4000 - attr5_vals[-1][1])
                            months_to_fail = remaining / growth_rate if growth_rate > 0 else 999
                            if months_to_fail < 120:
                                from datetime import datetime, timedelta as td  # noqa: PLC0415
                                est_date = datetime.now() + td(days=months_to_fail * 30)
                                estimated = est_date.strftime("%Y-%m")
                    elif status >= 2:
                        risk_score = 25  # Failed status but stable attributes
            except (httpx.HTTPError, KeyError, ValueError):
                if status >= 2:
                    risk_score = 20
            predictions.append({
                "wwn": wwn,
                "name": dev.get("device_name", ""),
                "model": dev.get("model_name", ""),
                "serial": dev.get("serial_number", ""),
                "status": status,
                "temp": temp,
                "powerOnHours": hours,
                "riskScore": risk_score,
                "growthRate": growth_rate,
                "estimatedFailure": estimated,
            })
        predictions.sort(key=lambda d: d["riskScore"], reverse=True)
        return predictions
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





# ── Speedtest Tracker ────────────────────────────────────────────────────────
def get_speedtest(url: str):
    if not url:
        return None
    try:
        base = url.rstrip("/")
        data = _http_get(f"{base}/api/speedtest/latest")
        if not data or not data.get("data"):
            return None
        r = data["data"]
        return {
            "download": round(r.get("download", 0) / 1_000_000, 1),
            "upload": round(r.get("upload", 0) / 1_000_000, 1),
            "ping": round(r.get("ping", 0), 1),
            "server": r.get("server_name", ""),
            "status": "online",
        }
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





# ── Frigate NVR ─────────────────────────────────────────────────────────────
def get_frigate(url: str) -> dict | None:
    """Fetch camera list and status from Frigate NVR."""
    if not url:
        return None
    base = url.rstrip("/")
    try:
        stats = _http_get(f"{base}/api/stats", timeout=6)
        config = _http_get(f"{base}/api/config", timeout=6)
        cameras = []
        cam_configs = config.get("cameras", {})
        for name, cfg in cam_configs.items():
            cam_stats = stats.get(name, {})
            cameras.append({
                "name": name,
                "fps": cam_stats.get("camera_fps", 0),
                "detect": cfg.get("detect", {}).get("enabled", False),
                "record": cfg.get("record", {}).get("enabled", False),
                "status": "online" if cam_stats.get("camera_fps", 0) > 0 else "offline",
            })
        svc = stats.get("service", {})
        return {
            "cameras": cameras,
            "cameraCount": len(cameras),
            "onlineCount": sum(1 for c in cameras if c["status"] == "online"),
            "version": svc.get("version", ""),
            "uptime": svc.get("uptime", 0),
            "status": "online",
        }
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





# ── Graylog ──────────────────────────────────────────────────────────────────
def get_graylog(url: str, token: str, query: str = "*", hours: int = 1) -> dict | None:
    """Query Graylog for recent log messages.

    *token* can be a Graylog API token (used as ``token:token`` Basic auth)
    or a ``user:password`` string for direct Basic auth.
    """
    if not url or not token:
        return None
    base = url.rstrip("/")
    try:
        import base64 as b64
        # If token contains ':', treat as user:password; otherwise as API token
        creds = token if ":" in token else f"{token}:token"
        auth = b64.b64encode(creds.encode()).decode()
        r = _client.get(
            f"{base}/api/search/universal/relative",
            params={"query": query, "range": hours * 3600, "limit": 50, "sort": "timestamp:desc"},
            headers={"Authorization": f"Basic {auth}", "Accept": "application/json",
                     "X-Requested-By": "noba"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        messages = []
        for msg in data.get("messages", []):
            m = msg.get("message", {})
            messages.append({
                "timestamp": m.get("timestamp", ""),
                "source": m.get("source", ""),
                "message": m.get("message", "")[:200],
                "level": m.get("level", 0),
                "facility": m.get("facility", ""),
            })
        return {
            "total": data.get("total_results", 0),
            "messages": messages,
            "query": query,
            "status": "online",
        }
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





# ── InfluxDB v2 ─────────────────────────────────────────────────────────────
def query_influxdb(url: str, token: str, org: str, query: str) -> list[dict] | None:
    """Execute a Flux query against InfluxDB v2 and return results."""
    if not url or not token or not query:
        return None
    base = url.rstrip("/")
    try:
        r = _client.post(
            f"{base}/api/v2/query",
            params={"org": org},
            headers={
                "Authorization": f"Token {token}",
                "Content-Type": "application/vnd.flux",
                "Accept": "application/csv",
            },
            content=query,
            timeout=15,
        )
        r.raise_for_status()
        # Parse CSV response
        lines = r.text.strip().split("\n")
        if len(lines) < 2:
            return []
        headers = lines[0].split(",")
        results = []
        for line in lines[1:]:
            if not line.strip() or line.startswith(",result"):
                continue
            cols = line.split(",")
            row = {}
            for i, h in enumerate(headers):
                if i < len(cols) and h.strip() and h.strip() not in ("", "result", "table"):
                    row[h.strip()] = cols[i].strip()
            if row:
                results.append(row)
        return results[:1000]  # Limit to 1000 rows
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}


# ── Weather (OpenWeatherMap) ─────────────────────────────────────────────────
def get_weather(api_key: str, city: str) -> dict | None:
    if not api_key or not city:
        return None
    try:
        data = _http_get(
            f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric",
            timeout=4,
        )
        weather = data.get("weather", [{}])[0] if data.get("weather") else {}
        main = data.get("main", {})
        return {
            "temp": float(main.get("temp", 0)),
            "feels_like": float(main.get("feels_like", 0)),
            "humidity": int(main.get("humidity", 0)),
            "description": weather.get("description", ""),
            "icon": weather.get("icon", ""),
            "city": data.get("name", city),
            "status": "online",
        }
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





# ── Energy Monitoring (Shelly) ───────────────────────────────────────────
def get_energy_shelly(urls: list[str]) -> list[dict]:
    """Query Shelly smart plugs/meters for power data."""
    results = []
    for entry in urls:
        parts = entry.split("|")
        url = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else url
        if not url:
            continue
        base = (url if url.startswith("http") else "http://" + url).rstrip("/")
        try:
            # Shelly Gen2 API
            data = _http_get(f"{base}/rpc/Switch.GetStatus?id=0", timeout=3)
            results.append({
                "name": name,
                "power_w": round(data.get("apower", 0), 1),
                "voltage_v": round(data.get("voltage", 0), 1),
                "current_a": round(data.get("current", 0), 3),
                "energy_wh": round(data.get("aenergy", {}).get("total", 0), 1),
                "on": data.get("output", False),
                "status": "online",
            })
        except (httpx.HTTPError, KeyError, ValueError):
            try:
                # Shelly Gen1 API fallback
                data = _http_get(f"{base}/status", timeout=3)
                meter = data.get("meters", [{}])[0] if data.get("meters") else {}
                relay = data.get("relays", [{}])[0] if data.get("relays") else {}
                results.append({
                    "name": name,
                    "power_w": round(meter.get("power", 0), 1),
                    "voltage_v": 0,
                    "current_a": 0,
                    "energy_wh": round(meter.get("total", 0) / 60, 1),  # Watt-minutes to Wh
                    "on": relay.get("ison", False),
                    "status": "online",
                })
            except (httpx.HTTPError, KeyError, ValueError):
                results.append({"name": name, "status": "offline"})
    return results



