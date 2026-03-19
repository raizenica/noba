"""Noba – Background stats collector and assembly."""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .config import STATS_INTERVAL, _WORKER_THREADS
from .db import db
from .metrics import (
    collect_system, collect_hardware, collect_storage, collect_network,
    get_cpu_percent, get_cpu_history, get_service_status, ping_host, get_containers,
    collect_disk_io, collect_per_interface_net,
    check_cert_expiry, check_device_presence, check_domain_expiry, get_vpn_status,
    check_docker_updates, snapshot_top_processes,
)
from .integrations import (
    get_pihole, get_plex, get_kuma, get_truenas, get_servarr, get_qbit, get_proxmox,
    get_adguard, get_jellyfin, get_hass, get_unifi, get_speedtest,
    get_tautulli, get_overseerr, get_prowlarr, get_servarr_extended, get_servarr_calendar,
    get_nextcloud, get_traefik, get_npm, get_authentik, get_cloudflare, get_omv, get_xcpng,
    get_homebridge, get_z2m, get_esphome, get_unifi_protect, get_pikvm, get_k8s,
    get_gitea, get_gitlab, get_github, get_paperless, get_vaultwarden, get_weather,
    get_energy_shelly, get_scrutiny,
)
from .cache import cache as _cache
from .alerts import build_threshold_alerts, check_anomalies, evaluate_alert_rules
from .plugins import plugin_manager
from .yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

_pool = ThreadPoolExecutor(max_workers=_WORKER_THREADS, thread_name_prefix="noba-worker")

