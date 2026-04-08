# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba integrations package — re-exports for backward compatibility."""
from __future__ import annotations

# Re-export httpx for tests that patch server.integrations.httpx.*
import httpx  # noqa: F401

# Shared infrastructure
from .base import (  # noqa: F401
    BaseIntegration,
    ConfigError,
    TransientError,
    _client,
    _http_get,
)

# Home Assistant (Bearer token)
from .hass import get_hass, get_hass_entities, get_hass_services  # noqa: F401

# Pi-hole (v6/v5 fallback with session caching)
from .pihole import get_pihole  # noqa: F401

# Proxmox VE (PVEAPIToken auth)
from .proxmox import get_proxmox  # noqa: F401

# qBittorrent (dedicated client for form login + cookie session)
from .qbittorrent import get_qbit  # noqa: F401

# Simple integrations (shared _client, no-auth / header-token / basic-auth)
from .simple import (  # noqa: F401
    get_adguard,
    get_authentik,
    get_cloudflare,
    get_energy_shelly,
    get_esphome,
    get_frigate,
    get_gitea,
    get_github,
    get_gitlab,
    get_graylog,
    get_homebridge,
    get_jellyfin,
    get_k8s,
    get_kuma,
    get_nextcloud,
    get_npm,
    get_omv,
    get_overseerr,
    get_paperless,
    get_pikvm,
    get_plex,
    get_prowlarr,
    get_scrutiny,
    get_scrutiny_intelligence,
    get_servarr,
    get_servarr_calendar,
    get_servarr_extended,
    get_speedtest,
    get_tautulli,
    get_traefik,
    get_vaultwarden,
    get_weather,
    get_xcpng,
    get_z2m,
    query_influxdb,
)
from .simple import (
    get_truenas as _get_truenas_rest,  # noqa: F401  # legacy REST — kept as fallback
)

# TrueNAS (JSON-RPC 2.0 over WebSocket, with REST fallback)
from .truenas_ws import get_truenas  # noqa: F401

# UniFi (dedicated httpx clients for cookie-based auth)
from .unifi import get_unifi, get_unifi_protect  # noqa: F401
