# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – YAML configuration read/write helpers."""
from __future__ import annotations

import glob
import logging
import os
import shutil
import threading
import time

import yaml

from .config import NOBA_YAML, WEB_KEYS, _BACKUP_WEB_KEYS, _NOTIF_WEB_KEYS
from .crypto import decrypt_value, encrypt_value
from .schemas import is_secret_key

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
        # ── Core / existing ────────────────────────────────────────────────
        "piholeUrl": "", "piholeToken": "", "piholePassword": "",
        "monitoredServices": "", "radarIps": "", "bookmarksStr": "",
        "plexUrl": "", "plexToken": "", "kumaUrl": "", "bmcMap": "", "backupSources": [], "backupDest": "",
        "backupRetentionDays": 7, "backupKeepCount": 0, "backupVerifySample": 20,
        "backupMaxDelete": "", "backupEmail": "",
        "cloudRemote": "", "downloadsDir": "",
        "organizeMaxDepth": 1, "organizeExclude": "", "organizeCustomRules": [],
        "truenasUrl": "", "truenasKey": "",
        "radarrUrl": "", "radarrKey": "", "sonarrUrl": "", "sonarrKey": "",
        "qbitUrl": "", "qbitUser": "", "qbitPass": "",
        "customActions": [], "automations": [], "wanTestIp": "8.8.8.8", "lanTestIp": "",
        "notifications": {}, "alertRules": [],
        "proxmoxUrl": "", "proxmoxUser": "", "proxmoxTokenName": "", "proxmoxTokenValue": "",
        "pushoverEnabled": False, "pushoverAppToken": "", "pushoverUserKey": "",
        "gotifyEnabled": False,   "gotifyUrl": "",        "gotifyAppToken": "",
        # ── Existing integrations (already in WEB_KEYS) ────────────────────
        "adguardUrl": "", "adguardUser": "", "adguardPass": "",
        "jellyfinUrl": "", "jellyfinKey": "",
        "hassUrl": "", "hassToken": "",
        "unifiUrl": "", "unifiUser": "", "unifiPass": "", "unifiSite": "",
        "speedtestUrl": "",
        "customMetricScripts": "",
        # ── Round 1: Automation ────────────────────────────────────────────
        "maintenanceWindows": [], "fsTriggers": [],
        # ── Round 2: Monitoring ────────────────────────────────────────────
        "weatherApiKey": "", "weatherCity": "", "certHosts": "", "domainList": "",
        "energySensors": "", "devicePresenceIps": "",
        # ── Round 3: Media ─────────────────────────────────────────────────
        "tautulliUrl": "", "tautulliKey": "",
        "overseerrUrl": "", "overseerrKey": "",
        "prowlarrUrl": "", "prowlarrKey": "",
        "lidarrUrl": "", "lidarrKey": "",
        "readarrUrl": "", "readarrKey": "",
        "bazarrUrl": "", "bazarrKey": "",
        "nextcloudUrl": "", "nextcloudUser": "", "nextcloudPass": "",
        # ── Round 4: Infrastructure ────────────────────────────────────────
        "traefikUrl": "",
        "npmUrl": "", "npmToken": "",
        "authentikUrl": "", "authentikToken": "",
        "cloudflareToken": "", "cloudflareZoneId": "",
        "omvUrl": "", "omvUser": "", "omvPass": "",
        "xcpngUrl": "", "xcpngUser": "", "xcpngPass": "",
        # ── Round 5: IoT ───────────────────────────────────────────────────
        "homebridgeUrl": "", "homebridgeUser": "", "homebridgePass": "",
        "z2mUrl": "",
        "esphomeUrl": "",
        "unifiProtectUrl": "", "unifiProtectUser": "", "unifiProtectPass": "",
        "pikvmUrl": "", "pikvmUser": "", "pikvmPass": "",
        "hassEventTriggers": [], "hassSensors": "", "cameraFeeds": [],
        "frigateUrl": "",
        # ── Round 6: Security ──────────────────────────────────────────────
        "oidcProviderUrl": "", "oidcClientId": "", "oidcClientSecret": "", "oidcProviderName": "SSO",
        "socialProviders": {
            "google": {"clientId": "", "clientSecret": ""},
            "facebook": {"clientId": "", "clientSecret": ""},
            "github": {"clientId": "", "clientSecret": ""},
            "microsoft": {"clientId": "", "clientSecret": ""},
        },
        "ldapUrl": "", "ldapBaseDn": "", "ldapBindDn": "", "ldapBindPassword": "",
        "ipWhitelist": "", "auditRetentionDays": 90, "require2fa": False,
        # ── Round 9: DevOps & Misc ─────────────────────────────────────────
        "k8sUrl": "", "k8sToken": "",
        "giteaUrl": "", "giteaToken": "",
        "gitlabUrl": "", "gitlabToken": "",
        "githubToken": "",
        "paperlessUrl": "", "paperlessToken": "",
        "vaultwardenUrl": "", "vaultwardenToken": "",
        "wolDevices": [], "gameServers": [], "composeProjects": [],
        # Disk health
        "scrutinyUrl": "",
        # RSS triggers
        "rssTriggers": [],
        # Multi-Site
        "siteMap": {}, "siteNames": {"siteA": "Site A", "siteB": "Site B"},
        # Service dependencies
        "serviceDependencies": "",
        # InfluxDB
        "influxdbUrl": "", "influxdbToken": "", "influxdbOrg": "",
        # Round 11: Ops Center expansion
        "agentKeys": "", "statusPageServices": "",
        "graylogUrl": "", "graylogToken": "",
        "runbooks": [],
        # AI / LLM
        "llmProvider": "", "llmModel": "", "llmApiKey": "", "llmBaseUrl": "",
        "llmMaxTokens": 4096, "llmTemperature": 0.3, "llmEnabled": False,
        # ── Workflow automation ────────────────────────────────────────────
        "n8nUrl": "", "n8nApiKey": "",
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
            # ── Backup section ────────────────────────────────────────────
            backup = full.get("backup") or {}
            if "sources" in backup:
                defaults["backupSources"] = backup["sources"]
            if "dest" in backup:
                defaults["backupDest"] = backup["dest"]
            if "retention_days" in backup:
                defaults["backupRetentionDays"] = int(backup["retention_days"])
            if "keep_count" in backup:
                defaults["backupKeepCount"] = int(backup["keep_count"])
            if "verify_sample" in backup:
                defaults["backupVerifySample"] = int(backup["verify_sample"])
            if "max_delete" in backup:
                defaults["backupMaxDelete"] = str(backup["max_delete"])
            if "email" in backup:
                defaults["backupEmail"] = str(backup["email"])
            # ── Cloud / downloads ─────────────────────────────────────────
            cloud = full.get("cloud") or {}
            if "remote" in cloud:
                defaults["cloudRemote"] = cloud["remote"]
            dl = full.get("downloads") or {}
            if "dir" in dl:
                defaults["downloadsDir"] = dl["dir"]
            organize = dl.get("organize") or {}
            if "max_depth" in organize:
                defaults["organizeMaxDepth"] = int(organize["max_depth"])
            if "exclude" in organize:
                defaults["organizeExclude"] = str(organize["exclude"])
            if "custom_rules" in organize:
                defaults["organizeCustomRules"] = organize["custom_rules"]
            # ── Notifications ─────────────────────────────────────────────
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

    # Decrypt secret values transparently on read
    for k, v in defaults.items():
        if isinstance(v, str) and is_secret_key(k):
            defaults[k] = decrypt_value(v)

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

        # Encrypt secret values before writing to disk
        settings = {
            k: (encrypt_value(v) if isinstance(v, str) and is_secret_key(k) and v and v != "***" else v)
            for k, v in settings.items()
        }

        # Merge web section — only update keys present in the request,
        # preserving existing values for keys not in this save
        web = config.get("web") or {}
        for k, v in settings.items():
            if k in WEB_KEYS and k not in _NOTIF_WEB_KEYS:
                web[k] = v
        config["web"] = web

        # Build backup section from settings
        if any(k in settings for k in _BACKUP_WEB_KEYS):
            bk = config.get("backup") or {}
            if "backupSources" in settings:
                bk["sources"] = settings["backupSources"]
            if "backupDest" in settings:
                bk["dest"] = settings["backupDest"]
            if "backupRetentionDays" in settings:
                bk["retention_days"] = int(settings["backupRetentionDays"])
            if "backupKeepCount" in settings:
                bk["keep_count"] = int(settings["backupKeepCount"])
            if "backupVerifySample" in settings:
                bk["verify_sample"] = int(settings["backupVerifySample"])
            if "backupMaxDelete" in settings:
                bk["max_delete"] = settings["backupMaxDelete"]
            if "backupEmail" in settings:
                bk["email"] = settings["backupEmail"]
            config["backup"] = bk
            # Cloud remote
            if "cloudRemote" in settings:
                cloud = config.get("cloud") or {}
                cloud["remote"] = settings["cloudRemote"]
                config["cloud"] = cloud
            # Downloads dir + organize settings
            if any(k in settings for k in ("downloadsDir", "organizeMaxDepth", "organizeExclude", "organizeCustomRules")):
                dl = config.get("downloads") or {}
                if "downloadsDir" in settings:
                    dl["dir"] = settings["downloadsDir"]
                organize = dl.get("organize") or {}
                if "organizeMaxDepth" in settings:
                    organize["max_depth"] = int(settings["organizeMaxDepth"])
                if "organizeExclude" in settings:
                    organize["exclude"] = settings["organizeExclude"]
                if "organizeCustomRules" in settings:
                    organize["custom_rules"] = settings["organizeCustomRules"]
                dl["organize"] = organize
                config["downloads"] = dl

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
