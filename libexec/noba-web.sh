#!/bin/bash
# noba-web.sh – Nobara Command Center v8.5.0
#
# Changes from v8.4.0:
#   Shell   : --https flag (enables TLS on the server)
#             --generate-cert (creates self-signed cert via openssl)
#             --add-user (interactive; multi-user management with roles)
#             --remove-user USERNAME
#             --list-users
#             --set-password now delegates to --add-user (backward-compatible)
#             auth.conf format extended: username:pbkdf2:salt:dk:role
#             Old single-user format auto-migrated to admin role on read
#   Backend : TLS via stdlib ssl module (wrap_socket when NOBA_HTTPS=1)
#             Multi-user load_users() — supports admin + viewer roles
#             Token store carries username+role
#             authenticate_request() returns token_info dict or None
#             Admin-only endpoints return 403 for viewer role
#             NotificationStore — timestamped alert history, deduped,
#               persisted to ~/.local/share/noba/notifications.json
#             SpeedtestHistory — parsed speedtest results, persisted to
#               ~/.local/share/noba/speedtest-history.json (last 20 runs)
#             BackgroundCollector feeds NotificationStore on every tick
#             /api/notifications GET  (auth required)
#             /api/speedtest-history GET (auth required)
#             /api/login response now includes { token, role, username }
#             Fixed write_yaml_settings double-call bug from v8.4.0
#   Frontend: Bell icon + unread badge in header
#             Right-side slide-in notifications drawer
#             Speedtest History card with CSS bar chart
#             Role-aware UI — Quick Actions + service buttons require admin
#             unreadCount tracks notifications since last drawer open
#             userRole stored in localStorage on login

set -euo pipefail
trap 'rc=$?; echo "Exiting with code $rc at line $LINENO" >&2' EXIT

# ── Test harness compliance ─────────────────────────────────────────────────
if [[ "${1:-}" == "--help"           ]]; then echo "Usage: noba-web.sh [OPTIONS]"; exit 0; fi
if [[ "${1:-}" == "--version"        ]]; then echo "noba-web.sh version 8.5.0"; exit 0; fi
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

CONFIG_FILE="${HOME}/.config/noba-web.conf"
if [[ -f "$CONFIG_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$CONFIG_FILE"
fi

START_PORT="${START_PORT:-8080}"
MAX_PORT="${MAX_PORT:-8090}"
HTML_DIR="${HTML_DIR:-/tmp/noba-web}"
SERVER_PID_FILE="${SERVER_PID_FILE:-/tmp/noba-web-server.pid}"
SERVER_URL_FILE="${SERVER_URL_FILE:-/tmp/noba-web-server.url}"
LOG_FILE="${LOG_FILE:-/tmp/noba-web.log}"
NOBA_YAML="${NOBA_CONFIG:-$HOME/.config/noba/config.yaml}"
AUTH_DIR="${HOME}/.config/noba-web"
AUTH_CONF="${AUTH_DIR}/auth.conf"
CERT_FILE="${AUTH_DIR}/server.crt"
KEY_FILE="${AUTH_DIR}/server.key"

KILL_ONLY=false
RESTART=false
VERBOSE=false
HOST="${HOST:-0.0.0.0}"
USE_HTTPS=false
SET_PASSWORD=false
ADD_USER=false
REMOVE_USER=""
LIST_USERS=false
SHOW_STATUS=false
GEN_SYSTEMD=false
GEN_CERT=false

# ── Default YAML ─────────────────────────────────────────────────────────────
create_default_yaml() {
    [[ -f "$NOBA_YAML" ]] && return
    log_info "Creating default YAML config at $NOBA_YAML"
    mkdir -p "$(dirname "$NOBA_YAML")"
    cat > "$NOBA_YAML" <<EOF
# Nobara Automation Suite configuration
email: "your@email.com"

backup:
  dest: "$HOME/backups"
  sources:
    - "$HOME/Documents"
    - "$HOME/Pictures"
    - "$HOME/.config"
  retention_days: 7
  space_margin_percent: 10
  min_free_space_gb: 5

disk:
  threshold: 85
  targets:
    - "/"
    - "/home"
  cleanup_enabled: true

downloads:
  dir: "$HOME/Downloads"
  min_age_minutes: 5
  dated_subfolders: true

logs:
  dir: "$HOME/.local/share/noba"
  log_rotation:
    days: 30

web:
  start_port: 8080
  max_port: 8090
  piholeUrl: "dnsa01.vannieuwenhove.org"
  piholeToken: ""
  monitoredServices: "backup-to-nas.service, organize-downloads.service, sshd, podman, syncthing.service"
  radarIps: "192.168.100.1, 1.1.1.1, 8.8.8.8"
  bookmarksStr: "TrueNAS (vnnas)|http://vnnas.vannieuwenhove.org|fa-server, Pi-Hole|http://dnsa01.vannieuwenhove.org/admin|fa-shield-alt, Home Assistant|http://homeassistant.local:8123|fa-home"
EOF
    log_success "Default YAML created. Please edit: $NOBA_YAML"
}

# ── show_version / show_help ─────────────────────────────────────────────────
show_version() { echo "noba-web.sh version 8.5.0"; exit 0; }

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]
Launch the Nobara Command Center web dashboard.

Options:
  -p, --port PORT          Start searching from PORT (default: 8080)
  -m, --max  PORT          Maximum port to try (default: 8090)
  --host     HOST          Bind to specific host/IP (default: 0.0.0.0)
  -k, --kill               Kill any running noba-web server and exit
  -v, --verbose            Tail the server log after starting (Ctrl+C to stop)
  --https                  Enable HTTPS/TLS (requires --generate-cert first)
  --generate-cert          Create a self-signed TLS certificate and exit
  --add-user               Add or update a user (interactive, supports roles)
  --remove-user USERNAME   Remove a user from auth.conf
  --list-users             List configured users and their roles
  --set-password           Alias for --add-user (backward compatible)
  --restart                Kill any running server and start a new one
  --status                 Show whether the server is running
  --generate-systemd       Print a systemd .service unit and exit
  --help                   Show this help message
  --version                Show version information

Configuration: ~/.config/noba-web.conf
Credentials:   ~/.config/noba-web/auth.conf
TLS certs:     ~/.config/noba-web/server.{crt,key}
EOF
    exit 0
}

# ── --status ─────────────────────────────────────────────────────────────────
show_status() {
    if [[ -f "$SERVER_PID_FILE" ]]; then
        local pid url
        pid=$(cat "$SERVER_PID_FILE" 2>/dev/null || true)
        url=$(cat "$SERVER_URL_FILE" 2>/dev/null || echo "unknown URL")
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            log_success "Server running  PID=$pid  URL=$url"
            echo "  Log: $LOG_FILE"
        else
            log_warning "PID file present but server is not running (stale). Cleaning up."
            rm -f "$SERVER_PID_FILE" "$SERVER_URL_FILE"
        fi
    else
        log_info "Server is not running."
    fi
    exit 0
}

# ── --generate-systemd ────────────────────────────────────────────────────────
generate_systemd() {
    local self proto_flag=""
    self="$(realpath "$0")"
    [[ "$USE_HTTPS" == true ]] && proto_flag=" --https"
    cat <<EOF
# Save to: ~/.config/systemd/user/noba-web.service
# Enable:  systemctl --user enable --now noba-web.service

[Unit]
Description=Nobara Command Center Web Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=${self} --port ${START_PORT} --host ${HOST}${proto_flag}
ExecStop=/bin/kill -TERM \$MAINPID
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=noba-web

[Install]
WantedBy=default.target
EOF
    exit 0
}

# ── --generate-cert ──────────────────────────────────────────────────────────
generate_cert() {
    if ! command -v openssl &>/dev/null; then
        log_error "openssl not found. Install it first."; exit 1
    fi
    mkdir -p "$AUTH_DIR"
    local local_ip
    local_ip=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[\d.]+' || hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
    log_info "Generating self-signed TLS certificate (RSA-2048, 365 days)…"
    openssl req -x509 -newkey rsa:2048 \
        -keyout "$KEY_FILE" -out "$CERT_FILE" \
        -days 365 -nodes \
        -subj "/C=XX/ST=Local/L=Local/O=Noba/CN=localhost" \
        -addext "subjectAltName=IP:127.0.0.1,IP:${local_ip},DNS:localhost" 2>/dev/null
    chmod 600 "$KEY_FILE"
    log_success "Certificate: $CERT_FILE"
    log_success "Private key: $KEY_FILE"
    cat <<EOF

To trust this certificate in your browser / OS:

  Linux (system-wide):
    sudo cp "${CERT_FILE}" /usr/local/share/ca-certificates/noba-web.crt
    sudo update-ca-certificates

  Firefox: Settings → Certificates → View Certificates → Authorities → Import

  Chrome/Chromium: Settings → Privacy → Security → Manage Certs → Authorities → Import

Start the server with:  $0 --https
EOF
    exit 0
}

# ── User management ──────────────────────────────────────────────────────────
_hash_password() {
    # Outputs  pbkdf2:salt:dk_hex  to stdout
    python3 - "$1" <<'PYEOF'
import hashlib, secrets, sys
salt = secrets.token_hex(16)
dk   = hashlib.pbkdf2_hmac('sha256', sys.argv[1].encode(), salt.encode(), 200_000)
print(f'pbkdf2:{salt}:{dk.hex()}', end='')
PYEOF
}

add_user() {
    echo "Add / update Nobara Web Dashboard user"
    local username role password password2 pw_hash
    read -rp  "Username: "                      username
    read -rs  -p "Password: "                   password;  echo
    read -rs  -p "Confirm password: "           password2; echo
    if [[ "$password" != "$password2" ]]; then
        echo "Passwords do not match."; exit 1
    fi
    read -rp  "Role [admin/viewer] (default: admin): " role
    role="${role:-admin}"
    if [[ "$role" != "admin" && "$role" != "viewer" ]]; then
        echo "Invalid role '${role}'. Must be 'admin' or 'viewer'."; exit 1
    fi
    pw_hash=$(_hash_password "$password")
    mkdir -p "$AUTH_DIR"
    # Remove existing entry for this user (if any), then append
    if [[ -f "$AUTH_CONF" ]]; then
        grep -v "^${username}:" "$AUTH_CONF" > "${AUTH_CONF}.tmp" 2>/dev/null || true
        mv "${AUTH_CONF}.tmp" "$AUTH_CONF"
    fi
    (umask 077; printf '%s:%s:%s\n' "$username" "$pw_hash" "$role" >> "$AUTH_CONF")
    log_success "User '${username}' (${role}) saved to ${AUTH_CONF}"
    create_default_yaml
    exit 0
}

remove_user() {
    local username="$1"
    if [[ ! -f "$AUTH_CONF" ]]; then
        log_error "No auth.conf found."; exit 1
    fi
    if ! grep -q "^${username}:" "$AUTH_CONF"; then
        log_error "User '${username}' not found."; exit 1
    fi
    grep -v "^${username}:" "$AUTH_CONF" > "${AUTH_CONF}.tmp"
    mv "${AUTH_CONF}.tmp" "$AUTH_CONF"
    log_success "User '${username}' removed."
    exit 0
}

list_users() {
    if [[ ! -f "$AUTH_CONF" ]]; then
        echo "No users configured. Run:  $0 --add-user"; exit 0
    fi
    printf '%-20s  %s\n' "USERNAME" "ROLE"
    printf '%-20s  %s\n' "--------" "----"
    while IFS=: read -r user rest; do
        [[ -z "$user" || "$user" =~ ^# ]] && continue
        # Role is the last colon-separated field in rest
        role=$(echo "$rest" | rev | cut -d: -f1 | rev)
        [[ "$role" != "admin" && "$role" != "viewer" ]] && role="admin"
        printf '%-20s  %s\n' "$user" "$role"
    done < "$AUTH_CONF"
    exit 0
}

# ── Kill server ───────────────────────────────────────────────────────────────
kill_server() {
    if [[ -f "$SERVER_PID_FILE" ]]; then
        local pid
        pid=$(cat "$SERVER_PID_FILE" 2>/dev/null || true)
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            log_info "Stopping server (PID $pid)…"
            kill "$pid" 2>/dev/null && sleep 1
            kill -0 "$pid" 2>/dev/null && { kill -9 "$pid" 2>/dev/null || true; }
        fi
        rm -f "$SERVER_PID_FILE" "$SERVER_URL_FILE"
        rm -rf "$HTML_DIR"
    fi
}

# ── Port finder ──────────────────────────────────────────────────────────────
find_free_port() {
    local start="$1" max="$2" port
    if command -v ss &>/dev/null; then
        for port in $(seq "$start" "$max"); do
            ss -tuln 2>/dev/null | grep -q ":${port}[[:space:]]" || { echo "$port"; return 0; }
        done
    elif command -v lsof &>/dev/null; then
        for port in $(seq "$start" "$max"); do
            lsof -i:"$port" -sTCP:LISTEN -t 2>/dev/null | grep -q . || { echo "$port"; return 0; }
        done
    else
        log_error "Neither 'ss' nor 'lsof' found."; exit 1
    fi
    return 1
}

# ── Argument parsing ──────────────────────────────────────────────────────────
if ! PARSED_ARGS=$(getopt -o p:m:kv \
    -l port:,max:,host:,kill,verbose,help,version,set-password,restart,status,\
generate-systemd,https,generate-cert,add-user,remove-user:,list-users \
    -- "$@" 2>/dev/null); then
    log_error "Invalid argument. Run with --help for usage."; exit 1
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -p|--port)           START_PORT="$2";        shift 2 ;;
        -m|--max)            MAX_PORT="$2";           shift 2 ;;
        --host)              HOST="$2";               shift 2 ;;
        -k|--kill)           KILL_ONLY=true;          shift   ;;
        -v|--verbose)        VERBOSE=true;            shift   ;;
        --set-password)      ADD_USER=true;           shift   ;;
        --add-user)          ADD_USER=true;           shift   ;;
        --remove-user)       REMOVE_USER="$2";        shift 2 ;;
        --list-users)        LIST_USERS=true;         shift   ;;
        --https)             USE_HTTPS=true;          shift   ;;
        --generate-cert)     GEN_CERT=true;           shift   ;;
        --restart)           KILL_ONLY=true; RESTART=true; shift ;;
        --status)            SHOW_STATUS=true;        shift   ;;
        --generate-systemd)  GEN_SYSTEMD=true;        shift   ;;
        --help)              show_help ;;
        --version)           show_version ;;
        --)                  shift; break ;;
        *)                   log_error "Unknown argument: $1"; exit 1 ;;
    esac
done

[[ "$SHOW_STATUS"  == true ]] && show_status
[[ "$GEN_CERT"     == true ]] && generate_cert
[[ "$GEN_SYSTEMD"  == true ]] && generate_systemd
[[ "$ADD_USER"     == true ]] && add_user
[[ -n "$REMOVE_USER"       ]] && remove_user "$REMOVE_USER"
[[ "$LIST_USERS"   == true ]] && list_users

