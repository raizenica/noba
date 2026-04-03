# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Background stats collector and assembly."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait as _wait_futures
from datetime import datetime

from .config import STATS_INTERVAL, _WORKER_THREADS
from .db import db
from .metrics import (
    collect_system, collect_hardware, collect_storage, collect_network,
    get_cpu_percent, get_cpu_history, get_service_status, ping_host, get_containers,
    collect_disk_io, collect_per_interface_net,
    check_cert_expiry, check_device_presence, check_domain_expiry, get_vpn_status,
    check_docker_updates, snapshot_top_processes, get_tailscale_status,
)
from .integrations import (
    get_pihole, get_plex, get_kuma, get_truenas, get_servarr, get_qbit, get_proxmox,
    get_adguard, get_jellyfin, get_hass, get_unifi, get_speedtest,
    get_tautulli, get_overseerr, get_prowlarr, get_servarr_extended, get_servarr_calendar,
    get_nextcloud, get_traefik, get_npm, get_authentik, get_cloudflare, get_omv, get_xcpng,
    get_homebridge, get_z2m, get_esphome, get_unifi_protect, get_pikvm, get_k8s,
    get_gitea, get_gitlab, get_github, get_paperless, get_vaultwarden, get_weather,
    get_energy_shelly, get_scrutiny, get_frigate,
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

    svc_raw   = _qs0("services") or cfg.get("monitoredServices", "")
    svc_list  = [s.strip() for s in svc_raw.split(",") if s.strip()]
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
    frigate_url  = cfg.get("frigateUrl", "")
    pihole_pass  = cfg.get("piholePassword", "")
    n8n_url      = cfg.get("n8nUrl", "")
    n8n_key      = cfg.get("n8nApiKey", "")

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

    ph_fut    = _pool.submit(get_pihole,  ph_url, ph_tok, pihole_pass) if ph_url else None
    plex_fut  = _pool.submit(get_plex,    plex_url, plex_tok) if plex_url else None
    kuma_fut  = _pool.submit(get_kuma,    kuma_url)          if kuma_url else None
    ct_fut    = _pool.submit(get_containers)
    tn_fut    = _pool.submit(get_truenas, tn_url, tn_key)    if tn_url  else None
    rad_fut   = _pool.submit(get_servarr, rad_url, rad_key)  if rad_url else None
    son_fut   = _pool.submit(get_servarr, son_url, son_key)  if son_url else None
    qbit_fut  = _pool.submit(get_qbit,   qbit_url, qbit_user, qbit_pass) if qbit_url else None
    pmx_verify = cfg.get("proxmoxVerifySsl", True)
    pmx_fut   = _pool.submit(get_proxmox, pmx_url, pmx_user, pmx_tname, pmx_tval, pmx_verify) if pmx_url else None
    ag_fut    = _pool.submit(get_adguard, ag_url, ag_user, ag_pass) if ag_url else None
    jf_fut    = _pool.submit(get_jellyfin, jf_url, jf_key) if jf_url else None
    hass_fut  = _pool.submit(get_hass, hass_url, hass_tok) if hass_url else None
    _unifi_ssl = cfg.get("unifiVerifySsl", False)  # default False: UniFi uses self-signed certs
    unifi_fut = _pool.submit(get_unifi, unifi_url, unifi_user, unifi_pass, unifi_site, verify_ssl=_unifi_ssl) if unifi_url else None
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
    _protect_ssl = cfg.get("unifiProtectVerifySsl", False)
    protect_fut = _pool.submit(get_unifi_protect, protect_url, protect_user, protect_pass, verify_ssl=_protect_ssl) if protect_url else None
    pikvm_fut   = _pool.submit(get_pikvm, pikvm_url, pikvm_user, pikvm_pass) if pikvm_url else None
    _k8s_ssl = cfg.get("k8sVerifySsl", True)
    k8s_fut     = _pool.submit(get_k8s, k8s_url, k8s_tok, verify_ssl=_k8s_ssl) if k8s_url else None
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
    frigate_fut  = _pool.submit(get_frigate, frigate_url) if frigate_url else None
    tailscale_fut = _pool.submit(get_tailscale_status)
    if n8n_url:
        from .integrations.n8n import collect_n8n
        n8n_fut = _pool.submit(collect_n8n, n8n_url, n8n_key)
    else:
        n8n_fut = None

    # Docker image update check — only every 5th cycle to avoid registry spam
    global _docker_update_cycle
    docker_upd_fut = None
    with _docker_update_lock:
        _docker_update_cycle += 1
        if _docker_update_cycle >= 5:
            _docker_update_cycle = 0
            docker_upd_fut = _pool.submit(check_docker_updates)

    # ── Wait for ALL futures with a single global timeout ───────────────────
    _all_futs = [f for f in [
        wan_fut, lan_fut, ph_fut, plex_fut, kuma_fut, ct_fut, tn_fut,
        rad_fut, son_fut, qbit_fut, pmx_fut, ag_fut, jf_fut, hass_fut,
        unifi_fut, spd_fut, tau_fut, ovs_fut, prowl_fut, lidarr_fut,
        readarr_fut, bazarr_fut, rad_ext_fut, son_ext_fut, rad_cal_fut,
        son_cal_fut, nc_fut, traefik_fut, npm_fut, ak_fut, cf_fut,
        omv_fut, xcp_fut, hb_fut, z2m_fut, esp_fut, protect_fut,
        pikvm_fut, k8s_fut, gitea_fut, gitlab_fut, github_fut,
        paperless_fut, vw_fut, weather_fut, cert_fut, domain_fut,
        vpn_fut, docker_upd_fut, presence_fut, scrutiny_fut, energy_fut,
        frigate_fut, tailscale_fut, n8n_fut,
        *svc_futs.keys(), *ping_futs.keys(), *bmc_futs.keys(),
    ] if f is not None]
    _done, _not_done = _wait_futures(_all_futs, timeout=4.5)

    # ── Collect service status results ────────────────────────────────────────
    services = []
    for fut, svc in svc_futs.items():
        if fut in _done:
            try:
                status, is_user = fut.result(timeout=0)
            except Exception as e:
                logger.warning("Service status check failed for %s: %s", svc, e)
                status, is_user = "error", False
        else:
            status, is_user = "error", False
        services.append({"name": svc, "status": status, "is_user": is_user})
    stats["services"] = services

    # ── Collect ping results ──────────────────────────────────────────────────
    radar = []
    for fut, ip in ping_futs.items():
        if fut in _done:
            try:
                ip_r, up, ms = fut.result(timeout=0)
                radar.append({"ip": ip_r, "status": "Up" if up else "Down", "ms": ms if up else 0})
                continue
            except Exception as e:
                logger.warning("Ping check failed for %s: %s", ip, e)
        radar.append({"ip": ip, "status": "Down", "ms": 0})
    stats["radar"] = radar

    # ── Net health ────────────────────────────────────────────────────────────
    stats["netHealth"] = {"wan": "Down", "lan": "Down", "configured": bool(wan_ip or lan_ip)}
    if wan_fut and wan_fut in _done:
        try:
            _, wan_up, _ = wan_fut.result(timeout=0)
            stats["netHealth"]["wan"] = "Up" if wan_up else "Down"
        except Exception as e:
            logger.warning("WAN health check failed: %s", e)
    if lan_fut and lan_fut in _done:
        try:
            _, lan_up, _ = lan_fut.result(timeout=0)
            stats["netHealth"]["lan"] = "Up" if lan_up else "Down"
        except Exception as e:
            logger.warning("LAN health check failed: %s", e)

    # ── Integration results ───────────────────────────────────────────────────
    from .integrations.base import ConfigError, TransientError

    def _get(fut, name=None, default=None):
        if fut is None:
            return default
        if fut not in _done:
            return {"status": "timeout", "error": "Request timed out"}
        try:
            res = fut.result(timeout=0)
            if res is None:
                return default
            return res
        except ConfigError as e:
            logger.error("Config error in %s: %s", name or "integration", e)
            return {"status": "unauthorized", "error": "Configuration error"}
        except (TransientError, Exception) as e:
            logger.warning("Transient error in %s: %s", name or "integration", e)
            return {"status": "offline", "error": "Connection failed"}

    def _cached_get(fut, cache_key, name=None, default=None, ttl=30):
        """Get a future result with optional cache layer."""
        if _cache.is_redis and cache_key:
            cached = _cache.get(cache_key)
            if cached is not None:
                return cached
        result = _get(fut, name=name, default=default)
        # Cache successful or offline results, but not ConfigErrors (which require user action)
        if _cache.is_redis and cache_key and result is not None:
            if isinstance(result, dict) and result.get("status") != "unauthorized":
                _cache.set(cache_key, result, ttl=ttl)
        return result

    stats["kuma"]       = _get(kuma_fut, name="Uptime Kuma", default=[])
    stats["pihole"]     = _get(ph_fut, name="Pi-hole")
    stats["plex"]       = _get(plex_fut, name="Plex")
    stats["containers"] = _get(ct_fut, name="Containers", default=[])
    stats["truenas"]    = _cached_get(tn_fut, "noba:int:truenas", name="TrueNAS", ttl=15)
    stats["radarr"]     = _get(rad_fut, name="Radarr")
    stats["sonarr"]     = _get(son_fut, name="Sonarr")
    stats["qbit"]       = _get(qbit_fut, name="qBittorrent")
    stats["proxmox"]    = _cached_get(pmx_fut, "noba:int:proxmox", name="Proxmox", ttl=15)
    stats["adguard"]    = _get(ag_fut, name="AdGuard")
    stats["jellyfin"]   = _get(jf_fut, name="Jellyfin")
    stats["hass"]       = _get(hass_fut, name="Home Assistant")
    stats["unifi"]      = _cached_get(unifi_fut, "noba:int:unifi", name="UniFi", ttl=15)
    stats["speedtest"]  = _get(spd_fut, name="Speedtest")

    # New integration results
    stats["tautulli"]       = _get(tau_fut, name="Tautulli")
    stats["overseerr"]      = _get(ovs_fut, name="Overseerr")
    stats["prowlarr"]       = _get(prowl_fut, name="Prowlarr")
    stats["lidarr"]         = _get(lidarr_fut, name="Lidarr")
    stats["readarr"]        = _get(readarr_fut, name="Readarr")
    stats["bazarr"]         = _get(bazarr_fut, name="Bazarr")
    stats["radarrExtended"] = _get(rad_ext_fut, name="Radarr Extended")
    stats["sonarrExtended"] = _get(son_ext_fut, name="Sonarr Extended")
    stats["radarrCalendar"] = _get(rad_cal_fut, name="Radarr Calendar", default=[])
    stats["sonarrCalendar"] = _get(son_cal_fut, name="Sonarr Calendar", default=[])
    stats["nextcloud"]      = _cached_get(nc_fut, "noba:int:nextcloud", name="Nextcloud", ttl=30)
    stats["traefik"]        = _get(traefik_fut, name="Traefik")
    stats["npm"]            = _get(npm_fut, name="NPM")
    stats["authentik"]      = _get(ak_fut, name="Authentik")
    stats["cloudflare"]     = _cached_get(cf_fut, "noba:int:cloudflare", name="Cloudflare", ttl=60)
    stats["omv"]            = _get(omv_fut, name="OpenMediaVault")
    stats["xcpng"]          = _cached_get(xcp_fut, "noba:int:xcpng", name="XCP-ng", ttl=15)
    stats["homebridge"]     = _get(hb_fut, name="Homebridge")
    stats["z2m"]            = _get(z2m_fut, name="Zigbee2MQTT")
    stats["esphome"]        = _get(esp_fut, name="ESPHome")
    stats["unifiProtect"]   = _get(protect_fut, name="UniFi Protect")
    stats["pikvm"]          = _get(pikvm_fut, name="PiKVM")
    stats["k8s"]            = _cached_get(k8s_fut, "noba:int:k8s", name="K8s", ttl=15)
    stats["gitea"]          = _get(gitea_fut, name="Gitea")
    stats["gitlab"]         = _get(gitlab_fut, name="GitLab")
    stats["github"]         = _get(github_fut, name="GitHub")
    stats["paperless"]      = _get(paperless_fut, name="Paperless")
    stats["vaultwarden"]    = _get(vw_fut, name="Vaultwarden")
    stats["weather"]        = _get(weather_fut, name="Weather")
    stats["certExpiry"]     = _get(cert_fut, name="Cert Expiry", default=[])
    stats["domainExpiry"]   = _get(domain_fut, name="Domain Expiry", default=[])
    stats["vpn"]            = _get(vpn_fut, name="VPN")
    stats["dockerUpdates"]  = _get(docker_upd_fut, name="Docker Updates", default=[])
    stats["devicePresence"] = _get(presence_fut, name="Device Presence", default=[])
    stats["scrutiny"]       = _get(scrutiny_fut, name="Scrutiny")
    stats["energy"]         = _get(energy_fut, name="Energy", default=[])
    stats["frigate"]        = _get(frigate_fut, name="Frigate")
    stats["tailscale"]      = _get(tailscale_fut, name="Tailscale")
    stats["n8n"]            = _get(n8n_fut, name="n8n")

    # ── Managed integration instances ─────────────────────────────────────────
    # Collect data for instances registered via /api/integrations/instances.
    # Results are stored under stats["instances"][instance_id] so the frontend
    # IntegrationCard can find them via dashboardStore.live.instances[id].
    try:
        import json as _json
        _inst_list = db.list_integration_instances()
        def _fetch_truenas(url, ac):
            key = ac.get("api_key") or ac.get("token") or ac.get("apikey_env") or ac.get("apikey") or ""
            raw = get_truenas(url, key)
            if not raw:
                return raw
            pools  = raw.get("pools", [])
            apps   = raw.get("apps", [])
            alerts = raw.get("alerts", [])
            return {
                **raw,
                "pool_status":  (pools[0]["status"].lower() if pools else "unknown"),
                "pool_healthy": all(p.get("healthy") for p in pools),
                "app_count":    len(apps),
                "running_apps": sum(1 for a in apps if a.get("state") == "RUNNING"),
                "alert_count":  len(alerts),
            }

        def _fetch_proxmox(url, ac):
            raw = get_proxmox(
                url,
                ac.get("user") or ac.get("username") or "",
                ac.get("token_name") or ac.get("tokenName") or "",
                ac.get("token_value") or ac.get("tokenValue") or ac.get("token") or "",
            )
            if not raw:
                return raw
            nodes = raw.get("nodes", [])
            n = nodes[0] if nodes else {}
            return {
                **raw,
                "node_status": n.get("status", "offline"),
                "cpu_percent": n.get("cpu", 0),
                "mem_percent": n.get("mem_percent", 0),
                "vm_count":    len(raw.get("vms", [])),
            }

        def _fetch_pihole(url, ac):
            raw = get_pihole(url, ac.get("token") or ac.get("api_key") or "", ac.get("password") or "")
            if not raw:
                return raw
            return {
                **raw,
                "queries_today":        raw.get("queries", 0),
                "ads_blocked_today":    raw.get("blocked", 0),
                "ads_percentage_today": raw.get("percent", 0),
                "status":               raw.get("status", "online"),
            }

        def _fetch_adguard(url, ac):
            raw = get_adguard(url, ac.get("username") or ac.get("user") or "", ac.get("password") or "")
            if not raw:
                return raw
            return {
                **raw,
                "num_dns_queries":       raw.get("queries", 0),
                "num_blocked_filtering": raw.get("blocked", 0),
            }

        def _fetch_plex(url, ac):
            raw = get_plex(url, ac.get("token") or ac.get("api_key") or "")
            if not raw:
                return raw
            return {**raw, "connections": raw.get("sessions", 0)}

        def _fetch_jellyfin(url, ac):
            raw = get_jellyfin(url, ac.get("api_key") or ac.get("token") or "")
            if not raw:
                return raw
            return {
                **raw,
                "movie_count":  raw.get("movies", 0),
                "series_count": raw.get("series", 0),
            }

        def _fetch_kuma(url, ac):
            raw = get_kuma(url)
            if not isinstance(raw, list):
                return None
            up   = sum(1 for m in raw if m.get("status") == "Up")
            down = len(raw) - up
            return {"monitors": raw, "monitors_up": up, "monitors_down": down,
                    "status": "online" if raw else "offline"}

        def _fetch_unifi(url, ac):
            raw = get_unifi(
                url,
                ac.get("username") or ac.get("user") or "",
                ac.get("password") or "",
                ac.get("site") or "default",
            )
            if not raw:
                return raw
            return {
                **raw,
                "num_ap":      raw.get("adopted", 0),
                "num_clients": raw.get("clients", 0),
            }

        _PLATFORM_FETCHERS = {
            "truenas":  _fetch_truenas,
            "proxmox":  _fetch_proxmox,
            "pihole":   _fetch_pihole,
            "adguard":  _fetch_adguard,
            "plex":     _fetch_plex,
            "jellyfin": _fetch_jellyfin,
            "kuma":     _fetch_kuma,
            "uptimekuma": _fetch_kuma,
            "unifi":    _fetch_unifi,
        }
        _inst_futs: dict[str, object] = {}
        for _inst in _inst_list:
            _platform = _inst.get("platform", "")
            _fetcher = _PLATFORM_FETCHERS.get(_platform)
            if not _fetcher:
                continue
            _url = _inst.get("url", "")
            _raw_ac = _inst.get("auth_config", "{}")
            try:
                _ac = _json.loads(_raw_ac) if isinstance(_raw_ac, str) else (_raw_ac or {})
            except Exception:
                _ac = {}
            if _url:
                _inst_futs[_inst["id"]] = _pool.submit(_fetcher, _url, _ac)
        _instances_data: dict = {}
        for _iid, _fut in _inst_futs.items():
            try:
                _result = _fut.result(timeout=15)
                if _result:
                    _instances_data[_iid] = _result
            except Exception as _e:
                logger.debug("Managed instance %s fetch failed: %s", _iid, _e)
        stats["instances"] = _instances_data
    except Exception as _e:
        logger.warning("Managed instances collection failed: %s", _e)
        stats["instances"] = {}

    stats.update(collect_disk_io())
    stats.update(collect_per_interface_net())

    # ── Agent data ────────────────────────────────────────────────────────────
    try:
        from .agent_store import _agent_data, _agent_data_lock, _AGENT_MAX_AGE
        now_a = time.time()
        with _agent_data_lock:
            agent_list = []
            for hn, adata in _agent_data.items():
                age = now_a - adata.get("_received", 0)
                agent_list.append({
                    "hostname": hn,
                    "cpu_percent": adata.get("cpu_percent", 0),
                    "mem_percent": adata.get("mem_percent", 0),
                    "online": age < _AGENT_MAX_AGE,
                    "last_seen_s": int(age),
                    "platform": adata.get("platform", ""),
                    "uptime_s": adata.get("uptime_s", 0),
                    "disks": adata.get("disks", []),
                    "top_processes": adata.get("top_processes", []),
                    "arch": adata.get("arch", ""),
                    "agent_version": adata.get("agent_version", ""),
                })
            stats["agents"] = agent_list
    except ImportError:
        stats["agents"] = []

    # ── Alerts ────────────────────────────────────────────────────────────────
    stats["alerts"] = build_threshold_alerts(stats, read_yaml_settings)
    stats["alerts"].extend(check_anomalies(db, read_yaml_settings))

    # ── BMC sentinel ─────────────────────────────────────────────────────────
    for fut, (os_ip, bmc_ip) in bmc_futs.items():
        if fut not in _done:
            continue
        try:
            _, bmc_up, _ = fut.result(timeout=0)
            os_status = next((r["status"] for r in radar if r["ip"] == os_ip), None)
            if os_status == "Down" and bmc_up:
                stats["alerts"].append({
                    "level": "danger",
                    "msg":   f"BMC Sentinel: {os_ip} OS offline, BMC ({bmc_ip}) reachable!",
                })
        except Exception as e:
            logger.warning("BMC sentinel check failed for %s: %s", os_ip, e)

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
        now_s = int(time.time())
        if now_s % 60 < STATS_INTERVAL:  # roughly once per minute
            db.rollup_to_1m()
        if now_s % 3600 < STATS_INTERVAL:  # roughly once per hour
            db.rollup_to_1h()
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
        self._last_tick = 0.0

    def update_qs(self, qs: dict) -> None:
        with self._lock:
            self._qs = dict(qs)

    def get(self) -> dict:
        with self._lock:
            return self._latest

    def get_pulse(self) -> float:
        """Return the time in seconds since the last collection tick."""
        with self._lock:
            if self._last_tick == 0:
                return 0
            return time.time() - self._last_tick

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
                    self._last_tick = time.time()
            except Exception as e:
                logger.warning("Collector error: %s", e)
            _shutdown_flag.wait(self._interval)


# Singleton
bg_collector = BackgroundCollector()
