# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Noba – Central configuration & constants."""
from __future__ import annotations

import os
import sys

# ── Version ───────────────────────────────────────────────────────────────────
VERSION = "2.0.0"

# ── Server ────────────────────────────────────────────────────────────────────
PORT    = int(os.environ.get("PORT",  8080))
HOST    = os.environ.get("HOST", "0.0.0.0")
SSL_CERT = os.environ.get("SSL_CERT", "")
SSL_KEY  = os.environ.get("SSL_KEY",  "")
TRUST_PROXY = os.environ.get("NOBA_TRUST_PROXY", "").lower() in ("1", "true", "yes")

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.environ.get("NOBA_SCRIPT_DIR", os.path.expanduser("~/.local/libexec/noba"))
LOG_DIR     = os.path.expanduser("~/.local/share")
PID_FILE    = os.environ.get("PID_FILE", "/tmp/noba-web-server.pid")
ACTION_LOG  = os.path.join(LOG_DIR, "noba-action.log")
AUTH_CONFIG = os.path.expanduser("~/.config/noba-web/auth.conf")
USER_DB     = os.path.expanduser("~/.config/noba-web/users.conf")
NOBA_YAML   = os.environ.get("NOBA_CONFIG", os.path.expanduser("~/.config/noba/config.yaml"))
HISTORY_DB  = os.path.join(LOG_DIR, "noba-history.db")

# ── Limits & tunables ────────────────────────────────────────────────────────
MAX_BODY_BYTES        = 64 * 1024
TOKEN_TTL_H           = 24
STATS_INTERVAL        = 5
NOTIFICATION_COOLDOWN = 300
HISTORY_RETENTION_DAYS = int(os.environ.get("NOBA_HISTORY_DAYS", 30))
AUDIT_RETENTION_DAYS   = int(os.environ.get("NOBA_AUDIT_DAYS",   90))
_WORKER_THREADS        = int(os.environ.get("NOBA_WORKER_THREADS", 24))
_PW_MIN_LEN            = int(os.environ.get("NOBA_PW_MIN_LEN", 8))
MAX_CONCURRENT_JOBS    = int(os.environ.get("NOBA_MAX_JOBS", 3))
JOB_TIMEOUT            = int(os.environ.get("NOBA_JOB_TIMEOUT", 300))
JOB_MAX_OUTPUT         = 256 * 1024
JOB_RETENTION_DAYS     = int(os.environ.get("NOBA_JOB_RETENTION_DAYS", 30))
PLUGIN_API_VERSION     = 2

