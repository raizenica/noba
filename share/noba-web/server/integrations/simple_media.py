# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Media integrations."""
from __future__ import annotations

import logging
from datetime import date, timedelta
import httpx

from .base import ConfigError, TransientError, _http_get


logger = logging.getLogger("noba")



# ── Plex ──────────────────────────────────────────────────────────────────────
def get_plex(url: str, token: str) -> dict | None:
    if not url or not token:
        return None
    base = url.rstrip("/")
    hdrs = {"Accept": "application/json", "X-Plex-Token": token}
    try:
        data1    = _http_get(f"{base}/status/sessions", hdrs, timeout=3)
        sessions = data1.get("MediaContainer", {}).get("size", 0)
        data2      = _http_get(f"{base}/activities", hdrs, timeout=3)
        activities = data2.get("MediaContainer", {}).get("size", 0)
        return {"sessions": sessions, "activities": activities, "status": "online"}
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"sessions": 0, "activities": 0, "status": "offline", "error": str(e)}





# ── Jellyfin ─────────────────────────────────────────────────────────────────
def get_jellyfin(url: str, key: str):
    if not url or not key:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"X-Emby-Token": key}
        sessions = _http_get(f"{base}/Sessions", hdrs)
        counts = _http_get(f"{base}/Items/Counts", hdrs)
        playing = sum(1 for s in (sessions or []) if s.get("NowPlayingItem"))
        return {
            "streams": playing,
            "movies": (counts or {}).get("MovieCount", 0),
            "series": (counts or {}).get("SeriesCount", 0),
            "episodes": (counts or {}).get("EpisodeCount", 0),
            "status": "online",
        }
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"streams": 0, "status": "offline", "error": str(e)}


# ── Tautulli ─────────────────────────────────────────────────────────────────



# ── Tautulli ─────────────────────────────────────────────────────────────────
def get_tautulli(url: str, key: str) -> dict | None:
    if not url or not key:
        return None
    try:
        base = url.rstrip("/")
        activity = _http_get(
            f"{base}/api/v2?apikey={key}&cmd=get_activity", timeout=4,
        )
        resp = activity.get("response", {}).get("data", {})
        streams = resp.get("stream_count", 0)
        direct_play = resp.get("stream_count_direct_play", 0)
        transcode = resp.get("stream_count_transcode", 0)

        top_users_data = _http_get(
            f"{base}/api/v2?apikey={key}&cmd=get_home_stats&stat_id=top_users&stats_count=5",
            timeout=4,
        )
        top_resp = top_users_data.get("response", {}).get("data", [])
        top_users = []
        # top_resp may be a list of stat groups or a flat list
        rows = top_resp if isinstance(top_resp, list) else []
        for item in rows:
            if isinstance(item, dict) and "rows" in item:
                # stat group format
                for row in item["rows"]:
                    top_users.append({
                        "user": row.get("friendly_name", row.get("user", "?")),
                        "total_plays": int(row.get("total_plays", 0)),
                    })
                break
            elif isinstance(item, dict) and "friendly_name" in item:
                top_users.append({
                    "user": item.get("friendly_name", "?"),
                    "total_plays": int(item.get("total_plays", 0)),
                })

        return {
            "streams": int(streams),
            "stream_count_direct_play": int(direct_play),
            "stream_count_transcode": int(transcode),
            "top_users": top_users,
            "status": "online",
        }
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}


# ── Overseerr ────────────────────────────────────────────────────────────────



# ── Overseerr ────────────────────────────────────────────────────────────────
def get_overseerr(url: str, key: str) -> dict | None:
    if not url or not key:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"X-Api-Key": key}
        data = _http_get(f"{base}/api/v1/request/count", hdrs)
        return {
            "pending": data.get("pending", 0),
            "approved": data.get("approved", 0),
            "available": data.get("available", 0),
            "total": data.get("total", 0),
            "status": "online",
        }
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}




# ── Prowlarr ─────────────────────────────────────────────────────────────────
def get_prowlarr(url: str, key: str) -> dict | None:
    if not url or not key:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"X-Api-Key": key}
        data = _http_get(f"{base}/api/v1/indexer", hdrs)
        return {
            "indexer_count": len(data) if isinstance(data, list) else 0,
            "status": "online",
        }
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