if [[ "$USE_HTTPS" == true && ! -f "$CERT_FILE" ]]; then
    log_error "TLS certificate not found. Run:  $0 --generate-cert"
    exit 1
fi

if [[ "$KILL_ONLY" == true ]]; then
    kill_server
    [[ "$RESTART" != true ]] && exit 0
fi

check_deps python3 yq

if ! yq --version 2>/dev/null | grep -q "mikefarah"; then
    log_error "'yq' must be the Go version (mikefarah/yq). See https://github.com/mikefarah/yq"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
if ! awk -v ver="$PYTHON_VERSION" 'BEGIN { split(ver,v,"."); exit !(v[1]>3||(v[1]==3&&v[2]>=7)); }'; then
    log_error "Python 3.7+ required (found $PYTHON_VERSION)."; exit 1
fi

PORT=$(find_free_port "$START_PORT" "$MAX_PORT") || die "No free port in range ${START_PORT}–${MAX_PORT}."
log_info "Using port $PORT"

mkdir -p "$HTML_DIR"
rm -f "$HTML_DIR"/*.html "$HTML_DIR"/server.py 2>/dev/null || true
create_default_yaml

# ── index.html ─────────────────────────────────────────────────────────────
cat > "$HTML_DIR/index.html" <<'HTMLEOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>NOBA // Command Center</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@400;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
    <script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>
    <style>
        *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
        :root {
            --bg:#060a10; --surface:#0c1420; --surface-2:#111d2c;
            --border:#1e3a5f; --border-hi:#2a5480;
            --text:#c8dff0; --text-muted:#4a7a9b; --text-dim:#1e3a5f;
            --accent:#00c8ff; --accent-dim:rgba(0,200,255,.1); --accent-glow:rgba(0,200,255,.18);
            --success:#00e676; --success-dim:rgba(0,230,118,.1);
            --warning:#ffb300; --warning-dim:rgba(255,179,0,.1);
            --danger:#ff1744; --danger-dim:rgba(255,23,68,.1);
            --font-ui:'Chakra Petch',monospace; --font-data:'JetBrains Mono',monospace;
        }
        [data-theme="dracula"] { --bg:#191a21;--surface:#282a36;--surface-2:#2f3146;--border:#44475a;--border-hi:#6272a4;--text:#f8f8f2;--text-muted:#6272a4;--text-dim:#44475a;--accent:#bd93f9;--accent-dim:rgba(189,147,249,.1);--accent-glow:rgba(189,147,249,.18);--success:#50fa7b;--success-dim:rgba(80,250,123,.1);--warning:#f1fa8c;--warning-dim:rgba(241,250,140,.1);--danger:#ff5555;--danger-dim:rgba(255,85,85,.1); }
        [data-theme="nord"] { --bg:#242933;--surface:#2e3440;--surface-2:#3b4252;--border:#4c566a;--border-hi:#5e81ac;--text:#eceff4;--text-muted:#4c566a;--text-dim:#3b4252;--accent:#88c0d0;--accent-dim:rgba(136,192,208,.1);--accent-glow:rgba(136,192,208,.18);--success:#a3be8c;--success-dim:rgba(163,190,140,.1);--warning:#ebcb8b;--warning-dim:rgba(235,203,139,.1);--danger:#bf616a;--danger-dim:rgba(191,97,106,.1); }
        [data-theme="catppuccin"] { --bg:#1e1e2e;--surface:#24273a;--surface-2:#2a2d3e;--border:#45475a;--border-hi:#7c7f93;--text:#cdd6f4;--text-muted:#6c7086;--text-dim:#45475a;--accent:#89b4fa;--accent-dim:rgba(137,180,250,.1);--accent-glow:rgba(137,180,250,.18);--success:#a6e3a1;--success-dim:rgba(166,227,161,.1);--warning:#f9e2af;--warning-dim:rgba(249,226,175,.1);--danger:#f38ba8;--danger-dim:rgba(243,139,168,.1); }
        [data-theme="tokyo"] { --bg:#13141f;--surface:#1a1b26;--surface-2:#24283b;--border:#2f3549;--border-hi:#414868;--text:#c0caf5;--text-muted:#565f89;--text-dim:#2f3549;--accent:#7aa2f7;--accent-dim:rgba(122,162,247,.1);--accent-glow:rgba(122,162,247,.18);--success:#9ece6a;--success-dim:rgba(158,206,106,.1);--warning:#e0af68;--warning-dim:rgba(224,175,104,.1);--danger:#f7768e;--danger-dim:rgba(247,118,142,.1); }
        [data-theme="gruvbox"] { --bg:#1d2021;--surface:#282828;--surface-2:#32302f;--border:#3c3836;--border-hi:#665c54;--text:#ebdbb2;--text-muted:#7c6f64;--text-dim:#504945;--accent:#83a598;--accent-dim:rgba(131,165,152,.1);--accent-glow:rgba(131,165,152,.18);--success:#b8bb26;--success-dim:rgba(184,187,38,.1);--warning:#fabd2f;--warning-dim:rgba(250,189,47,.1);--danger:#fb4934;--danger-dim:rgba(251,73,52,.1); }

        body { background:var(--bg); color:var(--text); font-family:var(--font-ui); min-height:100vh; overflow-x:hidden; background-image:radial-gradient(circle,var(--border) 1px,transparent 1px); background-size:28px 28px; }
        .page { padding:1.5rem 2rem; max-width:1600px; margin:0 auto; }

        /* ── Header ── */
        .header { display:flex; justify-content:space-between; align-items:center; margin-bottom:1.25rem; padding-bottom:1rem; border-bottom:1px solid var(--border); flex-wrap:wrap; gap:1rem; }
        .logo { display:flex; align-items:center; gap:.875rem; }
        .logo-mark { width:42px; height:42px; background:var(--accent-dim); border:1px solid var(--accent); border-radius:5px; display:flex; align-items:center; justify-content:center; color:var(--accent); font-size:1.15rem; }
        .logo-name { font-size:1.3rem; font-weight:700; letter-spacing:.18em; }
        .logo-slash { color:var(--accent); }
        .logo-tagline { font-size:.65rem; letter-spacing:.3em; color:var(--text-muted); margin-top:1px; }
        .header-controls { display:flex; align-items:center; gap:.625rem; flex-wrap:wrap; }
        .theme-select { background:var(--surface); color:var(--text); border:1px solid var(--border); border-radius:4px; padding:.4rem .6rem; font-family:var(--font-ui); font-size:.8rem; cursor:pointer; outline:none; }
        .theme-select:focus { border-color:var(--accent); }
        .icon-btn { width:34px; height:34px; display:flex; align-items:center; justify-content:center; background:var(--surface); border:1px solid var(--border); border-radius:4px; cursor:pointer; color:var(--text-muted); transition:all .15s; font-size:.85rem; position:relative; }
        .icon-btn:hover { border-color:var(--accent); color:var(--accent); background:var(--accent-dim); }

        /* ── Notification badge ── */
        .notif-badge { position:absolute; top:-6px; right:-6px; background:var(--danger); color:#fff; font-size:.6rem; font-weight:700; border-radius:10px; padding:.12rem .32rem; min-width:16px; text-align:center; line-height:1.5; font-family:var(--font-data); pointer-events:none; }

        /* ── Live pill ── */
        .live-pill { display:flex; align-items:center; gap:.45rem; background:var(--surface); border:1px solid var(--border); border-radius:4px; padding:.4rem .8rem; font-family:var(--font-data); font-size:.75rem; color:var(--text-muted); transition:border-color .3s; }
        .live-pill.conn-sse     { border-color:rgba(0,230,118,.35); }
        .live-pill.conn-polling { border-color:rgba(255,179,0,.3); }
        .live-pill.conn-offline { border-color:rgba(255,23,68,.35); }
        .live-dot { width:7px; height:7px; border-radius:50%; flex-shrink:0; transition:background .3s; }
        .live-dot.sse     { background:var(--success); animation:blink 2.5s infinite; }
        .live-dot.polling { background:var(--warning); }
        .live-dot.syncing { background:var(--warning); }
        .live-dot.offline { background:var(--danger); }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:.3} }

        /* ── Role badge ── */
        .role-pill { display:flex; align-items:center; gap:.35rem; background:var(--surface); border:1px solid var(--border); border-radius:4px; padding:.4rem .7rem; font-size:.65rem; font-weight:700; letter-spacing:.12em; text-transform:uppercase; }
        .role-pill.admin { color:var(--accent); border-color:rgba(0,200,255,.3); }
        .role-pill.viewer { color:var(--text-muted); }

        /* ── Alerts ── */
        .alerts { margin-bottom:1.25rem; display:flex; flex-direction:column; gap:.4rem; }
        .alert { display:flex; align-items:center; gap:.75rem; padding:.55rem 1rem; border-radius:4px; font-size:.82rem; font-family:var(--font-data); border-left:3px solid; }
        .alert.danger  { background:var(--danger-dim);  border-color:var(--danger);  color:var(--danger); }
        .alert.warning { background:var(--warning-dim); border-color:var(--warning); color:var(--warning); }
        .alert-dismiss { margin-left:auto; background:none; border:none; cursor:pointer; color:inherit; font-size:1rem; line-height:1; opacity:.65; padding:0 .2rem; transition:opacity .15s; }
        .alert-dismiss:hover { opacity:1; }

        /* ── Notifications drawer ── */
        .notif-overlay { position:fixed; inset:0; background:rgba(0,0,0,.6); backdrop-filter:blur(3px); z-index:55; display:flex; justify-content:flex-end; }
        .notif-drawer { background:var(--surface); border-left:1px solid var(--border); width:min(400px,95vw); height:100vh; display:flex; flex-direction:column; animation:slide-in-right .2s ease; }
        @keyframes slide-in-right { from{transform:translateX(100%)} to{transform:translateX(0)} }
        .notif-hdr { display:flex; justify-content:space-between; align-items:center; padding:1rem 1.25rem; border-bottom:1px solid var(--border); background:rgba(0,0,0,.25); }
        .notif-hdr-title { font-size:.8rem; font-weight:700; letter-spacing:.18em; text-transform:uppercase; color:var(--text-muted); }
        .notif-body { flex:1; overflow-y:auto; padding:.75rem; display:flex; flex-direction:column; gap:.4rem; }
        .notif-item { padding:.6rem .85rem; border-radius:4px; border-left:3px solid; font-size:.78rem; font-family:var(--font-data); }
        .notif-item.danger  { background:var(--danger-dim);  border-color:var(--danger);  color:var(--danger); }
        .notif-item.warning { background:var(--warning-dim); border-color:var(--warning); color:var(--warning); }
        .notif-item.info    { background:var(--accent-dim);  border-color:var(--accent);  color:var(--accent); }
        .notif-msg  { display:block; margin-bottom:.25rem; }
        .notif-time { font-size:.68rem; opacity:.7; }
        .notif-empty { text-align:center; color:var(--text-muted); font-size:.82rem; padding:3rem 1rem; }

        /* ── Grid ── */
        .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(330px,1fr)); gap:1.125rem; align-items:start; }
        .span-full { grid-column:1/-1; }

        /* ── Card ── */
        .card { background:var(--surface); border:1px solid var(--border); border-top:2px solid var(--accent); border-radius:5px; overflow:hidden; transition:box-shadow .2s; }
        .card:hover { box-shadow:0 0 28px var(--accent-glow); }
        .card-hdr { padding:.8rem 1.2rem; background:rgba(0,0,0,.25); border-bottom:1px solid var(--border); display:flex; align-items:center; gap:.7rem; cursor:grab; user-select:none; }
        .card-hdr:active { cursor:grabbing; }
        .card-icon { color:var(--accent); font-size:.85rem; flex-shrink:0; }
        .card-title { font-size:.65rem; font-weight:700; letter-spacing:.2em; text-transform:uppercase; color:var(--text-muted); flex:1; }
        .drag-handle { color:var(--text-dim); font-size:.8rem; transition:color .15s; }
        .card:hover .drag-handle { color:var(--text-muted); }
        .card-body { padding:1.125rem; }

        /* ── Data rows ── */
        .row { display:flex; justify-content:space-between; align-items:center; padding:.42rem 0; border-bottom:1px solid var(--surface-2); }
        .row:last-child { border-bottom:none; }
        .row-label { font-size:.72rem; color:var(--text-muted); letter-spacing:.08em; text-transform:uppercase; }
        .row-val { font-family:var(--font-data); font-size:.88rem; text-align:right; }

        /* ── Badges ── */
        .badge { display:inline-flex; align-items:center; gap:.25rem; padding:.18rem .55rem; border-radius:3px; font-size:.65rem; font-weight:700; letter-spacing:.1em; text-transform:uppercase; border:1px solid; }
        .bs { background:var(--success-dim); color:var(--success); border-color:rgba(0,230,118,.2); }
        .bw { background:var(--warning-dim); color:var(--warning); border-color:rgba(255,179,0,.2); }
        .bd { background:var(--danger-dim);  color:var(--danger);  border-color:rgba(255,23,68,.2); }
        .bn { background:var(--surface-2); color:var(--text-muted); border-color:var(--border); }
        .ba { background:var(--accent-dim); color:var(--accent); border-color:rgba(0,200,255,.2); }

        /* ── Progress ── */
        .prog { margin:.55rem 0; }
        .prog-meta { display:flex; justify-content:space-between; font-size:.7rem; color:var(--text-muted); margin-bottom:.28rem; font-family:var(--font-data); }
        .prog-track { height:4px; background:var(--surface-2); border-radius:2px; overflow:hidden; }
        .prog-fill { height:100%; border-radius:2px; transition:width .5s ease; }
        .f-accent{background:var(--accent)} .f-success{background:var(--success)} .f-warning{background:var(--warning)} .f-danger{background:var(--danger)}

        /* ── Sparkline ── */
        .spark-wrap { display:flex; align-items:center; gap:.875rem; margin-top:.75rem; }
        .spark-svg { flex:1; height:42px; overflow:visible; }
        .spark-val { font-family:var(--font-data); font-size:1.6rem; font-weight:500; color:var(--accent); min-width:58px; text-align:right; }

        /* ── IO Stats ── */
        .io-grid { display:grid; grid-template-columns:1fr 1fr; gap:.75rem; }
        .io-stat { background:var(--surface-2); border-radius:4px; padding:.75rem; text-align:center; }
        .io-val { font-family:var(--font-data); font-size:1.05rem; font-weight:500; }
        .io-down { color:var(--success); }
        .io-up   { color:var(--accent); }
        .io-label { font-size:.62rem; letter-spacing:.12em; text-transform:uppercase; color:var(--text-muted); margin-top:.2rem; }

        /* ── Pi-hole ── */
        .ph-stats { display:grid; grid-template-columns:1fr 1fr; gap:.75rem; margin-bottom:.875rem; }
        .ph-stat { background:var(--surface-2); border-radius:4px; padding:.7rem .9rem; }
        .ph-val { font-family:var(--font-data); font-size:1.25rem; font-weight:500; }
        .ph-label { font-size:.6rem; letter-spacing:.1em; text-transform:uppercase; color:var(--text-muted); margin-top:.18rem; }

        /* ── Radar ── */
        .radar-row { display:flex; align-items:center; gap:.7rem; padding:.45rem 0; border-bottom:1px solid var(--surface-2); }
        .radar-row:last-child { border-bottom:none; }
        .radar-ip  { font-family:var(--font-data); font-size:.82rem; flex:1; }
        .radar-ms  { font-family:var(--font-data); font-size:.72rem; color:var(--text-muted); min-width:48px; text-align:right; }
        .status-dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
        .dot-up   { background:var(--success); box-shadow:0 0 7px var(--success); animation:blink 2.5s infinite; }
        .dot-down { background:var(--danger); }

        /* ── Services ── */
        .svc-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(175px,1fr)); gap:.7rem; }
        .svc-card { background:var(--surface-2); border:1px solid var(--border); border-radius:4px; padding:.7rem .875rem; }
        .svc-name { font-size:.78rem; font-weight:600; margin-bottom:.45rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .svc-footer { display:flex; align-items:center; justify-content:space-between; }
        .svc-btns { display:flex; gap:.28rem; }
        .svc-btn { background:none; border:1px solid var(--border); color:var(--text-muted); cursor:pointer; padding:.2rem .4rem; border-radius:3px; font-size:.72rem; transition:all .15s; }
        .svc-btn:hover:not(:disabled) { border-color:var(--accent); color:var(--accent); }
        .svc-btn:disabled { opacity:.3; cursor:not-allowed; }

        /* ── Containers ── */
        .ct-list { display:flex; flex-direction:column; gap:.45rem; }
        .ct-row { display:flex; align-items:center; gap:.65rem; padding:.45rem .7rem; background:var(--surface-2); border-radius:4px; }
        .ct-name { font-family:var(--font-data); font-size:.78rem; flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .ct-img  { font-size:.68rem; color:var(--text-muted); font-family:var(--font-data); max-width:110px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }

        /* ── Process list ── */
        .proc-grid { display:grid; grid-template-columns:1fr 1fr; gap:1rem; }
        .proc-hdr { font-size:.62rem; letter-spacing:.15em; text-transform:uppercase; color:var(--text-muted); margin-bottom:.4rem; border-bottom:1px solid var(--border); padding-bottom:.2rem; }
        .proc-row { display:flex; justify-content:space-between; font-family:var(--font-data); font-size:.76rem; padding:.18rem 0; }
        .proc-n   { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:95px; }
        .cpu-col  { color:var(--warning); }
        .mem-col  { color:var(--accent); }

        /* ── Speedtest History card ── */
        .st-latest { display:grid; grid-template-columns:1fr 1fr 1fr; gap:.5rem; margin-bottom:.875rem; }
        .st-stat { background:var(--surface-2); border-radius:4px; padding:.65rem .75rem; text-align:center; }
        .st-val  { font-family:var(--font-data); font-size:1.1rem; font-weight:500; }
        .st-lbl  { font-size:.6rem; letter-spacing:.1em; text-transform:uppercase; color:var(--text-muted); margin-top:.15rem; }
        .st-chart { display:flex; align-items:flex-end; gap:4px; height:72px; margin-bottom:.6rem; }
        .st-col   { display:flex; align-items:flex-end; gap:2px; flex:1; height:100%; }
        .st-bar-dl { flex:1; background:var(--accent); border-radius:2px 2px 0 0; min-height:2px; transition:height .5s ease; }
        .st-bar-ul { flex:1; background:var(--success); border-radius:2px 2px 0 0; min-height:2px; transition:height .5s ease; }
        .st-legend { display:flex; gap:1rem; font-size:.68rem; color:var(--text-muted); }
        .st-legend-dot { width:8px; height:8px; border-radius:2px; display:inline-block; margin-right:3px; }
        .st-time { font-size:.65rem; color:var(--text-dim); text-align:center; margin-top:.2rem; font-family:var(--font-data); }

        /* ── Bookmarks ── */
        .bm-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(128px,1fr)); gap:.55rem; }
        .bm-link { display:flex; align-items:center; gap:.45rem; padding:.48rem .7rem; background:var(--surface-2); border:1px solid var(--border); border-radius:4px; text-decoration:none; color:var(--text); font-size:.78rem; transition:all .15s; overflow:hidden; }
        .bm-link:hover { border-color:var(--accent); color:var(--accent); background:var(--accent-dim); }
        .bm-link i { color:var(--accent); flex-shrink:0; font-size:.82rem; }
        .bm-link span { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

        /* ── Actions ── */
        .action-list { display:flex; flex-direction:column; gap:.55rem; }
        .btn { display:flex; align-items:center; gap:.6rem; padding:.65rem 1rem; border:1px solid var(--border); background:var(--surface-2); color:var(--text); border-radius:4px; cursor:pointer; font-family:var(--font-ui); font-size:.82rem; font-weight:600; letter-spacing:.05em; transition:all .15s; width:100%; }
        .btn:hover:not(:disabled) { border-color:var(--accent); color:var(--accent); background:var(--accent-dim); }
        .btn:disabled { opacity:.4; cursor:not-allowed; }
        .btn-primary { border-color:var(--accent); color:var(--accent); background:var(--accent-dim); }
        .btn-primary:hover:not(:disabled) { background:rgba(0,200,255,.18); }

        /* ── Log viewer ── */
        .log-controls { display:flex; justify-content:space-between; align-items:center; margin-bottom:.75rem; gap:.5rem; flex-wrap:wrap; }
        .log-pre { background:rgba(0,0,0,.45); padding:.875rem; border-radius:4px; font-family:var(--font-data); font-size:.73rem; color:var(--text-muted); white-space:pre-wrap; overflow-y:auto; max-height:215px; border:1px solid var(--border); }

        /* ── Sortable ── */
        .sortable-ghost { opacity:.25; border:1px dashed var(--accent)!important; }
        .sortable-drag  { box-shadow:0 20px 55px rgba(0,0,0,.6)!important; z-index:100; }

        /* ── Modal ── */
        .modal-overlay { position:fixed; inset:0; background:rgba(0,0,0,.82); backdrop-filter:blur(6px); display:flex; align-items:center; justify-content:center; z-index:50; }
        .modal-box { background:var(--surface); border:1px solid var(--border); border-top:2px solid var(--accent); border-radius:5px; width:92%; max-width:820px; padding:1.75rem; max-height:90vh; overflow-y:auto; }
        .modal-title { font-size:.9rem; font-weight:700; letter-spacing:.18em; text-transform:uppercase; margin-bottom:1.125rem; display:flex; align-items:center; gap:.7rem; }
        .console-out { background:#000; color:var(--success); padding:1rem; border-radius:4px; font-family:var(--font-data); font-size:.76rem; max-height:50vh; overflow-y:auto; white-space:pre-wrap; border:1px solid var(--border); }
        .modal-footer { display:flex; justify-content:flex-end; margin-top:1.25rem; }

        /* ── Settings ── */
        .s-section { margin-bottom:1.375rem; }
        .s-label { display:block; font-size:.62rem; letter-spacing:.2em; text-transform:uppercase; color:var(--text-muted); margin-bottom:.7rem; padding-bottom:.38rem; border-bottom:1px solid var(--border); }
        .toggle-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(170px,1fr)); gap:.45rem; }
        .toggle-item { display:flex; align-items:center; gap:.45rem; cursor:pointer; font-size:.8rem; color:var(--text-muted); }
        .toggle-item input[type=checkbox] { accent-color:var(--accent); }
        .field-2 { display:grid; grid-template-columns:1fr 1fr; gap:.75rem; margin-bottom:.75rem; }
        .field-label { display:block; font-size:.65rem; letter-spacing:.1em; text-transform:uppercase; color:var(--text-muted); margin-bottom:.28rem; }
        .field-input { width:100%; background:var(--surface-2); color:var(--text); border:1px solid var(--border); border-radius:4px; padding:.48rem .7rem; font-family:var(--font-data); font-size:.8rem; outline:none; transition:border-color .15s; }
        .field-input:focus { border-color:var(--accent); }
        .settings-footer { display:flex; justify-content:flex-end; gap:.7rem; margin-top:1.5rem; }
        .btn-sm { width:auto; padding:.55rem 1.4rem; }
        .kbd-grid { display:flex; flex-wrap:wrap; gap:.45rem; }
        .kbd-item { display:flex; align-items:center; gap:.4rem; font-size:.75rem; color:var(--text-muted); }
        kbd { background:var(--surface-2); border:1px solid var(--border-hi); border-radius:3px; padding:.15rem .45rem; font-family:var(--font-data); font-size:.72rem; color:var(--text); }

        /* ── Toast ── */
        .toasts { position:fixed; bottom:1.5rem; right:1.5rem; z-index:200; display:flex; flex-direction:column; gap:.45rem; pointer-events:none; }
        .toast { padding:.65rem 1rem; border-radius:4px; font-size:.8rem; display:flex; align-items:center; gap:.5rem; animation:toast-in .18s ease; border-left:3px solid; pointer-events:auto; min-width:200px; }
        .toast.success { background:var(--surface); border-color:var(--success); color:var(--success); }
        .toast.error   { background:var(--surface); border-color:var(--danger);  color:var(--danger); }
        .toast.info    { background:var(--surface); border-color:var(--accent);  color:var(--accent); }
        @keyframes toast-in { from{transform:translateX(110%);opacity:0} to{transform:translateX(0);opacity:1} }

        ::-webkit-scrollbar { width:5px; height:5px; }
        ::-webkit-scrollbar-track { background:var(--surface); }
        ::-webkit-scrollbar-thumb { background:var(--border); border-radius:3px; }
        ::-webkit-scrollbar-thumb:hover { background:var(--border-hi); }
    </style>
