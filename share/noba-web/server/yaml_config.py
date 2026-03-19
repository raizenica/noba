"""Noba – YAML configuration read/write helpers."""
from __future__ import annotations

import glob
import logging
import os
import shutil
import threading
import time

import yaml

from .config import NOBA_YAML, WEB_KEYS, _NOTIF_WEB_KEYS

logger = logging.getLogger("noba")

# ── Short-lived cache for read_yaml_settings ─────────────────────────────────
# Avoids re-parsing the YAML file multiple times per collection cycle (~5 s).
_settings_cache: dict | None = None
_settings_cache_t: float = 0.0
_settings_cache_lock = threading.Lock()
_SETTINGS_CACHE_TTL = 2.0


def _bust_settings_cache() -> None:
    """Invalidate the read cache (called after writes)."""
    global _settings_cache
    with _settings_cache_lock:
        _settings_cache = None


def read_yaml_settings() -> dict:
    global _settings_cache, _settings_cache_t
    with _settings_cache_lock:
        if _settings_cache is not None and (time.time() - _settings_cache_t) < _SETTINGS_CACHE_TTL:
            return _settings_cache

    defaults: dict = {
        "piholeUrl": "", "piholeToken": "", "monitoredServices": "", "radarIps": "", "bookmarksStr": "",
        "plexUrl": "", "plexToken": "", "kumaUrl": "", "bmcMap": "", "backupSources": [], "backupDest": "",
        "cloudRemote": "", "downloadsDir": "", "truenasUrl": "", "truenasKey": "",
        "radarrUrl": "", "radarrKey": "", "sonarrUrl": "", "sonarrKey": "",
        "qbitUrl": "", "qbitUser": "", "qbitPass": "",
        "customActions": [], "automations": [], "wanTestIp": "8.8.8.8", "lanTestIp": "",
        "notifications": {}, "alertRules": [],
        "proxmoxUrl": "", "proxmoxUser": "", "proxmoxTokenName": "", "proxmoxTokenValue": "",
        "pushoverEnabled": False, "pushoverAppToken": "", "pushoverUserKey": "",
        "gotifyEnabled": False,   "gotifyUrl": "",        "gotifyAppToken": "",
    }
    if not os.path.exists(NOBA_YAML):
        with _settings_cache_lock:
            _settings_cache = defaults
            _settings_cache_t = time.time()
        return defaults
    try:
        with open(NOBA_YAML, encoding="utf-8") as f:
            full = yaml.safe_load(f) or {}
        if isinstance(full, dict):
            web = full.get("web") or {}
            for k in WEB_KEYS:
                if k in web:
                    defaults[k] = web[k]
            backup = full.get("backup") or {}
            if "sources" in backup:
                defaults["backupSources"] = backup["sources"]
            if "dest" in backup:
                defaults["backupDest"] = backup["dest"]
            cloud = full.get("cloud") or {}
            if "remote" in cloud:
                defaults["cloudRemote"] = cloud["remote"]
            dl = full.get("downloads") or {}
            if "dir" in dl:
                defaults["downloadsDir"] = dl["dir"]
            notif = full.get("notifications") or {}
            if notif:
                defaults["notifications"] = notif
            push = notif.get("pushover") or {}
            defaults["pushoverEnabled"]  = bool(push.get("enabled", False))
            defaults["pushoverAppToken"] = str(push.get("app_token", ""))
            defaults["pushoverUserKey"]  = str(push.get("user_key", ""))
            got = notif.get("gotify") or {}
            defaults["gotifyEnabled"]  = bool(got.get("enabled", False))
            defaults["gotifyUrl"]      = str(got.get("url", ""))
            defaults["gotifyAppToken"] = str(got.get("app_token", ""))
            rules = web.get("alertRules", full.get("alertRules"))
            if rules is not None:
                defaults["alertRules"] = rules
    except Exception as e:
        logger.warning("read_yaml_settings: %s", e)

    with _settings_cache_lock:
        _settings_cache = defaults
        _settings_cache_t = time.time()
    return defaults


def write_yaml_settings(settings: dict) -> bool:
    tmp_path: str | None = None
    try:
        # Load existing config to preserve non-web sections (backup, cloud, downloads…)
        if os.path.exists(NOBA_YAML):
            with open(NOBA_YAML, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            backup_path = f"{NOBA_YAML}.bak.{int(time.time())}"
            try:
                shutil.copy2(NOBA_YAML, backup_path)
                os.chmod(backup_path, 0o600)
                for old in sorted(glob.glob(f"{NOBA_YAML}.bak.*"))[:-5]:
                    os.unlink(old)
            except Exception:
                pass
        else:
            config = {}

        # Build web section (all WEB_KEYS except notification-specific keys)
        config["web"] = {k: v for k, v in settings.items()
                         if k in WEB_KEYS and k not in _NOTIF_WEB_KEYS}

        # Build notifications section
        has_push = any(k in settings for k in ("pushoverEnabled", "pushoverAppToken", "pushoverUserKey"))
        has_got  = any(k in settings for k in ("gotifyEnabled", "gotifyUrl", "gotifyAppToken"))
        if has_push or has_got:
            notif = config.get("notifications") or {}
            if has_push:
                notif["pushover"] = {
                    "enabled":   bool(settings.get("pushoverEnabled", False)),
                    "app_token": str(settings.get("pushoverAppToken", "")),
                    "user_key":  str(settings.get("pushoverUserKey", "")),
                }
            if has_got:
                notif["gotify"] = {
                    "enabled":   bool(settings.get("gotifyEnabled", False)),
                    "url":       str(settings.get("gotifyUrl", "")),
                    "app_token": str(settings.get("gotifyAppToken", "")),
                }
            config["notifications"] = notif

        # Write atomically
        os.makedirs(os.path.dirname(NOBA_YAML), exist_ok=True)
        tmp_path = NOBA_YAML + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        os.replace(tmp_path, NOBA_YAML)
        _bust_settings_cache()
        return True
    except Exception as e:
        logger.error("write_yaml_settings: %s", e)
        return False
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