# ── YAML config keys ─────────────────────────────────────────────────────────
WEB_KEYS = frozenset([
    "piholeUrl", "piholeToken", "monitoredServices", "radarIps", "bookmarksStr",
    "plexUrl", "plexToken", "kumaUrl", "bmcMap", "truenasUrl", "truenasKey",
    "radarrUrl", "radarrKey", "sonarrUrl", "sonarrKey", "qbitUrl", "qbitUser", "qbitPass",
    "customActions", "automations", "wanTestIp", "lanTestIp",
    "alertRules",
    "proxmoxUrl", "proxmoxUser", "proxmoxTokenName", "proxmoxTokenValue", "proxmoxVerifySsl",
    "pushoverEnabled", "pushoverAppToken", "pushoverUserKey",
    "gotifyEnabled",   "gotifyUrl",        "gotifyAppToken",
    "adguardUrl", "adguardUser", "adguardPass",
    "jellyfinUrl", "jellyfinKey",
    "hassUrl", "hassToken",
    "unifiUrl", "unifiUser", "unifiPass", "unifiSite", "unifiVerifySsl",
    "speedtestUrl",
    "customMetricScripts",
    # Round 1 – Automation
    "maintenanceWindows", "fsTriggers",
    # Round 2 – Monitoring
    "weatherApiKey", "weatherCity", "certHosts", "domainList",
    "energySensors", "devicePresenceIps",
    # Round 3 – Media
    "tautulliUrl", "tautulliKey", "overseerrUrl", "overseerrKey",
    "prowlarrUrl", "prowlarrKey", "lidarrUrl", "lidarrKey",
    "readarrUrl", "readarrKey", "bazarrUrl", "bazarrKey",
    "nextcloudUrl", "nextcloudUser", "nextcloudPass",
    # Round 4 – Infra
    "traefikUrl", "npmUrl", "npmToken",
    "authentikUrl", "authentikToken",
    "cloudflareToken", "cloudflareZoneId",
    "omvUrl", "omvUser", "omvPass",
    "xcpngUrl", "xcpngUser", "xcpngPass",
    # Round 5 – IoT
    "homebridgeUrl", "homebridgeUser", "homebridgePass",
    "z2mUrl", "esphomeUrl",
    "unifiProtectUrl", "unifiProtectUser", "unifiProtectPass", "unifiProtectVerifySsl",
    "pikvmUrl", "pikvmUser", "pikvmPass",
    "hassEventTriggers", "hassSensors", "cameraFeeds",
    # Round 6 – Security
    "oidcProviderUrl", "oidcClientId", "oidcClientSecret",
    "ldapUrl", "ldapBaseDn", "ldapBindDn", "ldapBindPassword",
    "ipWhitelist", "auditRetentionDays", "require2fa",
    # Round 9 – DevOps
    "k8sUrl", "k8sToken", "k8sVerifySsl", "giteaUrl", "giteaToken",
    "gitlabUrl", "gitlabToken", "githubToken",
    "paperlessUrl", "paperlessToken",
    "vaultwardenUrl", "vaultwardenToken",
    "wolDevices", "gameServers", "composeProjects",
    # Disk health
    "scrutinyUrl",
    # RSS triggers
    "rssTriggers",
    # Round 10 – Deep features
    "piholePassword", "dnsService",
    "siteMap", "siteNames",
    "frigateUrl",
    "serviceDependencies",
    "influxdbUrl", "influxdbToken", "influxdbOrg",
    # Round 11 – Ops Center expansion
    "agentKeys", "statusPageServices",
    "graylogUrl", "graylogToken", "graylogUser", "graylogPassword",
    "runbooks",
    # AI / LLM
    "llmProvider", "llmModel", "llmApiKey", "llmBaseUrl",
    "llmMaxTokens", "llmTemperature", "llmEnabled",
])
_NOTIF_WEB_KEYS = frozenset([
    "pushoverEnabled", "pushoverAppToken", "pushoverUserKey",
    "gotifyEnabled",   "gotifyUrl",        "gotifyAppToken",
])
_BACKUP_WEB_KEYS = frozenset([
    "backupSources", "backupDest", "backupRetentionDays", "backupKeepCount",
    "backupVerifySample", "backupMaxDelete", "backupEmail",
    "cloudRemote", "downloadsDir",
    "organizeMaxDepth", "organizeExclude", "organizeCustomRules",
])

# ── State file paths ────────────────────────────────────────────────────────
BACKUP_STATE_FILE = os.path.join(LOG_DIR, "backup-to-nas.state")
CLOUD_STATE_FILE  = os.path.join(LOG_DIR, "cloud-backup.state")

# ── Script / action maps ─────────────────────────────────────────────────────
SCRIPT_MAP = {
    "backup":        "backup-to-nas.sh",
    "cloud":         "cloud-backup.sh",
    "verify":        "backup-verifier.sh",
    "organize":      "organize-downloads.sh",
    "diskcheck":     "disk-sentinel.sh",
    "check_updates": "noba-update.sh",
}
ALLOWED_ACTIONS    = frozenset({"start", "stop", "restart", "poweroff"})
ALLOWED_AUTO_TYPES = frozenset(["script", "webhook", "service", "workflow", "condition", "delay", "notify", "http", "agent_command", "remediation"])
VALID_ROLES        = ("viewer", "operator", "admin")

HISTORY_METRICS = [
    "cpu_percent", "mem_percent", "cpu_temp", "gpu_temp",
    "disk_percent", "ping_ms", "net_rx_bytes", "net_tx_bytes",
    "disk_io_read_bps", "disk_io_write_bps", "custom_metric",
    "cert_expiry_days", "domain_expiry_days", "bandwidth_ip", "weather_temp",
]

# ── Security headers ──────────────────────────────────────────────────────────
SECURITY_HEADERS = {
    "X-Content-Type-Options":            "nosniff",
    "X-Frame-Options":                   "DENY",
    "X-XSS-Protection":                  "0",
    "Referrer-Policy":                   "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' wss: ws:; "
        "frame-ancestors 'none'"
    ),
    "Permissions-Policy":                "geolocation=(), microphone=(), camera=()",
    "Strict-Transport-Security":         "max-age=63072000; includeSubDomains",
    "Cross-Origin-Opener-Policy":        "same-origin",
    "Cross-Origin-Embedder-Policy":      "credentialless",
    "Cross-Origin-Resource-Policy":      "same-site",
}

# ── Stdout buffering ──────────────────────────────────────────────────────────
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except (AttributeError, OSError):
    pass  # stdout/stderr may not be a TextIOWrapper (e.g. pytest, systemd journal)