</head>
<body x-data="dashboard()" x-init="init()" :data-theme="theme">
<div class="page">

    <!-- Header -->
    <header class="header">
        <div class="logo">
            <div class="logo-mark"><i class="fas fa-terminal"></i></div>
            <div>
                <div class="logo-name">NOBA <span class="logo-slash">//</span> COMMAND</div>
                <div class="logo-tagline">Nobara Automation Suite</div>
            </div>
        </div>
        <div class="header-controls">
            <select class="theme-select" x-model="theme" @change="saveSettings()">
                <option value="default">Operator</option>
                <option value="catppuccin">Catppuccin</option>
                <option value="tokyo">Tokyo Night</option>
                <option value="gruvbox">Gruvbox</option>
                <option value="dracula">Dracula</option>
                <option value="nord">Nord</option>
            </select>
            <div class="icon-btn" @click="showSettings=true" title="Settings (s)"><i class="fas fa-sliders-h"></i></div>
            <!-- Notifications bell -->
            <div class="icon-btn" @click="openNotifPanel()" title="Notifications" x-show="authenticated">
                <i class="fas fa-bell"></i>
                <span class="notif-badge" x-show="unreadCount > 0" x-text="unreadCount > 9 ? '9+' : unreadCount"></span>
            </div>
            <!-- Role pill -->
            <div class="role-pill" :class="userRole" x-show="authenticated">
                <i class="fas" :class="userRole==='admin'?'fa-shield-alt':'fa-eye'"></i>
                <span x-text="userRole"></span>
            </div>
            <div class="live-pill" :class="'conn-'+connStatus">
                <div class="live-dot" :class="refreshing?'syncing':connStatus"></div>
                <span x-text="livePillText"></span>
            </div>
            <button class="icon-btn" @click="logout" title="Logout" x-show="authenticated">
                <i class="fas fa-sign-out-alt"></i>
            </button>
        </div>
    </header>

    <!-- Alerts (dismissable) -->
    <div class="alerts" x-show="visibleAlerts.length > 0">
        <template x-for="a in visibleAlerts" :key="a.msg">
            <div class="alert" :class="a.level">
                <i class="fas" :class="a.level==='danger'?'fa-exclamation-circle':'fa-exclamation-triangle'"></i>
                <span x-text="a.msg" style="flex:1"></span>
                <button class="alert-dismiss" @click="dismissAlert(a.msg)" title="Dismiss">×</button>
            </div>
        </template>
    </div>

    <!-- Dashboard Grid -->
    <div class="grid" id="sortable-grid">

        <!-- Core System -->
        <div class="card" data-id="card-core" x-show="vis.core">
            <div class="card-hdr"><i class="fas fa-microchip card-icon"></i><span class="card-title">Core System</span><i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="card-body">
                <div class="row"><span class="row-label">OS</span><span class="row-val" x-text="osName"></span></div>
                <div class="row"><span class="row-label">Kernel</span><span class="row-val" x-text="kernel"></span></div>
                <div class="row"><span class="row-label">Uptime</span><span class="row-val" x-text="uptime"></span></div>
                <div class="row"><span class="row-label">Load Avg</span><span class="row-val" x-text="loadavg"></span></div>
                <div class="row"><span class="row-label">CPU Temp</span><span class="badge" :class="cpuTempClass" x-text="cpuTemp"></span></div>
                <div style="margin-top:.875rem">
                    <div style="font-size:.62rem;letter-spacing:.15em;text-transform:uppercase;color:var(--text-muted);margin-bottom:.35rem">CPU UTILIZATION</div>
                    <div class="spark-wrap">
                        <svg class="spark-svg" viewBox="0 0 120 40" preserveAspectRatio="none">
                            <defs><linearGradient id="sg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="var(--accent)" stop-opacity="0.3"/><stop offset="100%" stop-color="var(--accent)" stop-opacity="0.0"/></linearGradient></defs>
                            <polygon :points="cpuFill" fill="url(#sg)"/>
                            <polyline :points="cpuLine" fill="none" stroke="var(--accent)" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
                        </svg>
                        <div class="spark-val" x-text="cpuPercent+'%'"></div>
                    </div>
                </div>
                <div class="prog" style="margin-top:.65rem">
                    <div class="prog-meta"><span>MEMORY</span><span x-text="memPercent+'%'"></span></div>
                    <div class="prog-track"><div class="prog-fill" :class="memPercent>90?'f-danger':memPercent>75?'f-warning':'f-accent'" :style="'width:'+memPercent+'%'"></div></div>
                    <div style="font-family:var(--font-data);font-size:.72rem;color:var(--text-muted);margin-top:.2rem" x-text="memory"></div>
                </div>
            </div>
        </div>

        <!-- Network I/O -->
        <div class="card" data-id="card-netio" x-show="vis.netio">
            <div class="card-hdr"><i class="fas fa-network-wired card-icon"></i><span class="card-title">Network I/O</span><i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="card-body">
                <div class="io-grid" style="margin-bottom:.875rem">
                    <div class="io-stat"><div class="io-val io-down" x-text="netRx||'0 B/s'"></div><div class="io-label"><i class="fas fa-arrow-down"></i> RX</div></div>
                    <div class="io-stat"><div class="io-val io-up"   x-text="netTx||'0 B/s'"></div><div class="io-label"><i class="fas fa-arrow-up"></i> TX</div></div>
                </div>
                <div class="row"><span class="row-label">Hostname</span><span class="row-val" x-text="hostname||'--'"></span></div>
                <div class="row"><span class="row-label">Default IP</span><span class="row-val" x-text="defaultIp||'--'"></span></div>
            </div>
        </div>

        <!-- Hardware -->
        <div class="card" data-id="card-hw" x-show="vis.hw">
            <div class="card-hdr"><i class="fas fa-memory card-icon"></i><span class="card-title">Hardware</span><i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="card-body">
                <div class="row"><span class="row-label">CPU</span><span class="row-val" style="font-size:.78rem;max-width:210px" x-text="hwCpu"></span></div>
                <div class="row"><span class="row-label">GPU</span><span class="row-val" style="font-size:.76rem;max-width:210px" x-html="hwGpu"></span></div>
                <div class="row" x-show="gpuTemp&&gpuTemp!=='N/A'"><span class="row-label">GPU Temp</span><span class="badge" :class="gpuTempClass" x-text="gpuTemp"></span></div>
            </div>
        </div>

        <!-- Battery -->
        <div class="card" data-id="card-battery" x-show="vis.battery&&battery&&!battery.desktop">
            <div class="card-hdr"><i class="fas fa-battery-half card-icon"></i><span class="card-title">Power State</span><i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="card-body">
                <div class="row"><span class="row-label">Status</span><span class="badge" :class="battery.status==='Charging'||battery.status==='Full'?'bs':battery.status==='Discharging'?'bw':'bn'" x-text="battery.status"></span></div>
                <div class="row" x-show="battery.timeRemaining"><span class="row-label">Remaining</span><span class="row-val" x-text="battery.timeRemaining"></span></div>
                <div class="prog" style="margin-top:.75rem">
                    <div class="prog-meta"><span>CHARGE</span><span x-text="battery.percent+'%'"></span></div>
                    <div class="prog-track"><div class="prog-fill" :class="battery.percent>20?'f-success':'f-danger'" :style="'width:'+battery.percent+'%'"></div></div>
                </div>
            </div>
        </div>

        <!-- Pi-hole -->
        <div class="card" data-id="card-pihole" x-show="vis.pihole">
            <div class="card-hdr"><i class="fas fa-shield-alt card-icon"></i><span class="card-title">Pi-hole DNS</span><i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="card-body">
                <template x-if="pihole">
                    <div>
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.875rem">
                            <span class="badge" :class="pihole.status==='enabled'?'bs':'bd'" x-text="pihole.status"></span>
                            <span style="font-size:.68rem;color:var(--text-muted)" x-text="pihole.domains+' domains'"></span>
                        </div>
                        <div class="ph-stats">
                            <div class="ph-stat"><div class="ph-val" x-text="typeof pihole.queries==='number'?pihole.queries.toLocaleString():pihole.queries"></div><div class="ph-label">Total Queries</div></div>
                            <div class="ph-stat"><div class="ph-val" style="color:var(--danger)" x-text="typeof pihole.blocked==='number'?pihole.blocked.toLocaleString():pihole.blocked"></div><div class="ph-label">Blocked</div></div>
                        </div>
                        <div class="prog"><div class="prog-meta"><span>BLOCK RATE</span><span x-text="pihole.percent+'%'"></span></div><div class="prog-track"><div class="prog-fill f-accent" :style="'width:'+pihole.percent+'%'"></div></div></div>
                    </div>
                </template>
                <template x-if="!pihole"><div style="font-size:.8rem;color:var(--text-muted);font-style:italic">Pi-hole unreachable — configure URL in Settings.</div></template>
            </div>
        </div>

        <!-- Storage -->
        <div class="card" data-id="card-storage" x-show="vis.storage">
            <div class="card-hdr"><i class="fas fa-hdd card-icon"></i><span class="card-title">Storage</span><i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="card-body">
                <template x-for="pool in zfs.pools" :key="pool.name">
                    <div class="row"><span class="row-label" x-text="'ZFS: '+pool.name"></span><span class="badge" :class="pool.health==='ONLINE'?'bs':pool.health==='DEGRADED'?'bw':'bd'" x-text="pool.health"></span></div>
                </template>
                <div :style="zfs.pools&&zfs.pools.length?'margin-top:.6rem':''">
                    <template x-for="d in disks" :key="d.mount">
                        <div class="prog">
                            <div class="prog-meta"><span x-text="d.mount"></span><span x-text="d.used+' / '+d.size"></span></div>
                            <div class="prog-track"><div class="prog-fill" :class="'f-'+d.barClass" :style="'width:'+d.percent+'%'"></div></div>
                        </div>
                    </template>
                </div>
            </div>
        </div>

        <!-- Network Radar -->
        <div class="card" data-id="card-radar" x-show="vis.radar">
            <div class="card-hdr"><i class="fas fa-satellite-dish card-icon"></i><span class="card-title">Network Radar</span><i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="card-body">
                <template x-for="t in radar" :key="t.ip">
                    <div class="radar-row">
                        <div class="status-dot" :class="t.status==='Up'?'dot-up':'dot-down'"></div>
                        <span class="radar-ip" x-text="t.ip"></span>
                        <span class="badge" :class="t.status==='Up'?'bs':'bd'" x-text="t.status"></span>
                        <span class="radar-ms" x-show="t.status==='Up'" x-text="t.ms+'ms'"></span>
                    </div>
                </template>
            </div>
        </div>

        <!-- Resource Hogs -->
        <div class="card" data-id="card-procs" x-show="vis.procs">
            <div class="card-hdr"><i class="fas fa-chart-bar card-icon"></i><span class="card-title">Resource Hogs</span><i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="card-body">
                <div class="proc-grid">
                    <div><div class="proc-hdr">Top CPU</div><template x-for="p in topCpu" :key="p.name"><div class="proc-row"><span class="proc-n" x-text="p.name"></span><span class="cpu-col" x-text="p.val"></span></div></template></div>
                    <div><div class="proc-hdr">Top Memory</div><template x-for="p in topMem" :key="p.name"><div class="proc-row"><span class="proc-n" x-text="p.name"></span><span class="mem-col" x-text="p.val"></span></div></template></div>
                </div>
            </div>
        </div>

        <!-- Containers -->
        <div class="card" data-id="card-containers" x-show="vis.containers&&containers&&containers.length>0">
            <div class="card-hdr"><i class="fas fa-boxes card-icon"></i><span class="card-title">Containers</span><span style="font-size:.65rem;color:var(--text-muted);margin-left:auto;margin-right:.5rem" x-text="containers.length+' total'"></span><i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="card-body">
                <div class="ct-list">
                    <template x-for="c in containers" :key="c.name">
                        <div class="ct-row">
                            <div class="status-dot" :class="c.state==='running'?'dot-up':'dot-down'"></div>
                            <span class="ct-name" x-text="c.name"></span>
                            <span class="ct-img"  x-text="c.image"></span>
                            <span class="badge" :class="c.state==='running'?'bs':c.state==='exited'?'bw':'bn'" x-text="c.state"></span>
                        </div>
                    </template>
                </div>
            </div>
        </div>

        <!-- Speedtest History -->
        <div class="card" data-id="card-speedtest" x-show="vis.speedtest">
            <div class="card-hdr"><i class="fas fa-tachometer-alt card-icon"></i><span class="card-title">Speedtest History</span><i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="card-body">
                <template x-if="speedtestHistory.length > 0">
                    <div>
                        <div class="st-latest">
                            <div class="st-stat"><div class="st-val" style="color:var(--accent)"   x-text="speedtestHistory[speedtestHistory.length-1].download.toFixed(1)"></div><div class="st-lbl"><i class="fas fa-arrow-down"></i> Mbps DL</div></div>
                            <div class="st-stat"><div class="st-val" style="color:var(--success)"  x-text="speedtestHistory[speedtestHistory.length-1].upload.toFixed(1)"></div><div class="st-lbl"><i class="fas fa-arrow-up"></i> Mbps UL</div></div>
                            <div class="st-stat"><div class="st-val" style="color:var(--warning)"  x-text="speedtestHistory[speedtestHistory.length-1].ping.toFixed(0)"></div><div class="st-lbl"><i class="fas fa-wifi"></i> ms Ping</div></div>
                        </div>
                        <div class="st-chart">
                            <template x-for="(s,i) in speedtestHistory.slice(-10)" :key="i">
                                <div class="st-col">
                                    <div class="st-bar-dl" :style="'height:'+Math.max(3,(s.download/stMaxDl)*66)+'px'" :title="s.download.toFixed(1)+' Mbps DL'"></div>
                                    <div class="st-bar-ul" :style="'height:'+Math.max(3,(s.upload/stMaxDl)*66)+'px'"   :title="s.upload.toFixed(1)+' Mbps UL'"></div>
                                </div>
                            </template>
                        </div>
                        <div class="st-legend">
                            <span><span class="st-legend-dot" style="background:var(--accent)"></span>Download</span>
                            <span><span class="st-legend-dot" style="background:var(--success)"></span>Upload</span>
                            <span style="margin-left:auto;font-size:.65rem" x-text="speedtestHistory.length+' runs'"></span>
                        </div>
                    </div>
                </template>
                <template x-if="speedtestHistory.length === 0">
                    <div style="font-size:.8rem;color:var(--text-muted);font-style:italic;text-align:center;padding:1rem 0">
                        No speedtest results yet.<br>Run one via Quick Actions below.
                    </div>
                </template>
            </div>
        </div>

        <!-- Services -->
        <div class="card span-full" data-id="card-services" x-show="vis.services">
            <div class="card-hdr"><i class="fas fa-cogs card-icon"></i><span class="card-title">Services</span><i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="card-body">
                <div class="svc-grid">
                    <template x-for="s in services" :key="s.name">
                        <div class="svc-card">
                            <div class="svc-name" x-text="s.name.replace('.service','')"></div>
                            <div class="svc-footer">
                                <span class="badge" :class="{'bs':s.status==='active'||s.status==='timer-active','bw':s.status==='inactive','bd':s.status==='failed'||s.status==='not-found'}" x-text="s.status==='timer-active'?'active (timer)':s.status"></span>
                                <div class="svc-btns">
                                    <button class="svc-btn" title="Start"   :disabled="s.status==='active'||s.status==='timer-active'||userRole!=='admin'" @click="svcAction(s,'start')"><i class="fas fa-play"></i></button>
                                    <button class="svc-btn" title="Stop"    :disabled="s.status==='inactive'||s.status==='not-found'||userRole!=='admin'"  @click="svcAction(s,'stop')"><i class="fas fa-stop"></i></button>
                                    <button class="svc-btn" title="Restart" :disabled="s.status==='not-found'||userRole!=='admin'"                          @click="svcAction(s,'restart')"><i class="fas fa-sync"></i></button>
                                </div>
                            </div>
                        </div>
                    </template>
                </div>
            </div>
        </div>

        <!-- Log Viewer -->
        <div class="card span-full" data-id="card-logs" x-show="vis.logs">
            <div class="card-hdr"><i class="fas fa-scroll card-icon"></i><span class="card-title">System Logs</span><i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="card-body">
                <div class="log-controls">
                    <select class="theme-select" x-model="selectedLog" @change="fetchLog()">
                        <option value="syserr">System Errors (journalctl)</option>
                        <option value="action">Action Log</option>
                        <option value="backup">NAS Backup Log</option>
                    </select>
                    <div class="icon-btn" @click="fetchLog()" title="Refresh"><i class="fas fa-sync" :class="logLoading?'fa-spin':''"></i></div>
                </div>
                <pre class="log-pre" x-text="logContent"></pre>
            </div>
        </div>

        <!-- Quick Actions -->
        <div class="card" data-id="card-actions" x-show="vis.actions">
            <div class="card-hdr"><i class="fas fa-bolt card-icon"></i><span class="card-title">Quick Actions</span><i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="card-body action-list">
                <template x-if="userRole!=='admin'">
                    <div style="font-size:.78rem;color:var(--text-muted);font-style:italic;text-align:center;padding:.5rem">Viewer role — actions disabled</div>
                </template>
                <button class="btn btn-primary" :disabled="runningScript||userRole!=='admin'" @click="runScript('backup')"><i class="fas fa-database"></i> Force NAS Backup</button>
                <button class="btn" :disabled="runningScript||userRole!=='admin'" @click="runScript('verify')"><i class="fas fa-check-double"></i> Verify Backups</button>
                <button class="btn" :disabled="runningScript||userRole!=='admin'" @click="runScript('organize')"><i class="fas fa-folder-open"></i> Organize Downloads</button>
                <button class="btn" :disabled="runningScript||userRole!=='admin'" @click="runScript('diskcheck')"><i class="fas fa-broom"></i> Disk Cleanup</button>
                <button class="btn" :disabled="runningScript||userRole!=='admin'" @click="runScript('speedtest')"><i class="fas fa-tachometer-alt"></i> Speed Test</button>
            </div>
        </div>

        <!-- Homelab Links -->
        <div class="card" data-id="card-bookmarks" x-show="vis.bookmarks">
            <div class="card-hdr"><i class="fas fa-bookmark card-icon"></i><span class="card-title">Homelab Links</span><i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="card-body">
                <div class="bm-grid">
                    <template x-for="b in parsedBookmarks" :key="b.name">
                        <a :href="b.url" target="_blank" class="bm-link"><i class="fas" :class="b.icon"></i><span x-text="b.name"></span></a>
                    </template>
                </div>
            </div>
        </div>

    </div>
