# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Simple integrations (re-exports from category modules).

CF-9 note: each category module now imports its per-category httpx client
directly from ``.base`` via ``get_category_client(...)``. The old monkey-patch
loop that overwrote ``_http_get`` / ``_client`` on each sibling module has
been removed — it predated per-category pools and would now *undo* the
bulkheading by forcing every module to share a single client.

Tests that previously patched ``server.integrations.simple_XXX._client``
continue to work: each module still exposes a module-level ``_client`` (or
category-specific ``_nas_client`` / ``_git_devops_client`` / etc. in
``simple_infra.py``) for mocking purposes.
"""
# isort: skip_file
from __future__ import annotations

from .base import _client, _http_get

# Import category modules — no monkey-patching needed; each module imports
# its own per-category httpx client from .base at module load.
from . import simple_comms  # noqa: E402,F401
from . import simple_infra  # noqa: E402,F401
from . import simple_iot  # noqa: E402,F401
from . import simple_media  # noqa: E402,F401
from . import simple_monitoring  # noqa: E402,F401
from . import simple_network  # noqa: E402,F401

# Now re-export the actual function implementations
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
