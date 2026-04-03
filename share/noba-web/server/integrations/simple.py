# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Simple integrations (re-exports from category modules)."""
from __future__ import annotations

from .base import _client, _http_get

# Import category modules and monkey-patch their _http_get
# This allows tests to patch at simple._http_get and affect all implementations
from . import simple_media  # noqa: E402
from . import simple_network  # noqa: E402
from . import simple_infra  # noqa: E402
from . import simple_monitoring  # noqa: E402
from . import simple_iot  # noqa: E402
from . import simple_comms  # noqa: E402

for mod in [simple_media, simple_network, simple_infra, simple_monitoring, simple_iot, simple_comms]:
    mod._http_get = _http_get
    if hasattr(mod, '_client'):
        mod._client = _client

# Now import the actual function implementations
from .simple_comms import get_authentik  # noqa: E402
from .simple_infra import (  # noqa: E402
    get_gitea, get_github, get_gitlab, get_k8s, get_omv,
    get_paperless, get_truenas, get_vaultwarden, get_xcpng,
)
from .simple_iot import get_esphome, get_homebridge, get_pikvm, get_z2m  # noqa: E402
from .simple_media import (  # noqa: E402
    get_jellyfin, get_nextcloud, get_overseerr, get_plex, get_prowlarr,
    get_servarr, get_servarr_calendar, get_servarr_extended, get_tautulli,
)
from .simple_monitoring import (  # noqa: E402
    get_energy_shelly, get_frigate, get_graylog, get_kuma, get_scrutiny,
    get_scrutiny_intelligence, get_speedtest, get_weather, query_influxdb,
)
from .simple_network import get_adguard, get_cloudflare, get_npm, get_traefik  # noqa: E402

__all__ = [
    "get_plex", "get_jellyfin", "get_tautulli", "get_overseerr", "get_prowlarr",
    "get_servarr", "get_servarr_extended", "get_servarr_calendar", "get_nextcloud",
    "get_adguard", "get_cloudflare", "get_npm", "get_traefik",
    "get_truenas", "get_omv", "get_xcpng", "get_k8s",
    "get_gitea", "get_gitlab", "get_github", "get_paperless", "get_vaultwarden",
    "get_kuma", "get_scrutiny", "get_scrutiny_intelligence", "get_speedtest",
    "get_frigate", "get_graylog", "query_influxdb", "get_weather", "get_energy_shelly",
    "get_homebridge", "get_z2m", "get_esphome", "get_pikvm", "get_authentik",
    "_client", "_http_get",
]