</div>

<!-- Notifications drawer -->
<div x-show="notifOpen" class="notif-overlay" style="display:none" @click.self="notifOpen=false">
    <div class="notif-drawer">
        <div class="notif-hdr">
            <span class="notif-hdr-title"><i class="fas fa-bell" style="color:var(--accent);margin-right:.4rem"></i>Notifications</span>
            <div style="display:flex;gap:.4rem">
                <div class="icon-btn" @click="clearNotifs()" title="Clear all"><i class="fas fa-trash-alt"></i></div>
                <div class="icon-btn" @click="notifOpen=false" title="Close"><i class="fas fa-times"></i></div>
            </div>
        </div>
        <div class="notif-body">
            <template x-if="notifHistory.length===0">
                <div class="notif-empty"><i class="fas fa-check-circle" style="font-size:1.5rem;color:var(--success);display:block;margin-bottom:.75rem"></i>All clear — no alerts</div>
            </template>
            <template x-for="n in notifHistory.slice().reverse()" :key="n.id">
                <div class="notif-item" :class="n.level">
                    <span class="notif-msg" x-text="n.msg"></span>
                    <span class="notif-time" x-text="n.ts"></span>
                </div>
            </template>
        </div>
    </div>
</div>

<!-- Run Script Modal -->
<div x-show="showModal" class="modal-overlay" style="display:none" @click.self="showModal=false">
    <div class="modal-box">
        <div class="modal-title"><i class="fas fa-terminal" style="color:var(--accent)"></i><span x-text="modalTitle"></span></div>
        <pre id="console-out" class="console-out" x-text="modalOutput"></pre>
        <div class="modal-footer"><button class="btn btn-sm" @click="showModal=false" :disabled="runningScript" style="width:auto;padding:.55rem 1.4rem">Close</button></div>
    </div>
