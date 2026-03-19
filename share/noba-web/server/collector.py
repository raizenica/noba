"""Noba – Background stats collector and assembly."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .config import STATS_INTERVAL, _WORKER_THREADS
from .db import db
from .metrics import (
    collect_system, collect_hardware, collect_storage, collect_network,
    get_cpu_percent, get_cpu_history, get_service_status, ping_host, get_containers,
    collect_disk_io, collect_per_interface_net,
)
from .integrations import (
    get_pihole, get_plex, get_kuma, get_truenas, get_servarr, get_qbit, get_proxmox,
    get_adguard, get_jellyfin, get_hass, get_unifi, get_speedtest,
)
from .alerts import build_threshold_alerts, check_anomalies, evaluate_alert_rules
from .plugins import plugin_manager
from .yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

_pool = ThreadPoolExecutor(max_workers=_WORKER_THREADS, thread_name_prefix="noba-worker")

_shutdown_flag = threading.Event()


def get_shutdown_flag() -> threading.Event:
    return _shutdown_flag


def collect_stats(qs: dict) -> dict:
    stats: dict = {"timestamp": datetime.now().strftime("%H:%M:%S")}
    stats.update(collect_system())
    stats.update(collect_hardware())
    stats.update(collect_storage())
    stats["cpuPercent"] = get_cpu_percent()
    stats["cpuHistory"] = get_cpu_history()
    stats.update(collect_network())

    cfg = read_yaml_settings()

    # Parse query string / config values
    def _qs0(key: str) -> str:
        v = qs.get(key, [""])
        return v[0] if v else ""

    svc_list  = [s.strip() for s in _qs0("services").split(",") if s.strip()]
    ip_list   = [ip.strip() for ip in _qs0("radar").split(",") if ip.strip()]
    ph_url    = cfg.get("piholeUrl",  "") or _qs0("pihole")
    ph_tok    = cfg.get("piholeToken","") or _qs0("piholetok")
    plex_url  = cfg.get("plexUrl",    "") or _qs0("plexUrl")
    plex_tok  = cfg.get("plexToken",  "") or _qs0("plexToken")
    kuma_url  = cfg.get("kumaUrl",    "") or _qs0("kumaUrl")
    bmc_map   = [x.strip() for x in _qs0("bmcMap").split(",") if x.strip()]
    tn_url    = cfg.get("truenasUrl",         "")
    tn_key    = cfg.get("truenasKey",         "")
    rad_url   = cfg.get("radarrUrl",          "")
    rad_key   = cfg.get("radarrKey",          "")
    son_url   = cfg.get("sonarrUrl",          "")
    son_key   = cfg.get("sonarrKey",          "")
    qbit_url  = cfg.get("qbitUrl",            "")
    qbit_user = cfg.get("qbitUser",           "")
    qbit_pass = cfg.get("qbitPass",           "")
    pmx_url   = cfg.get("proxmoxUrl",         "")
    pmx_user  = cfg.get("proxmoxUser",        "")
    pmx_tname = cfg.get("proxmoxTokenName",   "")
    pmx_tval  = cfg.get("proxmoxTokenValue",  "")
    ag_url    = cfg.get("adguardUrl", "")
    ag_user   = cfg.get("adguardUser", "")
    ag_pass   = cfg.get("adguardPass", "")
    jf_url    = cfg.get("jellyfinUrl", "")
    jf_key    = cfg.get("jellyfinKey", "")
    hass_url  = cfg.get("hassUrl", "")
    hass_tok  = cfg.get("hassToken", "")
    unifi_url  = cfg.get("unifiUrl", "")
    unifi_user = cfg.get("unifiUser", "")
    unifi_pass = cfg.get("unifiPass", "")
    unifi_site = cfg.get("unifiSite", "default")
    spd_url   = cfg.get("speedtestUrl", "")
    wan_ip    = cfg.get("wanTestIp", "")
    lan_ip    = cfg.get("lanTestIp", "")

    bmc_list = []
    for entry in bmc_map:
        parts = entry.split("|")
        if len(parts) == 2:
            bmc_list.append((parts[0].strip(), parts[1].strip()))

    # ── Submit async tasks ────────────────────────────────────────────────────
    svc_futs  = {_pool.submit(get_service_status, s): s for s in svc_list}
    ping_futs = {_pool.submit(ping_host, ip): ip for ip in ip_list}
    bmc_futs  = {_pool.submit(ping_host, bmc_ip): (os_ip, bmc_ip) for os_ip, bmc_ip in bmc_list}

    wan_fut   = _pool.submit(ping_host, wan_ip) if wan_ip else None
    lan_fut   = _pool.submit(ping_host, lan_ip) if lan_ip else None

    ph_fut    = _pool.submit(get_pihole,  ph_url, ph_tok)   if ph_url  else None
    plex_fut  = _pool.submit(get_plex,    plex_url, plex_tok) if plex_url else None
    kuma_fut  = _pool.submit(get_kuma,    kuma_url)          if kuma_url else None
    ct_fut    = _pool.submit(get_containers)
    tn_fut    = _pool.submit(get_truenas, tn_url, tn_key)    if tn_url  else None
    rad_fut   = _pool.submit(get_servarr, rad_url, rad_key)  if rad_url else None
    son_fut   = _pool.submit(get_servarr, son_url, son_key)  if son_url else None
    qbit_fut  = _pool.submit(get_qbit,   qbit_url, qbit_user, qbit_pass) if qbit_url else None
    pmx_fut   = _pool.submit(get_proxmox, pmx_url, pmx_user, pmx_tname, pmx_tval) if pmx_url else None
    ag_fut    = _pool.submit(get_adguard, ag_url, ag_user, ag_pass) if ag_url else None
    jf_fut    = _pool.submit(get_jellyfin, jf_url, jf_key) if jf_url else None
    hass_fut  = _pool.submit(get_hass, hass_url, hass_tok) if hass_url else None
    unifi_fut = _pool.submit(get_unifi, unifi_url, unifi_user, unifi_pass, unifi_site) if unifi_url else None
    spd_fut   = _pool.submit(get_speedtest, spd_url) if spd_url else None

    # ── Collect service status results ────────────────────────────────────────
    services = []
    for fut, svc in svc_futs.items():
        try:
            status, is_user = fut.result(timeout=4)
        except Exception:
            status, is_user = "error", False
        services.append({"name": svc, "status": status, "is_user": is_user})
    stats["services"] = services

    # ── Collect ping results ──────────────────────────────────────────────────
    radar = []
    for fut, ip in ping_futs.items():
        try:
            ip_r, up, ms = fut.result(timeout=4)
            radar.append({"ip": ip_r, "status": "Up" if up else "Down", "ms": ms if up else 0})
        except Exception:
            radar.append({"ip": ip, "status": "Down", "ms": 0})
    stats["radar"] = radar

    # ── Net health ────────────────────────────────────────────────────────────
    stats["netHealth"] = {"wan": "Down", "lan": "Down", "configured": bool(wan_ip or lan_ip)}
    if wan_fut:
        try:
            _, wan_up, _ = wan_fut.result(timeout=3)
            stats["netHealth"]["wan"] = "Up" if wan_up else "Down"
        except Exception:
            pass
    if lan_fut:
        try:
            _, lan_up, _ = lan_fut.result(timeout=3)
            stats["netHealth"]["lan"] = "Up" if lan_up else "Down"
        except Exception:
            pass

    # ── Integration results ───────────────────────────────────────────────────
    def _get(fut, timeout=4, default=None):
        try:
            return fut.result(timeout=timeout) if fut else default
        except Exception:
            return default

    stats["kuma"]       = _get(kuma_fut, default=[])
    stats["pihole"]     = _get(ph_fut)
    stats["plex"]       = _get(plex_fut)
    stats["containers"] = _get(ct_fut, timeout=5, default=[])
    stats["truenas"]    = _get(tn_fut, timeout=5)
    stats["radarr"]     = _get(rad_fut)
    stats["sonarr"]     = _get(son_fut)
    stats["qbit"]       = _get(qbit_fut)
    stats["proxmox"]    = _get(pmx_fut, timeout=6)
    stats["adguard"]    = _get(ag_fut)
    stats["jellyfin"]   = _get(jf_fut)
    stats["hass"]       = _get(hass_fut)
    stats["unifi"]      = _get(unifi_fut)
    stats["speedtest"]  = _get(spd_fut)

    stats.update(collect_disk_io())
    stats.update(collect_per_interface_net())

    # ── Alerts ────────────────────────────────────────────────────────────────
    stats["alerts"] = build_threshold_alerts(stats, read_yaml_settings)
    stats["alerts"].extend(check_anomalies(db, read_yaml_settings))

    # ── BMC sentinel ─────────────────────────────────────────────────────────
    for fut, (os_ip, bmc_ip) in bmc_futs.items():
        try:
            _, bmc_up, _ = fut.result(timeout=4)
            os_status = next((r["status"] for r in radar if r["ip"] == os_ip), None)
            if os_status == "Down" and bmc_up:
                stats["alerts"].append({
                    "level": "danger",
                    "msg":   f"BMC Sentinel: {os_ip} OS offline, BMC ({bmc_ip}) reachable!",
                })
        except Exception:
            pass

    evaluate_alert_rules(stats, read_yaml_settings)

    # ── Plugins ──────────────────────────────────────────────────────────────
    if plugin_manager.count:
        stats["plugins"] = plugin_manager.get_all()

    # ── Persist history ───────────────────────────────────────────────────────
    try:
        batch = [
            ("cpu_percent", stats.get("cpuPercent", 0), ""),
            ("mem_percent", stats.get("memPercent",  0), ""),
        ]
        ct = stats.get("cpuTemp", "N/A")
        if ct != "N/A":
            batch.append(("cpu_temp", float(ct.replace("°C", "")), ""))
        gt = stats.get("gpuTemp", "N/A")
        if gt != "N/A":
            batch.append(("gpu_temp", float(gt.replace("°C", "")), ""))
        for disk in stats.get("disks", []):
            batch.append(("disk_percent", disk["percent"], disk["mount"]))
        for r in radar:
            if r["status"] == "Up" and r["ms"] > 0:
                batch.append(("ping_ms", r["ms"], r["ip"]))
        batch.append(("net_rx_bytes", stats.get("netRxRaw", 0), ""))
        batch.append(("net_tx_bytes", stats.get("netTxRaw", 0), ""))
        db.insert_metrics(batch)
    except Exception as e:
        logger.error("History insert failed: %s", e)

    return stats


class BackgroundCollector:
    def __init__(self, interval: int = STATS_INTERVAL) -> None:
        self._latest:   dict = {}
        self._qs:       dict = {}
        self._lock      = threading.Lock()
        self._interval  = interval

    def update_qs(self, qs: dict) -> None:
        with self._lock:
            self._qs = dict(qs)

    def get(self) -> dict:
        with self._lock:
            return self._latest

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True, name="stats-collector").start()

    def _loop(self) -> None:
        while not _shutdown_flag.is_set():
            try:
                with self._lock:
                    qs = dict(self._qs)
                result = collect_stats(qs)
                with self._lock:
                    self._latest = result
            except Exception as e:
                logger.warning("Collector error: %s", e)
            _shutdown_flag.wait(self._interval)


# Singleton
bg_collector = BackgroundCollector()