_shutdown_flag = threading.Event()
_docker_update_cycle = 0
_docker_update_lock = threading.Lock()


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

    # New integration config reads
    tau_url   = cfg.get("tautulliUrl", "")
    tau_key   = cfg.get("tautulliKey", "")
    ovs_url   = cfg.get("overseerrUrl", "")
    ovs_key   = cfg.get("overseerrKey", "")
    prowl_url = cfg.get("prowlarrUrl", "")
    prowl_key = cfg.get("prowlarrKey", "")
    lidarr_url = cfg.get("lidarrUrl", "")
    lidarr_key = cfg.get("lidarrKey", "")
    readarr_url = cfg.get("readarrUrl", "")
    readarr_key = cfg.get("readarrKey", "")
    bazarr_url = cfg.get("bazarrUrl", "")
    bazarr_key = cfg.get("bazarrKey", "")
    nc_url    = cfg.get("nextcloudUrl", "")
    nc_user   = cfg.get("nextcloudUser", "")
    nc_pass   = cfg.get("nextcloudPass", "")
    traefik_url = cfg.get("traefikUrl", "")
    npm_url   = cfg.get("npmUrl", "")
    npm_tok   = cfg.get("npmToken", "")
    ak_url    = cfg.get("authentikUrl", "")
    ak_tok    = cfg.get("authentikToken", "")
    cf_tok    = cfg.get("cloudflareToken", "")
    cf_zone   = cfg.get("cloudflareZoneId", "")
    omv_url   = cfg.get("omvUrl", "")
    omv_user  = cfg.get("omvUser", "")
    omv_pass  = cfg.get("omvPass", "")
    xcp_url   = cfg.get("xcpngUrl", "")
    xcp_user  = cfg.get("xcpngUser", "")
    xcp_pass  = cfg.get("xcpngPass", "")
    hb_url    = cfg.get("homebridgeUrl", "")
    hb_user   = cfg.get("homebridgeUser", "")
    hb_pass   = cfg.get("homebridgePass", "")
    z2m_url   = cfg.get("z2mUrl", "")
    esp_url   = cfg.get("esphomeUrl", "")
    protect_url  = cfg.get("unifiProtectUrl", "")
    protect_user = cfg.get("unifiProtectUser", "")
    protect_pass = cfg.get("unifiProtectPass", "")
    pikvm_url  = cfg.get("pikvmUrl", "")
    pikvm_user = cfg.get("pikvmUser", "")
    pikvm_pass = cfg.get("pikvmPass", "")
    k8s_url   = cfg.get("k8sUrl", "")
    k8s_tok   = cfg.get("k8sToken", "")
    gitea_url = cfg.get("giteaUrl", "")
    gitea_tok = cfg.get("giteaToken", "")
    gitlab_url = cfg.get("gitlabUrl", "")
    gitlab_tok = cfg.get("gitlabToken", "")
    github_tok = cfg.get("githubToken", "")
    paperless_url = cfg.get("paperlessUrl", "")
    paperless_tok = cfg.get("paperlessToken", "")
    vw_url    = cfg.get("vaultwardenUrl", "")
    vw_tok    = cfg.get("vaultwardenToken", "")
    weather_key  = cfg.get("weatherApiKey", "")
    weather_city = cfg.get("weatherCity", "")
    cert_hosts   = [h.strip() for h in cfg.get("certHosts", "").split(",") if h.strip()]
    domain_list  = [d.strip() for d in cfg.get("domainList", "").split(",") if d.strip()]
    presence_ips = [x.strip() for x in cfg.get("devicePresenceIps", "").split(",") if x.strip()]
    scrutiny_url = cfg.get("scrutinyUrl", "")
    energy_urls  = [x.strip() for x in cfg.get("energySensors", "").split(",") if x.strip()]

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

    # New integration futures
    tau_fut     = _pool.submit(get_tautulli, tau_url, tau_key) if tau_url else None
    ovs_fut     = _pool.submit(get_overseerr, ovs_url, ovs_key) if ovs_url else None
    prowl_fut   = _pool.submit(get_prowlarr, prowl_url, prowl_key) if prowl_url else None
    lidarr_fut  = _pool.submit(get_servarr, lidarr_url, lidarr_key) if lidarr_url else None
    readarr_fut = _pool.submit(get_servarr, readarr_url, readarr_key) if readarr_url else None
    bazarr_fut  = _pool.submit(get_servarr, bazarr_url, bazarr_key) if bazarr_url else None
    rad_ext_fut = _pool.submit(get_servarr_extended, rad_url, rad_key, "radarr") if rad_url else None
    son_ext_fut = _pool.submit(get_servarr_extended, son_url, son_key, "sonarr") if son_url else None
    rad_cal_fut = _pool.submit(get_servarr_calendar, rad_url, rad_key) if rad_url else None
    son_cal_fut = _pool.submit(get_servarr_calendar, son_url, son_key) if son_url else None
    nc_fut      = _pool.submit(get_nextcloud, nc_url, nc_user, nc_pass) if nc_url and nc_user else None
    traefik_fut = _pool.submit(get_traefik, traefik_url) if traefik_url else None
    npm_fut     = _pool.submit(get_npm, npm_url, npm_tok) if npm_url and npm_tok else None
    ak_fut      = _pool.submit(get_authentik, ak_url, ak_tok) if ak_url else None
    cf_fut      = _pool.submit(get_cloudflare, cf_tok, cf_zone) if cf_tok else None
    omv_fut     = _pool.submit(get_omv, omv_url, omv_user, omv_pass) if omv_url else None
    xcp_fut     = _pool.submit(get_xcpng, xcp_url, xcp_user, xcp_pass) if xcp_url else None
    hb_fut      = _pool.submit(get_homebridge, hb_url, hb_user, hb_pass) if hb_url else None
    z2m_fut     = _pool.submit(get_z2m, z2m_url) if z2m_url else None
    esp_fut     = _pool.submit(get_esphome, esp_url) if esp_url else None
    protect_fut = _pool.submit(get_unifi_protect, protect_url, protect_user, protect_pass) if protect_url else None
    pikvm_fut   = _pool.submit(get_pikvm, pikvm_url, pikvm_user, pikvm_pass) if pikvm_url else None
    k8s_fut     = _pool.submit(get_k8s, k8s_url, k8s_tok) if k8s_url else None
    gitea_fut   = _pool.submit(get_gitea, gitea_url, gitea_tok) if gitea_url else None
    gitlab_fut  = _pool.submit(get_gitlab, gitlab_url, gitlab_tok) if gitlab_url else None
    github_fut  = _pool.submit(get_github, github_tok) if github_tok else None
    paperless_fut = _pool.submit(get_paperless, paperless_url, paperless_tok) if paperless_url else None
    vw_fut      = _pool.submit(get_vaultwarden, vw_url, vw_tok) if vw_url else None
    weather_fut = _pool.submit(get_weather, weather_key, weather_city) if weather_key and weather_city else None
    cert_fut    = _pool.submit(check_cert_expiry, cert_hosts) if cert_hosts else None
    domain_fut  = _pool.submit(check_domain_expiry, domain_list) if domain_list else None
    vpn_fut     = _pool.submit(get_vpn_status)
    presence_fut = _pool.submit(check_device_presence, presence_ips) if presence_ips else None
    scrutiny_fut = _pool.submit(get_scrutiny, scrutiny_url) if scrutiny_url else None
    energy_fut   = _pool.submit(get_energy_shelly, energy_urls) if energy_urls else None

    # Docker image update check — only every 5th cycle to avoid registry spam
    global _docker_update_cycle
    docker_upd_fut = None
    with _docker_update_lock:
        _docker_update_cycle += 1
        if _docker_update_cycle >= 5:
            _docker_update_cycle = 0
            docker_upd_fut = _pool.submit(check_docker_updates)

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

    def _cached_get(fut, cache_key, timeout=4, default=None, ttl=30):
        """Get a future result with optional cache layer."""
        if _cache.is_redis and cache_key:
            cached = _cache.get(cache_key)
            if cached is not None:
                return cached
        result = _get(fut, timeout, default)
        if _cache.is_redis and cache_key and result is not None:
            _cache.set(cache_key, result, ttl=ttl)
        return result

    stats["kuma"]       = _get(kuma_fut, default=[])
    stats["pihole"]     = _get(ph_fut)
    stats["plex"]       = _get(plex_fut)
    stats["containers"] = _get(ct_fut, timeout=5, default=[])
    stats["truenas"]    = _cached_get(tn_fut, "noba:int:truenas", timeout=5, ttl=15)
    stats["radarr"]     = _get(rad_fut)
    stats["sonarr"]     = _get(son_fut)
    stats["qbit"]       = _get(qbit_fut)
    stats["proxmox"]    = _cached_get(pmx_fut, "noba:int:proxmox", timeout=6, ttl=15)
    stats["adguard"]    = _get(ag_fut)
    stats["jellyfin"]   = _get(jf_fut)
    stats["hass"]       = _get(hass_fut)
    stats["unifi"]      = _cached_get(unifi_fut, "noba:int:unifi", ttl=15)
    stats["speedtest"]  = _get(spd_fut)

    # New integration results
    stats["tautulli"]       = _get(tau_fut)
    stats["overseerr"]      = _get(ovs_fut)
    stats["prowlarr"]       = _get(prowl_fut)
    stats["lidarr"]         = _get(lidarr_fut)
    stats["readarr"]        = _get(readarr_fut)
    stats["bazarr"]         = _get(bazarr_fut)
    stats["radarrExtended"] = _get(rad_ext_fut)
    stats["sonarrExtended"] = _get(son_ext_fut)
    stats["radarrCalendar"] = _get(rad_cal_fut, default=[])
    stats["sonarrCalendar"] = _get(son_cal_fut, default=[])
    stats["nextcloud"]      = _cached_get(nc_fut, "noba:int:nextcloud", ttl=30)
    stats["traefik"]        = _get(traefik_fut)
    stats["npm"]            = _get(npm_fut)
    stats["authentik"]      = _get(ak_fut)
    stats["cloudflare"]     = _cached_get(cf_fut, "noba:int:cloudflare", ttl=60)
    stats["omv"]            = _get(omv_fut)
    stats["xcpng"]          = _cached_get(xcp_fut, "noba:int:xcpng", timeout=6, ttl=15)
    stats["homebridge"]     = _get(hb_fut)
    stats["z2m"]            = _get(z2m_fut)
    stats["esphome"]        = _get(esp_fut)
    stats["unifiProtect"]   = _get(protect_fut)
    stats["pikvm"]          = _get(pikvm_fut)
    stats["k8s"]            = _cached_get(k8s_fut, "noba:int:k8s", ttl=15)
    stats["gitea"]          = _get(gitea_fut)
    stats["gitlab"]         = _get(gitlab_fut)
    stats["github"]         = _get(github_fut)
    stats["paperless"]      = _get(paperless_fut)
    stats["vaultwarden"]    = _get(vw_fut)
    stats["weather"]        = _get(weather_fut)
    stats["certExpiry"]     = _get(cert_fut, default=[])
    stats["domainExpiry"]   = _get(domain_fut, default=[])
    stats["vpn"]            = _get(vpn_fut)
    stats["dockerUpdates"]  = _get(docker_upd_fut, default=[])
    stats["devicePresence"] = _get(presence_fut, default=[])
    stats["scrutiny"]       = _get(scrutiny_fut)
    stats["energy"]         = _get(energy_fut, default=[])

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
        for cert in (stats.get("certExpiry") or []):
            if cert.get("days") is not None:
                batch.append(("cert_expiry_days", cert["days"], cert.get("host", "")))
        db.insert_metrics(batch)
    except Exception as e:
        logger.error("History insert failed: %s", e)

    # Snapshot top processes for history
    try:
        snapshot_top_processes()
    except Exception:
        pass

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