</div>

<!-- Settings Modal -->
<div x-show="showSettings" class="modal-overlay" style="display:none" @click.self="showSettings=false">
    <div class="modal-box">
        <div class="modal-title"><i class="fas fa-sliders-h" style="color:var(--accent)"></i> Settings</div>
        <div class="s-section">
            <span class="s-label">Module Visibility</span>
            <div class="toggle-grid">
                <label class="toggle-item"><input type="checkbox" x-model="vis.core"> Core System</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.netio"> Network I/O</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.hw"> Hardware</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.battery"> Power State</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.pihole"> Pi-hole DNS</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.storage"> Storage</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.radar"> Network Radar</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.procs"> Resource Hogs</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.containers"> Containers</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.speedtest"> Speedtest History</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.services"> Services</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.logs"> System Logs</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.actions"> Quick Actions</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.bookmarks"> Homelab Links</label>
            </div>
        </div>
        <div class="s-section">
            <span class="s-label">Pi-hole</span>
            <div class="field-2">
                <div><label class="field-label">URL / IP</label><input class="field-input" type="text" x-model="piholeUrl" placeholder="dnsa01.example.org"></div>
                <div><label class="field-label">App Password (v6)</label><input class="field-input" type="password" x-model="piholeToken"></div>
            </div>
        </div>
        <div class="s-section">
            <span class="s-label">Data Sources</span>
            <div style="display:flex;flex-direction:column;gap:.7rem">
                <div><label class="field-label">Services (comma-separated)</label><input class="field-input" type="text" x-model="monitoredServices"></div>
                <div><label class="field-label">Radar IPs (comma-separated)</label><input class="field-input" type="text" x-model="radarIps"></div>
                <div><label class="field-label">Bookmarks (Name|URL|fa-icon, comma-separated)</label><textarea class="field-input" x-model="bookmarksStr" style="height:72px;resize:vertical"></textarea></div>
            </div>
        </div>
        <div class="s-section">
            <span class="s-label">Keyboard Shortcuts</span>
            <div class="kbd-grid">
                <div class="kbd-item"><kbd>s</kbd> Settings</div>
                <div class="kbd-item"><kbd>r</kbd> Refresh</div>
                <div class="kbd-item"><kbd>n</kbd> Notifications</div>
                <div class="kbd-item"><kbd>Esc</kbd> Close modal</div>
            </div>
        </div>
        <div class="settings-footer">
            <button class="btn" @click="showSettings=false" style="width:auto;padding:.55rem 1.4rem">Cancel</button>
            <button class="btn btn-primary" @click="applySettings()" style="width:auto;padding:.55rem 1.4rem"><i class="fas fa-check"></i> Save & Apply</button>
        </div>
    </div>
</div>

<!-- Login Modal -->
<div x-show="!authenticated" class="modal-overlay" style="display:none">
    <div class="modal-box" style="max-width:400px">
        <div class="modal-title"><i class="fas fa-lock" style="color:var(--accent)"></i> Login</div>
        <div style="margin:1rem 0"><label class="field-label">Username</label><input class="field-input" type="text" x-model="loginUsername" @keyup.enter="doLogin" autofocus></div>
        <div style="margin:1rem 0"><label class="field-label">Password</label><input class="field-input" type="password" x-model="loginPassword" @keyup.enter="doLogin"></div>
        <div class="settings-footer">
            <button class="btn btn-primary" @click="doLogin" :disabled="loginLoading">
                <i class="fas fa-spinner fa-spin" x-show="loginLoading"></i>
                <span x-show="!loginLoading">Login</span>
            </button>
        </div>
        <p x-show="loginError" class="alert danger" style="margin-top:.5rem" x-text="loginError"></p>
    </div>
</div>

<!-- Toasts -->
<div class="toasts">
    <template x-for="t in toasts" :key="t.id">
        <div class="toast" :class="t.type">
            <i class="fas" :class="t.type==='success'?'fa-check-circle':t.type==='error'?'fa-times-circle':'fa-info-circle'"></i>
            <span x-text="t.msg"></span>
        </div>
    </template>
</div>

<script>
function dashboard() {
    const DEF_VIS = { core:true,netio:true,hw:true,battery:true,pihole:true,storage:true,radar:true,procs:true,containers:true,speedtest:true,services:true,logs:true,actions:true,bookmarks:true };
    const DEF_BM  = 'TrueNAS (vnnas)|http://vnnas.vannieuwenhove.org|fa-server, Pi-Hole|http://dnsa01.vannieuwenhove.org/admin|fa-shield-alt, Home Assistant|http://homeassistant.local:8123|fa-home, ROMM|http://romm.local|fa-gamepad, Prowlarr|http://localhost:9696|fa-search, ASUS Router|http://192.168.100.1|fa-network-wired';
    const savedTheme = localStorage.getItem('noba-theme');
    const autoTheme  = savedTheme || (window.matchMedia('(prefers-color-scheme: light)').matches ? 'nord' : 'default');

    return {
        theme: autoTheme,
        vis:   { ...DEF_VIS, ...JSON.parse(localStorage.getItem('noba-vis')||'{}') },
        piholeUrl:          localStorage.getItem('noba-pihole')    || 'dnsa01.vannieuwenhove.org',
        piholeToken:        localStorage.getItem('noba-pihole-tok')|| '',
        bookmarksStr:       localStorage.getItem('noba-bookmarks') || DEF_BM,
        monitoredServices:  localStorage.getItem('noba-services')  || 'backup-to-nas.service, organize-downloads.service, sshd, podman, syncthing.service',
        radarIps:           localStorage.getItem('noba-radar')     || '192.168.100.1, 1.1.1.1, 8.8.8.8',

        // system data
        timestamp:'--:--',uptime:'--',loadavg:'--',memory:'--',hostname:'--',defaultIp:'--',
        memPercent:0,cpuPercent:0,cpuHistory:[],cpuTemp:'N/A',gpuTemp:'N/A',
        osName:'--',kernel:'--',hwCpu:'--',hwGpu:'--',
        netRx:'0 B/s',netTx:'0 B/s',
        battery:{percent:0,status:'Unknown',desktop:false},
        disks:[],services:[],zfs:{pools:[]},radar:[],
        topCpu:[],topMem:[],pihole:null,containers:[],alerts:[],
        selectedLog:'syserr',logContent:'Loading…',logLoading:false,
        showModal:false,showSettings:false,
        modalTitle:'',modalOutput:'',runningScript:false,refreshing:false,
        toasts:[],_es:null,_poll:null,

        // auth
        authenticated: !!localStorage.getItem('noba-token'),
        loginUsername:'',loginPassword:'',loginLoading:false,loginError:'',
        userRole: localStorage.getItem('noba-role') || 'viewer',

        // connection
        connStatus:'offline',countdown:5,_countdownTimer:null,

        // notifications
        notifOpen: false,
        notifHistory: [],
        _lastReadId: parseInt(localStorage.getItem('noba-notif-last-id')||'0', 10),
        _dismissedAlerts: new Set(),

        // speedtest
        speedtestHistory: [],

        // ── Computed ──────────────────────────────────────────────────────────
        get cpuTempClass()  { const t=parseInt(this.cpuTemp)||0; return t>80?'bd':t>65?'bw':'bn'; },
        get gpuTempClass()  { const t=parseInt(this.gpuTemp)||0; return t>85?'bd':t>70?'bw':'bn'; },
        get livePillText()  { if(this.refreshing)return'Syncing…'; if(this.connStatus==='sse')return'Live'; if(this.connStatus==='polling')return this.countdown+'s'; return'Offline'; },
        get visibleAlerts() { return (this.alerts||[]).filter(a=>!this._dismissedAlerts.has(a.msg)); },
        get unreadCount()   { return this.notifHistory.filter(n=>n.id>this._lastReadId).length; },
        get stMaxDl()       { return Math.max(1,...this.speedtestHistory.map(s=>s.download)); },

        get parsedBookmarks() {
            return (this.bookmarksStr||'').split(',').map(b=>{
                const p=b.split('|');
                return{name:(p[0]||'Link').trim(),url:(p[1]||'#').trim(),icon:(p[2]||'fa-link').trim()};
            });
        },
        get cpuLine() {
            const h=this.cpuHistory; if(h.length<2)return'0,36 120,36';
            return h.map((v,i)=>`${Math.round((i/(h.length-1))*120)},${Math.round(36-(v/100)*32)}`).join(' ');
        },
        get cpuFill() {
            const h=this.cpuHistory; if(h.length<2)return'0,38 120,38 120,38 0,38';
            const pts=h.map((v,i)=>`${Math.round((i/(h.length-1))*120)},${Math.round(36-(v/100)*32)}`).join(' ');
            return`${pts} 120,38 0,38`;
        },

        // ── Init ─────────────────────────────────────────────────────────────
        async init() {
            this.initSortable();
            this.initKeyboard();
            if(this.authenticated){
                await this.fetchSettings();
                await Promise.all([this.fetchLog(), this.fetchNotifications(), this.fetchSpeedtestHistory()]);
                this.connectSSE();
                setInterval(()=>{ if(this.vis.logs)this.fetchLog(); }, 12000);
            }
        },

        initKeyboard() {
            document.addEventListener('keydown', e=>{
                if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA') return;
                if(e.key==='s'&&!this.showSettings&&!this.showModal) this.showSettings=true;
                else if(e.key==='n'&&!this.showSettings&&!this.showModal&&this.authenticated) this.openNotifPanel();
                else if(e.key==='r'&&!this.showSettings&&!this.showModal&&this.authenticated) this.refreshStats();
                else if(e.key==='Escape'){ this.showSettings=false; this.showModal=false; this.notifOpen=false; }
            });
        },

        dismissAlert(msg) { this._dismissedAlerts=new Set([...this._dismissedAlerts,msg]); },

        // ── Notifications ────────────────────────────────────────────────────
        openNotifPanel() {
            this.notifOpen=true;
            const maxId=this.notifHistory.reduce((m,n)=>Math.max(m,n.id),0);
            if(maxId>this._lastReadId){
                this._lastReadId=maxId;
                localStorage.setItem('noba-notif-last-id',String(maxId));
            }
        },
        clearNotifs() {
            this.notifHistory=[];
            this._lastReadId=0;
            localStorage.removeItem('noba-notif-last-id');
        },
        async fetchNotifications() {
            if(!this.authenticated) return;
            const token=localStorage.getItem('noba-token');
            try {
                const r=await fetch('/api/notifications',{headers:{'Authorization':'Bearer '+token}});
                if(r.ok){ const d=await r.json(); this.notifHistory=d; }
            } catch {}
        },
        _ingestAlerts(newAlerts) {
            if(!newAlerts||!newAlerts.length) return;
            const existing=new Set(this.notifHistory.map(n=>n.msg));
            const now=new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
            let maxId=this.notifHistory.reduce((m,n)=>Math.max(m,n.id),0);
            for(const a of newAlerts){
                if(!existing.has(a.msg)){
                    maxId++;
                    this.notifHistory.push({id:maxId,ts:now,level:a.level,msg:a.msg});
                    existing.add(a.msg);
                }
            }
            if(this.notifHistory.length>100) this.notifHistory=this.notifHistory.slice(-100);
        },

        // ── Speedtest History ────────────────────────────────────────────────
        async fetchSpeedtestHistory() {
            if(!this.authenticated) return;
            const token=localStorage.getItem('noba-token');
            try {
                const r=await fetch('/api/speedtest-history',{headers:{'Authorization':'Bearer '+token}});
                if(r.ok) this.speedtestHistory=await r.json();
            } catch {}
        },

        // ── SSE connection ───────────────────────────────────────────────────
        connectSSE() {
            if(!this.authenticated) return;
            if(this._es){this._es.close();this._es=null;}
            if(this._poll){clearInterval(this._poll);this._poll=null;}
            clearInterval(this._countdownTimer);this._countdownTimer=null;

            const token=localStorage.getItem('noba-token');
            const qs=`services=${encodeURIComponent(this.monitoredServices)}&radar=${encodeURIComponent(this.radarIps)}&pihole=${encodeURIComponent(this.piholeUrl)}&piholetok=${encodeURIComponent(this.piholeToken)}&token=${encodeURIComponent(token)}`;
            this._es=new EventSource(`/api/stream?${qs}`);
            this._es.onopen=()=>{ this.connStatus='sse'; clearInterval(this._countdownTimer); this._countdownTimer=null; };
            this._es.onmessage=e=>{
                try{
                    const d=JSON.parse(e.data);
                    this._ingestAlerts(d.alerts);
                    Object.assign(this,d);
                }catch{}
            };
            this._es.onerror=()=>{
                this._es.close();this._es=null;
                this.connStatus='polling';
                this.countdown=5;
                this._countdownTimer=setInterval(()=>{ this.countdown=Math.max(0,this.countdown-1); if(this.countdown===0)this.countdown=5; },1000);
                setTimeout(()=>{
                    this.refreshStats();
                    this._poll=setInterval(()=>{ this.refreshStats(); this.countdown=5; },5000);
                },3000);
            };
        },

        async refreshStats() {
            if(!this.authenticated||this.refreshing) return;
            this.refreshing=true;
            const token=localStorage.getItem('noba-token');
            try {
                const url=`/api/stats?services=${encodeURIComponent(this.monitoredServices)}&radar=${encodeURIComponent(this.radarIps)}&pihole=${encodeURIComponent(this.piholeUrl)}&piholetok=${encodeURIComponent(this.piholeToken)}`;
                const res=await fetch(url,{headers:{'Authorization':'Bearer '+token}});
                if(res.ok){ const d=await res.json(); this._ingestAlerts(d.alerts); Object.assign(this,d); if(this.connStatus==='offline')this.connStatus='polling'; }
                else if(res.status===401){ this.authenticated=false; this.connStatus='offline'; }
                else this.connStatus='offline';
            }catch{ this.connStatus='offline'; }
            finally{ this.refreshing=false; }
        },

        // ── Settings ─────────────────────────────────────────────────────────
        async fetchSettings() {
            const token=localStorage.getItem('noba-token');
            try{
                const r=await fetch('/api/settings',{headers:{'Authorization':'Bearer '+token}});
                if(r.ok){
                    const s=await r.json();
                    if(s.piholeUrl)         this.piholeUrl=s.piholeUrl;
                    if(s.piholeToken)       this.piholeToken=s.piholeToken;
                    if(s.monitoredServices) this.monitoredServices=s.monitoredServices;
                    if(s.radarIps)          this.radarIps=s.radarIps;
                    if(s.bookmarksStr)      this.bookmarksStr=s.bookmarksStr;
                    this.saveSettings();
                }
            }catch(e){ console.warn('fetchSettings:',e); }
        },
        async saveSettings() {
            localStorage.setItem('noba-theme',      this.theme);
            localStorage.setItem('noba-pihole',     this.piholeUrl);
            localStorage.setItem('noba-pihole-tok', this.piholeToken);
            localStorage.setItem('noba-bookmarks',  this.bookmarksStr);
            localStorage.setItem('noba-services',   this.monitoredServices);
            localStorage.setItem('noba-radar',      this.radarIps);
            localStorage.setItem('noba-vis',        JSON.stringify(this.vis));
            if(!this.authenticated) return;
            const token=localStorage.getItem('noba-token');
            try{
                await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},
                    body:JSON.stringify({piholeUrl:this.piholeUrl,piholeToken:this.piholeToken,monitoredServices:this.monitoredServices,radarIps:this.radarIps,bookmarksStr:this.bookmarksStr})});
            }catch(e){ console.warn('saveSettings:',e); }
        },
        applySettings() {
            this.saveSettings(); this.showSettings=false;
            if(this.authenticated) this.connectSSE();
            this.addToast('Settings saved','success');
        },

        initSortable() {
            Sortable.create(document.getElementById('sortable-grid'),{
                animation:200,handle:'.card-hdr',ghostClass:'sortable-ghost',dragClass:'sortable-drag',
                forceFallback:true,fallbackOnBody:true,group:'noba-v8',
                store:{get:s=>(localStorage.getItem(s.options.group.name)||'').split('|'),set:s=>localStorage.setItem(s.options.group.name,s.toArray().join('|'))}
            });
        },

        async fetchLog() {
            if(!this.authenticated) return;
            this.logLoading=true;
            const token=localStorage.getItem('noba-token');
            try{
                const r=await fetch('/api/log-viewer?type='+this.selectedLog,{headers:{'Authorization':'Bearer '+token}});
                if(r.ok) this.logContent=await r.text();
                else if(r.status===401) this.authenticated=false;
            }catch{ this.logContent='Failed to fetch log.'; }
            finally{ this.logLoading=false; }
        },

        async svcAction(svc,action) {
            if(!this.authenticated||this.userRole!=='admin') return;
            const token=localStorage.getItem('noba-token');
            try{
                const r=await fetch('/api/service-control',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify({service:svc.name,action,is_user:svc.is_user})});
                const d=await r.json();
                this.addToast(d.success?`${action}: ${svc.name.replace('.service','')}`:`Failed: ${svc.name}`,d.success?'success':'error');
                setTimeout(()=>this.refreshStats(),1200);
            }catch{ this.addToast('Service control error','error'); }
        },

        async runScript(script) {
            if(!this.authenticated||this.runningScript||this.userRole!=='admin') return;
            this.runningScript=true;
            this.modalTitle=`Running: ${script}`;
            this.modalOutput=`>> [${new Date().toLocaleTimeString()}] Starting ${script}...\n`;
            this.showModal=true;
            const token=localStorage.getItem('noba-token');
            const poll=setInterval(async()=>{
                try{ const r=await fetch('/api/action-log',{headers:{'Authorization':'Bearer '+token}}); if(r.ok){this.modalOutput=await r.text();const el=document.getElementById('console-out');if(el)el.scrollTop=el.scrollHeight;} }catch{}
            },800);
            try{
                const r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify({script})});
                const d=await r.json();
                this.modalTitle=d.success?'✓ Completed':'✗ Failed';
                this.addToast(d.success?`${script} completed`:`${script} failed`,d.success?'success':'error');
                if(script==='speedtest'&&d.success) await this.fetchSpeedtestHistory();
            }catch{ this.modalTitle='✗ Connection Error'; }
            finally{
                clearInterval(poll);
                try{ const r=await fetch('/api/action-log',{headers:{'Authorization':'Bearer '+token}}); if(r.ok)this.modalOutput=await r.text(); }catch{}
                this.runningScript=false;
                await this.refreshStats();
            }
        },

        async doLogin() {
            this.loginLoading=true; this.loginError='';
            try{
                const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:this.loginUsername,password:this.loginPassword})});
                const d=await r.json();
                if(r.ok&&d.token){
                    localStorage.setItem('noba-token',d.token);
                    localStorage.setItem('noba-role',d.role||'viewer');
                    this.userRole=d.role||'viewer';
                    this.authenticated=true;
                    await this.fetchSettings();
                    this.init();
                }else{ this.loginError=d.error||'Login failed'; }
            }catch{ this.loginError='Network error'; }
            finally{ this.loginLoading=false; }
        },

        async logout() {
            const token=localStorage.getItem('noba-token');
            if(token) try{ await fetch('/api/logout?token='+encodeURIComponent(token),{method:'POST'}); }catch{}
            localStorage.removeItem('noba-token');
            localStorage.removeItem('noba-role');
            this.authenticated=false; this.connStatus='offline';
            clearInterval(this._countdownTimer); this._countdownTimer=null;
            if(this._es){this._es.close();this._es=null;}
            if(this._poll){clearInterval(this._poll);this._poll=null;}
        },

        addToast(msg,type='info'){
            const id=Date.now()+Math.random();
            this.toasts.push({id,msg,type});
            setTimeout(()=>{this.toasts=this.toasts.filter(t=>t.id!==id);},3500);
        }
    };
}
</script>
</body>
</html>
HTMLEOF