# ── Servarr (Radarr / Sonarr) ─────────────────────────────────────────────────
def get_servarr(url: str, key: str) -> dict | None:
    if not url or not key:
        return None
    hdrs = {"X-Api-Key": key, "Accept": "application/json"}
    try:
        data = _http_get(f"{url.rstrip('/')}/api/v3/queue", hdrs, timeout=3)
        return {"queue_count": data.get("totalRecords", 0), "status": "online"}
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"queue_count": 0, "status": "offline", "error": str(e)}





# ── Servarr Extended (Radarr / Sonarr — missing + disk) ──────────────────────
def get_servarr_extended(url: str, key: str, service: str = "radarr") -> dict | None:
    if not url or not key:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"X-Api-Key": key, "Accept": "application/json"}

        queue = _http_get(f"{base}/api/v3/queue", hdrs, timeout=3)
        queue_count = queue.get("totalRecords", 0)

        missing_data = _http_get(
            f"{base}/api/v3/wanted/missing?pageSize=1", hdrs, timeout=3,
        )
        missing = missing_data.get("totalRecords", 0)

        rootfolders = _http_get(f"{base}/api/v3/rootfolder", hdrs, timeout=3)
        total_space = 0.0
        free_space = 0.0
        for rf in (rootfolders if isinstance(rootfolders, list) else []):
            total_space += rf.get("totalSpace", 0)
            free_space += rf.get("freeSpace", 0)

        return {
            "queue_count": queue_count,
            "missing": missing,
            "total_space_gb": round(total_space / (1024 ** 3), 1),
            "free_space_gb": round(free_space / (1024 ** 3), 1),
            "status": "online",
            "service": service,
        }
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





# ── Servarr Calendar (Radarr / Sonarr) ───────────────────────────────────────
def get_servarr_calendar(url: str, key: str, days: int = 7) -> list | None:
    if not url or not key:
        return None
    try:
        base = url.rstrip("/")
        hdrs = {"X-Api-Key": key, "Accept": "application/json"}
        today = date.today().isoformat()
        end = (date.today() + timedelta(days=days)).isoformat()
        data = _http_get(f"{base}/api/v3/calendar?start={today}&end={end}", hdrs, timeout=4)
        items = []
        for entry in (data if isinstance(data, list) else []):
            title = entry.get("title", "")
            # Sonarr entries have 'series' and 'episodeFile'; Radarr have 'title'
            if "series" in entry:
                title = entry.get("series", {}).get("title", title)
                item_type = "episode"
                air_date = entry.get("airDateUtc", entry.get("airDate", ""))
            else:
                item_type = "movie"
                air_date = entry.get("inCinemas", entry.get("digitalRelease", entry.get("physicalRelease", "")))
            items.append({"title": title, "date": air_date, "type": item_type})
        return items
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}





# ── Nextcloud ────────────────────────────────────────────────────────────────
def get_nextcloud(url: str, user: str, password: str) -> dict | None:
    if not url or not user:
        return None
    try:
        import base64
        base = url.rstrip("/")
        cred = base64.b64encode(f"{user}:{password}".encode()).decode()
        hdrs = {
            "Authorization": f"Basic {cred}",
            "OCS-APIREQUEST": "true",
        }
        data = _http_get(
            f"{base}/ocs/v2.php/apps/serverinfo/api/v1/info?format=json", hdrs,
        )
        ocs = data.get("ocs", {}).get("data", {})
        nc = ocs.get("nextcloud", {})
        storage = nc.get("storage", {})
        system = nc.get("system", {})
        active = ocs.get("activeUsers", {})
        return {
            "active_users": active.get("last5minutes", 0),
            "storage_total_gb": round(system.get("freespacealiased", system.get("mem_total", 0)) / (1024 ** 3), 1) if system.get("freespacealiased") else 0.0,
            "storage_free_gb": round(system.get("freespace", 0) / (1024 ** 3), 1),
            "num_files": storage.get("num_files", 0),
            "version": system.get("version", ""),
            "status": "online",
        }
    except ConfigError:
        raise
    except (TransientError, httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        return {"status": "offline", "error": str(e)}



