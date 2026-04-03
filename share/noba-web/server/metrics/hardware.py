# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Temperature, SMART, GPU, battery, IPMI metrics."""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import subprocess

import psutil

from .util import _cache, _read_file, _run


logger = logging.getLogger("noba")


# ── Hardware ──────────────────────────────────────────────────────────────────
def collect_hardware() -> dict:
    s: dict = {}
    cpu_model = ""
    try:
        for line in _read_file("/proc/cpuinfo").splitlines():
            if line.startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
    except Exception:
        pass
    s["hwCpu"] = cpu_model or "Unknown CPU"
    raw_gpu = _run(
        ["bash", "-c", "lspci | grep -i 'vga\\|3d' | cut -d: -f3"],
        cache_key="lspci", cache_ttl=3600,
    )
    s["hwGpu"] = raw_gpu.strip() if raw_gpu else "Unknown GPU"

    # CPU temperature — try psutil first, fall back to sensors
    cpu_temp = None
    try:
        temps = psutil.sensors_temperatures()
        for key in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz"):
            if key in temps and temps[key]:
                cpu_temp = int(temps[key][0].current)
                break
    except Exception:
        pass

    if cpu_temp is None:
        raw = _run(["sensors"], timeout=2, cache_key="sensors", cache_ttl=5)
        m = re.search(r"(?:Tctl|Package id \d+|Core 0|temp1).*?\+?(\d+\.?\d*)[°℃]", raw)
        cpu_temp = int(float(m.group(1))) if m else None

    s["cpuTemp"] = f"{cpu_temp}°C" if cpu_temp is not None else "N/A"

    # GPU temperature
    gpu_t = _run(
        ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
        timeout=2, cache_key="nvidia-temp", cache_ttl=5,
    )
    if not gpu_t:
        raw = _run(
            ["bash", "-c", "cat /sys/class/drm/card*/device/hwmon/hwmon*/temp1_input 2>/dev/null | head -1"],
            timeout=1,
        )
        gpu_t = f"{int(raw) // 1000}°C" if raw else "N/A"
    else:
        gpu_t = f"{gpu_t}°C"
    s["gpuTemp"] = gpu_t

    s["battery"] = _collect_battery()
    return s


def _collect_battery() -> dict:
    try:
        bat = psutil.sensors_battery()
        if bat is None:
            return {"percent": 100, "status": "Desktop", "desktop": True, "timeRemaining": ""}
        pct    = round(bat.percent)
        status = "Charging" if bat.power_plugged else "Discharging"
        tr = ""
        if bat.secsleft and bat.secsleft > 0 and not bat.power_plugged:
            h, m = divmod(bat.secsleft // 60, 60)
            tr = f"{h}h {m}m"
        elif bat.power_plugged and bat.secsleft and bat.secsleft > 0:
            h, m = divmod(bat.secsleft // 60, 60)
            tr = f"{h}h {m}m to full"
        return {"percent": pct, "status": status, "desktop": False, "timeRemaining": tr}
    except Exception:
        # Fall back to /sys if psutil fails
        bats = glob.glob("/sys/class/power_supply/BAT*")
        if not bats:
            return {"percent": 100, "status": "Desktop", "desktop": True, "timeRemaining": ""}
        try:
            b = bats[0]
            pct  = int(_read_file(f"{b}/capacity", "0"))
            stat = _read_file(f"{b}/status", "Unknown")
            return {"percent": pct, "status": stat, "desktop": False, "timeRemaining": ""}
        except Exception:
            return {"percent": 0, "status": "Error", "desktop": False, "timeRemaining": ""}


# ── SMART ─────────────────────────────────────────────────────────────────────
def collect_smart() -> list:
    cached = _cache.get("smart_data", 300)
    if cached is not None:
        return cached

    results = []
    devs = sorted({
        f"/dev/{os.path.basename(p)}"
        for p in glob.glob("/sys/block/*")
        if any(os.path.basename(p).startswith(pfx) for pfx in ("sd", "hd", "nvme", "vd"))
    })
    for dev in devs:
        try:
            raw = subprocess.check_output(
                ["smartctl", "-a", "-j", dev], timeout=10, stderr=subprocess.DEVNULL
            )
            d = json.loads(raw)
        except FileNotFoundError:
            break
        except subprocess.TimeoutExpired:
            results.append({"device": dev, "error": "timeout"})
            continue
        except Exception as e:
            results.append({"device": dev, "error": str(e)})
            continue

        model   = d.get("model_name") or d.get("model_family", "")
        serial  = d.get("serial_number", "")
        cap     = d.get("user_capacity", {}).get("bytes", 0)
        smart_ok = d.get("smart_status", {}).get("passed", True)
        temp     = d.get("temperature", {}).get("current")
        poh      = None
        attrs: dict = {}

        for attr in d.get("ata_smart_attributes", {}).get("table", []):
            aid      = attr.get("id")
            raw_val  = attr.get("raw", {}).get("value", 0)
            norm_val = attr.get("value", 0)
            if aid == 5:
                attrs["reallocated_sectors"] = raw_val
            elif aid == 9:
                poh = raw_val
            elif aid == 177:
                attrs["wear_leveling_count"] = norm_val
            elif aid == 194:
                if temp is None:
                    temp = raw_val
            elif aid == 197:
                attrs["pending_sectors"] = raw_val
            elif aid == 198:
                attrs["uncorrectable_sectors"] = raw_val
            elif aid == 231:
                attrs["ssd_life_left_pct"] = norm_val
            elif aid == 233:
                attrs["nand_writes_gb"] = raw_val

        nvme = d.get("nvme_smart_health_information_log", {})
        if nvme:
            if temp is None:
                temp = nvme.get("temperature")
            attrs["available_spare_pct"] = nvme.get("available_spare")
            attrs["percentage_used"]     = nvme.get("percentage_used")
            poh = nvme.get("power_on_hours", poh)

        risk = 0
        if not smart_ok:
            risk = 100
        if attrs.get("uncorrectable_sectors", 0) > 0:
            risk = max(risk, 75)
        if attrs.get("reallocated_sectors", 0) > 0:
            risk = max(risk, 60)
        if attrs.get("pending_sectors", 0) > 0:
            risk = max(risk, 50)
        if attrs.get("percentage_used", 0) > 90:
            risk = max(risk, 50)
        if attrs.get("available_spare_pct", 100) < 10:
            risk = max(risk, 50)
        if isinstance(temp, (int, float)) and temp > 55:
            risk = max(risk, 40)

        results.append({
            "device":         dev,
            "model":          model,
            "serial":         serial,
            "capacity_bytes": cap,
            "smart_ok":       smart_ok,
            "temp_c":         temp,
            "power_on_hours": poh,
            "risk_score":     risk,
            "attributes":     attrs,
        })

    _cache.set("smart_data", results)
    return results


def get_ipmi_sensors(host: str, user: str = "", password: str = "") -> list[dict]:
    """Query IPMI sensors from a remote BMC."""
    cmd = ["ipmitool"]
    if host:
        cmd += ["-H", host, "-I", "lanplus"]
        if user:
            cmd += ["-U", user]
        if password:
            cmd += ["-P", password]
    cmd += ["sdr", "list"]
    out = _run(cmd, timeout=10, ignore_rc=True)
    if not out:
        return []
    sensors = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3:
            name = parts[0]
            value = parts[1]
            status = parts[2]
            sensors.append({
                "name": name,
                "value": value,
                "status": status.lower(),
            })
    return sensors