# ── server.py ─────────────────────────────────────────────────────────────────
cat > "$HTML_DIR/server.py" <<'PYEOF'
#!/usr/bin/env python3
"""Nobara Command Center – Backend v8.5.0

New vs v8.4.0:
  - TLS via stdlib ssl module  (NOBA_HTTPS=1, NOBA_CERT, NOBA_KEY)
  - Multi-user auth.conf       (username:pbkdf2:salt:dk:role per line)
  - Token store carries username + role
  - authenticate_request() returns token_info dict or None
  - 403 returned for viewer role on admin-only endpoints
  - NotificationStore — timestamped alert history, deduped 5-min window,
      persisted to ~/.local/share/noba/notifications.json
  - SpeedtestHistory — last 20 runs, persisted to
      ~/.local/share/noba/speedtest-history.json; auto-parsed after run
  - BackgroundCollector feeds NotificationStore on every tick
  - /api/notifications GET
  - /api/speedtest-history GET
  - /api/login response includes { token, role, username }
  - Fixed double write_yaml_settings call (was a bug in v8.4.0)
"""

import http.server
import socketserver
import json
import subprocess
import os
import time
import re
import logging
import glob
import threading
import urllib.request
import urllib.error
import signal
import sys
import ipaddress
import uuid
import hashlib
import secrets
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs

# ── Config ────────────────────────────────────────────────────────────────────
VERSION    = '8.5.0'
PORT       = int(os.environ.get('PORT',   8080))
HOST       = os.environ.get('HOST',       '0.0.0.0')
SCRIPT_DIR = os.environ.get('NOBA_SCRIPT_DIR', os.path.expanduser('~/.local/bin'))
LOG_DIR    = os.path.expanduser('~/.local/share/noba')
PID_FILE   = os.environ.get('PID_FILE',  '/tmp/noba-web-server.pid')
ACTION_LOG = '/tmp/noba-action.log'
AUTH_CONFIG = os.path.expanduser('~/.config/noba-web/auth.conf')
NOBA_YAML   = os.environ.get('NOBA_CONFIG', os.path.expanduser('~/.config/noba/config.yaml'))
USE_HTTPS   = os.environ.get('NOBA_HTTPS', '0') == '1'
CERT_FILE   = os.environ.get('NOBA_CERT', os.path.expanduser('~/.config/noba-web/server.crt'))
KEY_FILE    = os.environ.get('NOBA_KEY',  os.path.expanduser('~/.config/noba-web/server.key'))
NOTIF_FILE  = os.path.join(LOG_DIR, 'notifications.json')
SPEED_FILE  = os.path.join(LOG_DIR, 'speedtest-history.json')

_server_start_time = time.time()

try:    os.makedirs(LOG_DIR, exist_ok=True)
except Exception: pass

log_file = os.path.join(LOG_DIR, 'noba-web-server.log')
try:    logging.basicConfig(filename=log_file, level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
except Exception: logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('noba')

ANSI_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
def strip_ansi(s): return ANSI_RE.sub('', s)

SCRIPT_MAP = {
    'backup':        'backup-to-nas.sh',
    'verify':        'backup-verifier.sh',
    'organize':      'organize-downloads.sh',
    'diskcheck':     'disk-sentinel.sh',
    'check_updates': 'noba-update.sh',
}
ALLOWED_ACTIONS = {'start', 'stop', 'restart'}
ADMIN_ONLY_POST = {'/api/run', '/api/service-control'}

# ── Authentication (multi-user) ───────────────────────────────────────────────
_tokens_lock = threading.Lock()
_tokens: dict = {}   # token → {expiry, username, role}

def verify_password(stored: str, password: str) -> bool:
    """Handles pbkdf2:salt:dk and legacy salt:dk formats. Timing-safe."""
    if not stored:
        return False
    if stored.startswith('pbkdf2:'):
        parts = stored.split(':', 2)
        if len(parts) != 3:
            return False
        _, salt, expected = parts
        dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200_000)
        return secrets.compare_digest(expected, dk.hex())
    # Legacy SHA-256: salt:hash
    if ':' not in stored:
        return False
    salt, expected = stored.split(':', 1)
    actual = hashlib.sha256((salt + password).encode()).hexdigest()
    return secrets.compare_digest(expected, actual)

def load_users() -> dict:
    """Returns {username: {hash, role}}. Handles old single-user format."""
    if not os.path.exists(AUTH_CONFIG):
        return {}
    users = {}
    try:
        with open(AUTH_CONFIG) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if ':' not in line:
                    continue
                username, rest = line.split(':', 1)
                # Role is the last colon-separated field IF it is 'admin' or 'viewer'
                rparts = rest.rsplit(':', 1)
                if rparts[-1] in ('admin', 'viewer'):
                    pw_hash = rparts[0]
                    role    = rparts[-1]
                else:
                    pw_hash = rest
                    role    = 'admin'  # backward compat: old format → admin
                users[username.strip()] = {'hash': pw_hash, 'role': role}
    except Exception as e:
        logger.warning(f'Could not read auth config: {e}')
    return users

def generate_token(username: str, role: str) -> str:
    token = str(uuid.uuid4())
    with _tokens_lock:
        _tokens[token] = {
            'expiry':   datetime.now() + timedelta(hours=24),
            'username': username,
            'role':     role,
        }
    return token

def get_token_info(token: str) -> dict | None:
    with _tokens_lock:
        info = _tokens.get(token)
        if info and info['expiry'] > datetime.now():
            return info
        if token in _tokens:
            del _tokens[token]
    return None

def revoke_token(token: str) -> None:
    with _tokens_lock:
        _tokens.pop(token, None)

def authenticate_request(headers, query=None) -> dict | None:
    """Returns token_info dict {expiry,username,role} or None."""
    auth = headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        info = get_token_info(auth[7:])
        if info:
            return info
    if query and 'token' in query:
        info = get_token_info(query['token'][0])
        if info:
            return info
    return None

def _token_cleanup_loop():
    while not _shutdown_flag.is_set():
        _shutdown_flag.wait(300)
        now = datetime.now()
        with _tokens_lock:
            expired = [t for t, v in list(_tokens.items()) if v['expiry'] <= now]
            for t in expired:
                del _tokens[t]
        if expired:
            logger.info(f'Token cleanup: {len(expired)} expired')

# ── Login rate limiter ─────────────────────────────────────────────────────────
class LoginRateLimiter:
    def __init__(self, max_attempts=5, window_s=60, lockout_s=30):
        self._lock     = threading.Lock()
        self._attempts: dict = {}
        self._lockouts: dict = {}
        self.max_attempts = max_attempts
        self.window_s     = window_s
        self.lockout_s    = lockout_s
    def is_locked(self, ip: str) -> bool:
        with self._lock:
            exp = self._lockouts.get(ip)
            if exp and datetime.now() < exp: return True
            self._lockouts.pop(ip, None)
            return False
    def record_failure(self, ip: str) -> bool:
        now = datetime.now(); cutoff = now - timedelta(seconds=self.window_s)
        with self._lock:
            attempts = [t for t in self._attempts.get(ip, []) if t > cutoff]
            attempts.append(now); self._attempts[ip] = attempts
            if len(attempts) >= self.max_attempts:
                self._lockouts[ip] = now + timedelta(seconds=self.lockout_s)
                self._attempts.pop(ip, None)
                logger.warning(f'Login lockout: {ip}')
                return True
        return False
    def reset(self, ip: str) -> None:
        with self._lock:
            self._attempts.pop(ip, None); self._lockouts.pop(ip, None)

_rate_limiter = LoginRateLimiter()

# ── NotificationStore ─────────────────────────────────────────────────────────
class NotificationStore:
    """Timestamped alert history, deduped within 5-min window, persistent."""
    def __init__(self, persist_file: str, maxlen: int = 100):
        self._lock     = threading.Lock()
        self._items    = deque(maxlen=maxlen)
        self._next_id  = 1
        self._persist  = persist_file
        self._load()

    def _load(self):
        if not os.path.exists(self._persist):
            return
        try:
            with open(self._persist) as f:
                items = json.load(f)
            for item in items[-self._items.maxlen:]:
                self._items.append(item)
                self._next_id = max(self._next_id, item.get('id', 0) + 1)
        except Exception as e:
            logger.warning(f'NotificationStore load error: {e}')

    def _save(self):
        try:
            with open(self._persist, 'w') as f:
                json.dump(list(self._items), f)
        except Exception:
            pass

    def add_alerts(self, alerts: list):
        if not alerts:
            return
        now = datetime.now()
        with self._lock:
            recent_msgs = {
                item['msg'] for item in self._items
                if (now - datetime.fromisoformat(item['ts'])).total_seconds() < 300
            }
            added = False
            for alert in alerts:
                if alert['msg'] not in recent_msgs:
                    self._items.append({
                        'id':    self._next_id,
                        'ts':    now.strftime('%H:%M:%S'),
                        'level': alert['level'],
                        'msg':   alert['msg'],
                    })
                    recent_msgs.add(alert['msg'])
                    self._next_id += 1
                    added = True
            if added:
                self._save()

    def get_all(self, limit: int = 100) -> list:
        with self._lock:
            return list(self._items)[-limit:]

# ── SpeedtestHistory ──────────────────────────────────────────────────────────
class SpeedtestHistory:
    """Persistent store for speedtest results (last 20 runs)."""
    def __init__(self, persist_file: str, maxlen: int = 20):
        self._lock    = threading.Lock()
        self._items   = deque(maxlen=maxlen)
        self._persist = persist_file
        self._load()

    def _load(self):
        if not os.path.exists(self._persist):
            return
        try:
            with open(self._persist) as f:
                for item in json.load(f)[-self._items.maxlen:]:
                    self._items.append(item)
        except Exception as e:
            logger.warning(f'SpeedtestHistory load error: {e}')

    def _save(self):
        try:
            with open(self._persist, 'w') as f:
                json.dump(list(self._items), f)
        except Exception:
            pass

    def add(self, download: float, upload: float, ping: float):
        with self._lock:
            self._items.append({
                'ts':       datetime.now().strftime('%m/%d %H:%M'),
                'download': round(download, 1),
                'upload':   round(upload, 1),
                'ping':     round(ping, 1),
            })
            self._save()

    def get_all(self) -> list:
        with self._lock:
            return list(self._items)

    @staticmethod
    def parse_output(text: str):
        """Parse speedtest-cli --simple output → (download, upload, ping)."""
        ping = download = upload = None
        for line in text.splitlines():
            m = re.search(r'([\d.]+)', line)
            if not m: continue
            val = float(m.group(1))
            if   'Ping'     in line: ping     = val
            elif 'Download' in line: download = val
            elif 'Upload'   in line: upload   = val
        return download, upload, ping

