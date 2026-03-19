"""Noba – Central configuration & constants."""
from __future__ import annotations

import os
import sys

# ── Version ───────────────────────────────────────────────────────────────────
VERSION = "1.14.0"

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
JOB_MAX_OUTPUT         = 64 * 1024
JOB_RETENTION_DAYS     = int(os.environ.get("NOBA_JOB_RETENTION_DAYS", 30))

# ── YAML config keys ─────────────────────────────────────────────────────────
WEB_KEYS = frozenset([
    "piholeUrl", "piholeToken", "monitoredServices", "radarIps", "bookmarksStr",
    "plexUrl", "plexToken", "kumaUrl", "bmcMap", "truenasUrl", "truenasKey",
    "radarrUrl", "radarrKey", "sonarrUrl", "sonarrKey", "qbitUrl", "qbitUser", "qbitPass",
    "customActions", "automations", "wanTestIp", "lanTestIp",
    "alertRules",
    "proxmoxUrl", "proxmoxUser", "proxmoxTokenName", "proxmoxTokenValue",
    "pushoverEnabled", "pushoverAppToken", "pushoverUserKey",
    "gotifyEnabled",   "gotifyUrl",        "gotifyAppToken",
    "adguardUrl", "adguardUser", "adguardPass",
    "jellyfinUrl", "jellyfinKey",
    "hassUrl", "hassToken",
    "unifiUrl", "unifiUser", "unifiPass", "unifiSite",
    "speedtestUrl",
    "customMetricScripts",
])
_NOTIF_WEB_KEYS = frozenset([
    "pushoverEnabled", "pushoverAppToken", "pushoverUserKey",
    "gotifyEnabled",   "gotifyUrl",        "gotifyAppToken",
])

# ── Script / action maps ─────────────────────────────────────────────────────
SCRIPT_MAP = {
    "backup":        "backup-to-nas.sh",
    "cloud":         "cloud-backup.sh",
    "verify":        "backup-verifier.sh",
    "organize":      "organize-downloads.sh",
    "diskcheck":     "disk-sentinel.sh",
    "check_updates": "noba-update.sh",
}
ALLOWED_ACTIONS = frozenset({"start", "stop", "restart", "poweroff"})
VALID_ROLES     = ("viewer", "operator", "admin")

HISTORY_METRICS = [
    "cpu_percent", "mem_percent", "cpu_temp", "gpu_temp",
    "disk_percent", "ping_ms", "net_rx_bytes", "net_tx_bytes",
    "disk_io_read_bps", "disk_io_write_bps", "custom_metric",
]

# ── Security headers ──────────────────────────────────────────────────────────
SECURITY_HEADERS = {
    "X-Content-Type-Options":  "nosniff",
    "X-Frame-Options":         "SAMEORIGIN",
    "Referrer-Policy":         "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data:; connect-src 'self' wss: ws: https://cdn.jsdelivr.net"
    ),
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}

# ── Stdout buffering ──────────────────────────────────────────────────────────
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except (AttributeError, OSError):
    pass  # stdout/stderr may not be a TextIOWrapper (e.g. pytest, systemd journal)