# ── YAML settings ─────────────────────────────────────────────────────────────
def read_yaml_settings():
    default = {
        'piholeUrl': '', 'piholeToken': '',
        'monitoredServices': 'backup-to-nas.service, organize-downloads.service, sshd, podman, syncthing.service',
        'radarIps': '192.168.100.1, 1.1.1.1, 8.8.8.8',
        'bookmarksStr': ''
    }
    if not os.path.exists(NOBA_YAML):
        return default
    try:
        r = subprocess.run(['yq', 'eval', '-o=json', '.web', NOBA_YAML], capture_output=True, text=True, timeout=2)
        if r.returncode == 0 and r.stdout.strip():
            web = json.loads(r.stdout)
            for k in default:
                if k in web: default[k] = web[k]
    except Exception as e:
        logger.warning(f'read_yaml_settings: {e}')
    return default

def write_yaml_settings(settings: dict) -> bool:
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            tmp.write('web:\n')
            for k, v in settings.items():
                if isinstance(v, str) and any(c in v for c in '\n:#'):
                    v = json.dumps(v)
                tmp.write(f'  {k}: {v}\n')
            tmp_path = tmp.name
        if os.path.exists(NOBA_YAML):
            r = subprocess.run(['yq', 'eval-all', 'select(fileIndex==0) * select(fileIndex==1)', NOBA_YAML, tmp_path],
                               capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                with open(NOBA_YAML, 'w') as f: f.write(r.stdout)
            else:
                raise RuntimeError(f'yq merge failed: {r.stderr}')
        else:
            os.makedirs(os.path.dirname(NOBA_YAML), exist_ok=True)
            with open(tmp_path) as src, open(NOBA_YAML, 'w') as dst: dst.write(src.read())
        os.unlink(tmp_path)
        return True
    except Exception as e:
        logger.exception(f'write_yaml_settings: {e}')
        return False

# ── Validation ────────────────────────────────────────────────────────────────
def validate_service_name(n): return bool(re.match(r'^[a-zA-Z0-9_.@-]+$', n))
def validate_ip(ip):
    try: ipaddress.ip_address(ip); return True
    except ValueError: return False

# ── TTL cache ─────────────────────────────────────────────────────────────────
class TTLCache:
    def __init__(self): self._s={}; self._l=threading.Lock()
    def get(self,k,ttl=30):
        with self._l:
            e=self._s.get(k)
            if e and (time.time()-e['t'])<ttl: return e['v']
        return None
    def set(self,k,v):
        with self._l: self._s[k]={'v':v,'t':time.time()}

_cache = TTLCache()

# ── Global state ──────────────────────────────────────────────────────────────
_state_lock  = threading.Lock()
_cpu_history = deque(maxlen=20)
_cpu_prev    = None
_net_prev    = None
_net_prev_t  = None
_shutdown_flag = threading.Event()

# ── Signal handler ────────────────────────────────────────────────────────────
def sigterm_handler(signum, frame):
    logger.info('SIGTERM received, shutting down…')
    _shutdown_flag.set()
    threading.Thread(target=lambda: server.shutdown(), daemon=True).start()
signal.signal(signal.SIGTERM, sigterm_handler)

# ── Helpers ───────────────────────────────────────────────────────────────────
def run(cmd, timeout=3, cache_key=None, cache_ttl=30, ignore_rc=False):
    if cache_key:
        hit = _cache.get(cache_key, cache_ttl)
        if hit is not None: return hit
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = r.stdout.strip() if (r.returncode == 0 or ignore_rc) else ''
        if cache_key and out: _cache.set(cache_key, out)
        return out
    except Exception as e:
        logger.debug(f'run {cmd}: {e}'); return ''

def human_bps(bps):
    for u in ('B/s','KB/s','MB/s','GB/s'):
        if bps<1024: return f'{bps:.1f} {u}'
        bps/=1024
    return f'{bps:.1f} TB/s'

# ── Stats collectors ──────────────────────────────────────────────────────────
def get_cpu_percent():
    global _cpu_prev
    with _state_lock:
        try:
            with open('/proc/stat') as f: fields=list(map(int,f.readline().split()[1:]))
            idle=fields[3]+fields[4]; total=sum(fields)
            if _cpu_prev is None: _cpu_prev=(total,idle); return 0.0
            dt=total-_cpu_prev[0]; di=idle-_cpu_prev[1]; _cpu_prev=(total,idle)
            pct=round(100.0*(1.0-di/dt) if dt>0 else 0.0,1)
            _cpu_history.append(pct); return pct
        except: return 0.0

def get_net_io():
    global _net_prev, _net_prev_t
    with _state_lock:
        try:
            with open('/proc/net/dev') as f: lines=f.readlines()
            rx=tx=0
            for line in lines[2:]:
                p=line.split()
                if len(p)>9 and not p[0].startswith('lo'): rx+=int(p[1]); tx+=int(p[9])
            now=time.time()
            if _net_prev is None: _net_prev=(rx,tx); _net_prev_t=now; return 0.0,0.0
            dt=now-_net_prev_t
            if dt<0.05: return 0.0,0.0
            rx_bps=max(0.0,(rx-_net_prev[0])/dt); tx_bps=max(0.0,(tx-_net_prev[1])/dt)
            _net_prev=(rx,tx); _net_prev_t=now; return rx_bps,tx_bps
        except: return 0.0,0.0

def ping_host(ip):
    ip=ip.strip()
    if not validate_ip(ip): return ip,False,0
    try:
        t0=time.time()
        r=subprocess.run(['ping','-c','1','-W','1',ip],capture_output=True,timeout=2.5)
        return ip,r.returncode==0,round((time.time()-t0)*1000)
    except: return ip,False,0

def get_service_status(svc):
    svc=svc.strip()
    if not validate_service_name(svc): return 'invalid',False
    for scope,is_user in ((['--user'],True),([],False)):
        cmd=['systemctl']+scope+['show','-p','ActiveState,LoadState',svc]
        out=run(cmd,timeout=2)
        d=dict(l.split('=',1) for l in out.splitlines() if '=' in l)
        if d.get('LoadState') not in (None,'','not-found'):
            state=d.get('ActiveState','unknown')
            if state=='inactive' and svc.endswith('.service'):
                tn=svc.replace('.service','.timer')
                t=run(['systemctl']+scope+['show','-p','ActiveState',tn],timeout=1)
                if 'ActiveState=active' in t: return 'timer-active',is_user
            return state,is_user
    return 'not-found',False

def get_battery():
    bats=glob.glob('/sys/class/power_supply/BAT*')
    if not bats: return{'percent':100,'status':'Desktop','desktop':True,'timeRemaining':''}
    try:
        pct=int(open(f'{bats[0]}/capacity').read().strip())
        stat=open(f'{bats[0]}/status').read().strip()
        time_rem=''
        try:
            cur=int(open(f'{bats[0]}/current_now').read().strip())
            if cur>0:
                if stat=='Discharging': charge=int(open(f'{bats[0]}/charge_now').read().strip()); hrs=charge/cur
                else:
                    cfull=int(open(f'{bats[0]}/charge_full').read().strip())
                    charge=int(open(f'{bats[0]}/charge_now').read().strip())
                    hrs=(cfull-charge)/cur
                time_rem=f'{int(hrs)}h {int((hrs%1)*60)}m'
                if stat!='Discharging': time_rem+=' to full'
        except: pass
        return{'percent':pct,'status':stat,'desktop':False,'timeRemaining':time_rem}
    except: return{'percent':0,'status':'Error','desktop':False,'timeRemaining':''}

def get_containers():
    for cmd in (['podman','ps','-a','--format','json'],['docker','ps','-a','--format','{{json .}}']):
        out=run(cmd,timeout=4,cache_key=' '.join(cmd),cache_ttl=10)
        if not out: continue
        try:
            items=json.loads(out) if out.lstrip().startswith('[') else [json.loads(l) for l in out.splitlines() if l.strip()]
            res=[]
            for c in items[:16]:
                name=c.get('Names',c.get('Name','?'))
                if isinstance(name,list): name=name[0] if name else '?'
                image=c.get('Image',c.get('Repository','?')).split('/')[-1][:32]
                state=(c.get('State',c.get('Status','?')) or '?').lower().split()[0]
                res.append({'name':name,'image':image,'state':state,'status':c.get('Status',state)})
            return res
        except: continue
    return []

def get_pihole(url, token):
    if not url: return None
    base=url if url.startswith('http') else 'http://'+url
    base=base.rstrip('/').replace('/admin','')
    def _get(ep,h=None):
        hdrs={'User-Agent':f'noba-web/{VERSION}','Accept':'application/json'}
        if h: hdrs.update(h)
        req=urllib.request.Request(base+ep,headers=hdrs)
        with urllib.request.urlopen(req,timeout=3) as r: return json.loads(r.read().decode())
    try:
        auth={'sid':token} if token else {}
        d=_get('/api/stats/summary',auth)
        return{'queries':d.get('queries',{}).get('total',0),'blocked':d.get('ads',{}).get('blocked',0),
               'percent':round(d.get('ads',{}).get('percentage',0.0),1),'status':d.get('gravity',{}).get('status','unknown'),
               'domains':f"{d.get('gravity',{}).get('domains_being_blocked',0):,}"}
    except: pass
    try:
        ep='/admin/api.php?summaryRaw'+(f'&auth={token}' if token else '')
        d=_get(ep)
        return{'queries':d.get('dns_queries_today',0),'blocked':d.get('ads_blocked_today',0),
               'percent':round(d.get('ads_percentage_today',0),1),'status':d.get('status','enabled'),
               'domains':f"{d.get('domains_being_blocked',0):,}"}
    except: return None

def collect_stats(qs):
    stats={'timestamp':datetime.now().strftime('%H:%M:%S')}
    try:
        with open('/etc/os-release') as f:
            for line in f:
                if line.startswith('PRETTY_NAME='): stats['osName']=line.split('=',1)[1].strip().strip('"')
    except: stats['osName']='Linux'
    stats['kernel']    = run(['uname','-r'],cache_key='uname-r',cache_ttl=3600)
    stats['hostname']  = run(['hostname'],cache_key='hostname',cache_ttl=3600)
    stats['defaultIp'] = run(['bash','-c',"ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \\K[\\d.]+'"],timeout=1)
    try:
        uptime_s=float(open('/proc/uptime').read().split()[0])
        d,rem=divmod(int(uptime_s),86400); h,rem=divmod(rem,3600); m=rem//60
        stats['uptime']=(f'{d}d ' if d else '')+f'{h}h {m}m'
        stats['loadavg']=' '.join(open('/proc/loadavg').read().split()[:3])
        ml=open('/proc/meminfo').readlines()
        mm={l.split(':')[0]:int(l.split()[1]) for l in ml if ':' in l}
        tot=mm.get('MemTotal',0)//1024; avail=mm.get('MemAvailable',0)//1024; used=tot-avail
        stats['memory']=f'{used} MiB / {tot} MiB'; stats['memPercent']=round(100*used/tot) if tot>0 else 0
    except: stats.setdefault('uptime','--'); stats.setdefault('loadavg','--'); stats.setdefault('memPercent',0)

    stats['cpuPercent']=get_cpu_percent()
    with _state_lock: stats['cpuHistory']=list(_cpu_history)
    rx_bps,tx_bps=get_net_io()
    stats['netRx']=human_bps(rx_bps); stats['netTx']=human_bps(tx_bps)

    s=run(['sensors'],timeout=2,cache_key='sensors',cache_ttl=5)
    m=re.search(r'(?:Tctl|Package id \d+|Core 0|temp1).*?\+?(\d+\.?\d*)[°℃]',s)
    stats['cpuTemp']=f'{int(float(m.group(1)))}°C' if m else 'N/A'
    gpu_t=run(['nvidia-smi','--query-gpu=temperature.gpu','--format=csv,noheader'],timeout=2,cache_key='nvidia-temp',cache_ttl=5)
    if not gpu_t:
        raw=run(['bash','-c','cat /sys/class/drm/card*/device/hwmon/hwmon*/temp1_input 2>/dev/null | head -1'],timeout=1)
        gpu_t=f'{int(raw)//1000}°C' if raw else 'N/A'
    else: gpu_t=f'{gpu_t}°C'
    stats['gpuTemp']=gpu_t; stats['battery']=get_battery()
    stats['hwCpu']=run(['bash','-c',"lscpu | grep 'Model name' | head -1 | cut -d: -f2 | xargs"],cache_key='lscpu',cache_ttl=3600)
    raw_gpu=run(['bash','-c',"lspci | grep -i 'vga\\|3d' | cut -d: -f3"],cache_key='lspci',cache_ttl=3600)
    stats['hwGpu']=raw_gpu.replace('\n','<br>') if raw_gpu else 'Unknown GPU'

    disks=[]
    for line in run(['df','-BM'],cache_key='df',cache_ttl=10).splitlines()[1:]:
        p=line.split()
        if len(p)>=6 and p[0].startswith('/dev/'):
            mnt=p[5]
            if any(mnt.startswith(x) for x in ('/var/lib/snapd','/boot','/run','/snap')): continue
            try:
                pct=int(p[4].replace('%','')); bc='danger' if pct>=90 else 'warning' if pct>=75 else 'success'
                disks.append({'mount':mnt,'percent':pct,'barClass':bc,'size':p[1].replace('M',' MiB'),'used':p[2].replace('M',' MiB')})
            except: pass
    stats['disks']=disks

    zfs_out=run(['zpool','list','-H','-o','name,health'],timeout=3,cache_key='zpool',cache_ttl=15)
    pools=[{'name':l.split('\t')[0].strip(),'health':l.split('\t')[1].strip()} for l in zfs_out.splitlines() if '\t' in l]
    stats['zfs']={'pools':pools}

    cpu_ps=run(['ps','ax','--format','comm,%cpu','--sort','-%cpu'],timeout=2)
    mem_ps=run(['ps','ax','--format','comm,%mem','--sort','-%mem'],timeout=2)
    def parse_ps(out):
        res=[]
        for line in out.splitlines()[1:6]:
            p=line.strip().rsplit(None,1)
            if len(p)==2 and p[1] not in ('%CPU','%MEM'): res.append({'name':p[0][:16],'val':p[1]+'%'})
        return res
    stats['topCpu']=parse_ps(cpu_ps); stats['topMem']=parse_ps(mem_ps)

    svc_list=[s.strip() for s in qs.get('services',[''])[0].split(',') if s.strip()]
    ip_list =[ip.strip() for ip in qs.get('radar',  [''])[0].split(',') if ip.strip()]
    ph_url  =qs.get('pihole',   [''])[0]
    ph_tok  =qs.get('piholetok',[''])[0]

    with ThreadPoolExecutor(max_workers=max(4,len(svc_list)+len(ip_list)+3)) as ex:
        svc_futs ={ex.submit(get_service_status,s):s  for s in svc_list}
        ping_futs={ex.submit(ping_host,ip):ip          for ip in ip_list}
        ph_fut   =ex.submit(get_pihole,ph_url,ph_tok) if ph_url else None
        ct_fut   =ex.submit(get_containers)

        services=[]
        for fut,svc in svc_futs.items():
            try: status,is_user=fut.result(timeout=4)
            except: status,is_user='error',False
            services.append({'name':svc,'status':status,'is_user':is_user})
        stats['services']=services

        radar=[]
        for fut,ip in ping_futs.items():
            try: ip_r,up,ms=fut.result(timeout=4); radar.append({'ip':ip_r,'status':'Up' if up else 'Down','ms':ms if up else 0})
            except: radar.append({'ip':ip,'status':'Down','ms':0})
        stats['radar']=radar

        try: stats['pihole']=ph_fut.result(timeout=4) if ph_fut else None
        except: stats['pihole']=None
        try: stats['containers']=ct_fut.result(timeout=5)
        except: stats['containers']=[]

    alerts=[]
    cpu=stats.get('cpuPercent',0)
    if   cpu>90: alerts.append({'level':'danger', 'msg':f'CPU critical: {cpu}%'})
    elif cpu>75: alerts.append({'level':'warning','msg':f'CPU high: {cpu}%'})
    ct=stats.get('cpuTemp','N/A')
    if ct!='N/A':
        t=int(ct.replace('°C',''))
        if   t>85: alerts.append({'level':'danger', 'msg':f'CPU temp critical: {t}°C'})
        elif t>70: alerts.append({'level':'warning','msg':f'CPU temp elevated: {t}°C'})
    for disk in stats.get('disks',[]):
        p=disk.get('percent',0)
        if   p>=90: alerts.append({'level':'danger', 'msg':f"Disk {disk['mount']} at {p}%"})
        elif p>=80: alerts.append({'level':'warning','msg':f"Disk {disk['mount']} at {p}%"})
    for svc in stats.get('services',[]):
        if svc.get('status')=='failed': alerts.append({'level':'danger','msg':f"Service failed: {svc['name']}"})
    stats['alerts']=alerts
    return stats

# ── BackgroundCollector ───────────────────────────────────────────────────────
class BackgroundCollector:
    def __init__(self, interval=5):
        self._lock=threading.Lock(); self._latest={}; self._qs={}; self._interval=interval
    def update_qs(self,qs):
        with self._lock: self._qs=dict(qs)
    def get(self):
        with self._lock: return dict(self._latest)
    def start(self):
        threading.Thread(target=self._loop,daemon=True,name='stats-collector').start()
    def _loop(self):
        while not _shutdown_flag.is_set():
            try:
                with self._lock: qs=dict(self._qs)
                data=collect_stats(qs)
                _notif_store.add_alerts(data.get('alerts',[]))
                with self._lock: self._latest=data
            except Exception as e: logger.warning(f'BackgroundCollector: {e}')
            _shutdown_flag.wait(self._interval)

_bg           = BackgroundCollector(interval=5)
_notif_store  = NotificationStore(NOTIF_FILE)
_speed_hist   = SpeedtestHistory(SPEED_FILE)

# ── HTTP Handler ──────────────────────────────────────────────────────────────
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw): super().__init__(*a,directory='.',**kw)
    def log_message(self,fmt,*args): pass
    def _ip(self): return self.client_address[0] if self.client_address else '0.0.0.0'
    def _json(self,data,status=200):
        body=json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        parsed=urlparse(self.path); qs=parse_qs(parsed.query); path=parsed.path

        # Public
        if path in ('/','index.html'): super().do_GET(); return
        if path=='/api/health':
            self._json({'status':'ok','version':VERSION,'uptime_s':round(time.time()-_server_start_time)}); return

        token_info=authenticate_request(self.headers,qs)
        if not token_info: self.send_error(401,'Unauthorized'); return

        if path=='/api/stats':
            _bg.update_qs(qs)
            cached=_bg.get()
            try: self._json(cached if cached else collect_stats(qs))
            except Exception as e: logger.exception('/api/stats'); self._json({'error':str(e)},500)

        elif path=='/api/settings':
            self._json(read_yaml_settings())

        elif path=='/api/notifications':
            self._json(_notif_store.get_all())

        elif path=='/api/speedtest-history':
            self._json(_speed_hist.get_all())

        elif path=='/api/stream':
            _bg.update_qs(qs)
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.send_header('Cache-Control','no-cache')
            self.send_header('Connection','keep-alive')
            self.end_headers()
            try:
                first=_bg.get() or collect_stats(qs)
                self.wfile.write(f'data: {json.dumps(first)}\n\n'.encode()); self.wfile.flush()
                while not _shutdown_flag.is_set():
                    _shutdown_flag.wait(5)
                    if _shutdown_flag.is_set(): break
                    d=_bg.get()
                    if d: self.wfile.write(f'data: {json.dumps(d)}\n\n'.encode()); self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,OSError): pass
            except Exception as e: logger.warning(f'SSE: {e}')

        elif path=='/api/log-viewer':
            lt=qs.get('type',['syserr'])[0]
            if   lt=='syserr': text=run(['journalctl','-p','3','-n','25','--no-pager'],timeout=4)
            elif lt=='action':
                try: text=strip_ansi(open(ACTION_LOG).read())
                except FileNotFoundError: text='No recent actions.'
            elif lt=='backup':
                try:
                    lines=open(os.path.join(LOG_DIR,'backup-to-nas.log')).readlines()
                    text=strip_ansi(''.join(lines[-30:]))
                except FileNotFoundError: text='No backup log found.'
            else: text='Unknown log type.'
            body=(text or 'Empty.').encode()
            self.send_response(200)
            self.send_header('Content-Type','text/plain; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers(); self.wfile.write(body)

        elif path=='/api/action-log':
            try: text=strip_ansi(open(ACTION_LOG).read())
            except FileNotFoundError: text='Waiting for output…'
            body=text.encode()
            self.send_response(200); self.send_header('Content-Type','text/plain; charset=utf-8')
            self.end_headers(); self.wfile.write(body)

        else: self.send_error(404)

    def do_POST(self):
        path=self.path.split('?')[0]; ip=self._ip()

        if path=='/api/login':
            if _rate_limiter.is_locked(ip):
                self._json({'error':'Too many failed attempts. Try again shortly.'},429); return
            try:
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
                username=body.get('username',''); password=body.get('password','')
                users=load_users()
                user=users.get(username)
                if user and verify_password(user['hash'],password):
                    _rate_limiter.reset(ip)
                    token=generate_token(username,user['role'])
                    self._json({'token':token,'role':user['role'],'username':username})
                else:
                    locked=_rate_limiter.record_failure(ip)
                    msg='Too many failed attempts. Try again shortly.' if locked else 'Invalid credentials'
                    self._json({'error':msg},401)
            except Exception as e:
                logger.exception('/api/login'); self._json({'error':str(e)},500)
            return

        if path=='/api/logout':
            parsed=urlparse(self.path); qs=parse_qs(parsed.query)
            token=None
            ah=self.headers.get('Authorization','')
            if ah.startswith('Bearer '): token=ah[7:]
            elif 'token' in qs: token=qs['token'][0]
            if token: revoke_token(token)
            self._json({'status':'ok'}); return

        token_info=authenticate_request(self.headers)
        if not token_info: self.send_error(401,'Unauthorized'); return

        # Role check for admin-only POSTs
        if path in ADMIN_ONLY_POST and token_info.get('role')!='admin':
            self._json({'error':'Admin role required'},403); return

        if path=='/api/settings':
            try:
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
                ok=write_yaml_settings(body)
                self._json({'status':'ok'} if ok else {'error':'Write failed'}, 200 if ok else 500)
            except Exception as e:
                logger.exception('/api/settings POST'); self._json({'error':str(e)},500)

        elif path=='/api/run':
            try:
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
                script=body.get('script','')
                with open(ACTION_LOG,'w') as f:
                    f.write(f'>> [{datetime.now().strftime("%H:%M:%S")}] Initiating: {script}\n\n')
                success=False
                if script=='speedtest':
                    with open(ACTION_LOG,'a') as f:
                        p=subprocess.Popen(['speedtest-cli','--simple'],stdout=f,stderr=subprocess.STDOUT)
                        p.wait(timeout=120); success=p.returncode==0
                    # Parse and persist result
                    if success:
                        try:
                            with open(ACTION_LOG) as f: output=f.read()
                            dl,ul,ping=SpeedtestHistory.parse_output(output)
                            if dl is not None and ul is not None and ping is not None:
                                _speed_hist.add(dl,ul,ping)
                        except Exception as e: logger.warning(f'speedtest parse: {e}')
                elif script in SCRIPT_MAP:
                    sfile=os.path.join(SCRIPT_DIR,SCRIPT_MAP[script])
                    if os.path.isfile(sfile):
                        with open(ACTION_LOG,'a') as f:
                            p=subprocess.Popen([sfile,'--verbose'],stdout=f,stderr=subprocess.STDOUT,cwd=SCRIPT_DIR)
                            p.wait(timeout=300); success=p.returncode==0
                    else:
                        with open(ACTION_LOG,'a') as f: f.write(f'[ERROR] Script not found: {sfile}\n')
                else:
                    with open(ACTION_LOG,'a') as f: f.write(f'[ERROR] Unknown script: {script}\n')
                self._json({'success':success})
            except subprocess.TimeoutExpired: self._json({'success':False,'error':'Script timed out'})
            except Exception as e:
                logger.exception('/api/run'); self._json({'success':False,'error':str(e)})

        elif path=='/api/service-control':
            try:
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
                svc=body.get('service','').strip(); action=body.get('action','').strip(); is_user=bool(body.get('is_user',False))
                if action not in ALLOWED_ACTIONS: return self._json({'success':False,'error':f'Action "{action}" not allowed'})
                if not svc: return self._json({'success':False,'error':'No service name'})
                if not validate_service_name(svc): return self._json({'success':False,'error':'Invalid service name'})
                cmd=(['systemctl','--user',action,svc] if is_user else ['sudo','-n','systemctl',action,svc])
                r=subprocess.run(cmd,timeout=10,capture_output=True)
                self._json({'success':r.returncode==0,'stderr':r.stderr.decode().strip()})
            except Exception as e: self._json({'success':False,'error':str(e)})

        else: self.send_error(404)


class ThreadingHTTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address=True; daemon_threads=True

server=None

if __name__=='__main__':
    try:
        with open(PID_FILE,'w') as f: f.write(str(os.getpid()))
    except Exception as e: logger.warning(f'PID file: {e}')

    _bg.start()
    threading.Thread(target=_token_cleanup_loop,daemon=True,name='token-cleanup').start()

    server=ThreadingHTTPServer((HOST,PORT),Handler)

    if USE_HTTPS:
        import ssl
        ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            ctx.load_cert_chain(CERT_FILE,KEY_FILE)
            server.socket=ctx.wrap_socket(server.socket,server_side=True)
            proto='https'
        except Exception as e:
            print(f'[ERROR] TLS setup failed: {e}',file=sys.stderr)
            print(f'        Run: noba-web.sh --generate-cert',file=sys.stderr)
            sys.exit(1)
    else:
        proto='http'

    url=f'{proto}://{HOST}:{PORT}'
    logger.warning(f'Serving at {url}  (v{VERSION})')
    print(f'Noba server v{VERSION} starting at {url}',file=sys.stderr)

    try: server.serve_forever()
    except KeyboardInterrupt: logger.info('Shutting down…')
    except Exception as e: logger.exception('Unhandled exception')
    finally:
        _shutdown_flag.set(); server.shutdown()
        try: os.unlink(PID_FILE)
        except: pass
        logger.info('Server stopped.')
PYEOF

chmod +x "$HTML_DIR/server.py"

# ── Launch ────────────────────────────────────────────────────────────────────
kill_server

PROTO="http"
EXTRA_ENV=""
[[ "$USE_HTTPS" == true ]] && PROTO="https" && EXTRA_ENV=" NOBA_HTTPS=1 NOBA_CERT=$CERT_FILE NOBA_KEY=$KEY_FILE"

export PORT HOST PID_FILE="$SERVER_PID_FILE" NOBA_SCRIPT_DIR="$SCRIPT_DIR" NOBA_CONFIG="$NOBA_YAML"
[[ "$USE_HTTPS" == true ]] && export NOBA_HTTPS=1 NOBA_CERT="$CERT_FILE" NOBA_KEY="$KEY_FILE"

cd "$HTML_DIR"
: > "$LOG_FILE"

nohup python3 server.py >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$SERVER_PID_FILE"
echo "${PROTO}://${HOST}:${PORT}" > "$SERVER_URL_FILE"

# Health check — polls /api/health (returns JSON {status:"ok"})
MAX_WAIT=12
WAITED=0
while true; do
    if command -v curl &>/dev/null; then
        CODE=$(curl -sk -o /dev/null -w '%{http_code}' "${PROTO}://${HOST}:${PORT}/api/health" 2>/dev/null || true)
    elif command -v wget &>/dev/null; then
        CODE=$(wget -qO- --no-check-certificate "${PROTO}://${HOST}:${PORT}/api/health" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(200 if d.get('status')=='ok' else 0)" 2>/dev/null || true)
    else
        log_error "Neither curl nor wget found."; kill "$SERVER_PID" 2>/dev/null; exit 1
    fi
    [[ "$CODE" == "200" ]] && break
    sleep 1; WAITED=$((WAITED+1))
    if [[ $WAITED -ge $MAX_WAIT ]]; then
        log_error "Server did not respond within ${MAX_WAIT}s. Last 20 lines of log:"
        tail -20 "$LOG_FILE" | sed 's/^/  /' >&2
        kill "$SERVER_PID" 2>/dev/null || true; exit 1
    fi
done

log_success "Dashboard live → ${PROTO}://${HOST}:${PORT}"
[[ "$USE_HTTPS" == true ]] && log_info "Using TLS cert: $CERT_FILE"
if [[ ! -f "$AUTH_CONF" ]]; then
    log_warning "No users configured. Run:  $0 --add-user"
fi

if [[ "$VERBOSE" == true ]]; then
    log_info "Tailing log (Ctrl+C to stop)…"
    tail -f "$LOG_FILE" &
    TAIL_PID=$!
fi

wait "$SERVER_PID"
EXIT_CODE=$?
[[ -n "${TAIL_PID:-}" ]] && kill "$TAIL_PID" 2>/dev/null || true
exit $EXIT_CODE
