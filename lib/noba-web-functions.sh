#!/usr/bin/env bash
# Shared functions for Noba Web – v1.11.0-sandbox
# Sourced by bin/noba-web — do NOT execute directly.

# ── Logging ───────────────────────────────────────────────────────────────────
_has_color() { [[ -t 1 ]]; }
_has_color_err() { [[ -t 2 ]]; }

log_info() {
    if _has_color; then
        echo -e "\033[1;34m[INFO]\033[0m $*"
    else
        echo "[INFO] $*"
    fi
}

log_success() {
    if _has_color; then
        echo -e "\033[1;32m[OK]\033[0m $*"
    else
        echo "[OK] $*"
    fi
}

log_warn() {
    if _has_color_err; then
        echo -e "\033[1;33m[WARN]\033[0m $*" >&2
    else
        echo "[WARN] $*" >&2
    fi
}

log_error() {
    if _has_color_err; then
        echo -e "\033[1;31m[ERROR]\033[0m $*" >&2
    else
        echo "[ERROR] $*" >&2
    fi
}

# ── Dependency check ──────────────────────────────────────────────────────────
check_deps() {
    local missing=()
    for dep in "$@"; do
        if ! command -v "$dep" &>/dev/null; then
            missing+=("$dep")
        fi
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required dependencies: ${missing[*]}"
        exit 1
    fi
}

# ── Network helpers ───────────────────────────────────────────────────────────
local_ip() {
    ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}' || echo "127.0.0.1"
}

# ── Process helpers ───────────────────────────────────────────────────────────
_is_running() {
    if [[ -n "${1:-}" ]]; then
        kill -0 "$1" 2>/dev/null
    else
        return 1
    fi
}

_read_pid() {
    if [[ -s "$1" ]]; then
        cat "$1"
    else
        return 1
    fi
}

# ── Kill server (strict safe removal) ─────────────────────────────────────────
kill_server() {
    local pid_file="$1"
    local url_file="$2"
    local html_dir="${3:-}"
    local pid

    if [[ -f "$pid_file" ]]; then
        pid=$(_read_pid "$pid_file" || true)

        if _is_running "$pid"; then
            log_info "Stopping server (PID $pid)…"
            kill -TERM "$pid" 2>/dev/null || true

            local i
            for i in {1..5}; do
                if ! _is_running "$pid"; then
                    break
                fi
                sleep 1
            done

            if _is_running "$pid"; then
                log_warn "Server did not stop gracefully — sending SIGKILL."
                kill -KILL "$pid" 2>/dev/null || true
            fi
        fi

        rm -f "$pid_file" "$url_file"
    fi

    # Strict Environment-Aware Cleanup: Only nuke ephemeral dev directories.
    # NEVER delete the persistent deployment or user home directory.
    if [[ -n "$html_dir" && -d "$html_dir" ]]; then
        if [[ "$html_dir" =~ ^(/tmp/|/var/tmp/) ]] && [[ ! "$html_dir" =~ ^$HOME ]]; then
            log_info "Cleaning up ephemeral sandbox: $html_dir"
            rm -rf "$html_dir"
        else
            log_info "Retaining persistent deployment directory: $html_dir"
        fi
    fi
}

# ── Show status (with uptime) ─────────────────────────────────────────────────
show_status() {
    local pid_file="$1"
    local url_file="$2"
    local log_file="$3"
    local pid url

    pid=$(_read_pid "$pid_file" || true)
    if [[ -z "$pid" ]]; then
        log_info "Server is not running."
        return
    fi

    url=$(cat "$url_file" 2>/dev/null || echo "unknown")

    if _is_running "$pid"; then
        local uptime_str=""
        if [[ -r "/proc/$pid/stat" ]]; then
            local start_ticks hz elapsed
            start_ticks=$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null || echo "")
            hz=$(getconf CLK_TCK 2>/dev/null || echo "100")
            if [[ -n "$start_ticks" ]]; then
                local uptime_s
                uptime_s=$(awk '{print int($1)}' /proc/uptime)
                elapsed=$(( uptime_s - start_ticks / hz ))
                local d h m
                d=$(( elapsed / 86400 ))
                h=$(( (elapsed % 86400) / 3600 ))
                m=$(( (elapsed % 3600) / 60 ))
                uptime_str="  uptime=${d}d${h}h${m}m"
            fi
        fi
        log_success "Server running PID=$pid URL=$url${uptime_str}"
        echo "  Log: $log_file"
    else
        log_warn "PID file present but server is not running (stale). Cleaning up."
        rm -f "$pid_file" "$url_file"
    fi
}

# ── Systemd unit generator (with hardening) ───────────────────────────────────
generate_systemd() {
    local self="$1"
    local host="$2"

    cat <<EOF
# Save to: ~/.config/systemd/user/noba-web.service
# Enable:  systemctl --user enable --now noba-web.service

[Unit]
Description=Noba Command Center Web Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=${self} --host ${host}
ExecStop=/bin/kill -TERM \$MAINPID
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=noba-web

# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=%h/.local %h/.config
RestrictSUIDSGID=true

[Install]
WantedBy=default.target
EOF
}

# ── Unified password hashing (PBKDF2-SHA256) ──────────────────────────────────
hash_password() {
    local raw_password="$1"
    python3 - "$raw_password" <<'PYEOF'
import hashlib, secrets, sys
password = sys.argv[1]
salt = secrets.token_hex(16)
dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200_000)
print(f"pbkdf2:{salt}:{dk.hex()}")
PYEOF
}

# ── Legacy single‑user setup (auth.conf) ─────────────────────────────────────
set_password() {
    local yaml_file="$1"
    echo "Setting up login credentials for Noba Web Dashboard"

    local username
    while true; do
        read -rp "Username: " username
        if [[ -z "$username" ]]; then
            echo "Username cannot be empty."
        elif [[ ! "$username" =~ ^[a-zA-Z0-9_-]{1,32}$ ]]; then
            echo "Username must be 1–32 characters: letters, digits, _ or - only."
        else
            break
        fi
    done

    local password password2
    while true; do
        read -rs -p "Password: " password
        echo
        if [[ ${#password} -lt 12 ]]; then
            echo "Password must be at least 12 characters."
            continue
        fi
        read -rs -p "Confirm password: " password2
        echo
        if [[ "$password" != "$password2" ]]; then
            echo "Passwords do not match. Try again."
            continue
        fi
        break
    done

    local auth_dir="$HOME/.config/noba-web"
    mkdir -p "$auth_dir"

    local hash
    hash=$(hash_password "$password")

    local tmp="$auth_dir/auth.conf.tmp"
    touch "$tmp"
    chmod 600 "$tmp"
    echo "$username:$hash:admin" > "$tmp"
    mv "$tmp" "$auth_dir/auth.conf"

    log_success "Credentials saved to $auth_dir/auth.conf  (PBKDF2-SHA256, 200k rounds)"
    create_default_yaml "$yaml_file"
}

# ── Default YAML config (if missing) ─────────────────────────────────────────
create_default_yaml() {
    local yaml_file="$1"

    if [[ -f "$yaml_file" ]]; then
        return 0
    fi

    log_info "Creating default config at $yaml_file"
    mkdir -p "$(dirname "$yaml_file")"

    cat > "$yaml_file" <<'EOF'
# Noba Automation Suite — configuration
# Edit this file to match your environment.
email: "you@example.com"

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

checksum:
  default_algo: "sha256"

images2pdf:
  default_paper_size: "A4"
  default_orientation: "portrait"
  default_quality: 92

logs:
  dir: "$HOME/.local/share/noba"
  log_rotation:
    days: 30

update:
  repo_dir: "$HOME/.local/libexec/noba"
  remote: "origin"
  branch: "main"

motd:
  quote_file: "$HOME/.config/quotes.txt"
  show_updates: true
  show_backup: true

services:
  monitor:
    - sshd
    - docker
    - NetworkManager
  notify: true

cron:
  scripts:
    - backup-to-nas.sh
    - disk-sentinel.sh
    - organize-downloads.sh

cloud:
  remote: "mycloud:backups/$USER"
  rclone_ops: "-v --checksum --progress"

web:
  # Comma-separated list of systemd services to monitor.
  monitoredServices: "sshd, docker, NetworkManager"
  # Comma-separated IPs to ping in the radar panel.
  radarIps: "192.168.1.1, 1.1.1.1, 8.8.8.8"
  # Pi-hole base URL (leave blank to disable).
  piholeUrl: ""
  piholeToken: ""
  # Bookmarks format: "Label|URL|fa-icon-name" separated by commas.
  bookmarksStr: ""

# Notifications (optional)
notifications:
  # email:
  #   enabled: false
  #   smtp_server: "smtp.gmail.com:587"
  #   username: "you@gmail.com"
  #   password: "your-app-password"
  #   from: "you@gmail.com"
  #   to: "admin@example.com"
  #   starttls: true
  # telegram:
  #   enabled: false
  #   bot_token: "123456:ABC-DEF1234"
  #   chat_id: "123456789"
  # discord:
  #   enabled: false
  #   webhook_url: "https://discord.com/api/webhooks/..."
  # slack:
  #   enabled: false
  #   webhook_url: "https://hooks.slack.com/services/..."
EOF

    log_success "Default config created. Edit before first use: $yaml_file"
}

# ── Multi‑user database management ───────────────────────────────────────────
NOBA_USER_DB="${NOBA_USER_DB:-$HOME/.config/noba-web/users.conf}"

init_user_db() {
    if [[ ! -f "$NOBA_USER_DB" ]]; then
        mkdir -p "$(dirname "$NOBA_USER_DB")"
        touch "$NOBA_USER_DB"
        chmod 600 "$NOBA_USER_DB"
    fi
}

_user_exists() {
    awk -F: -v u="$1" '$1==u{found=1} END{exit !found}' "$NOBA_USER_DB" 2>/dev/null
}

add_user() {
    local username="$1"
    local password="$2"
    local role="${3:-viewer}"

    init_user_db

    if _user_exists "$username"; then
        log_error "User '$username' already exists"
        return 1
    fi

    local hash
    hash=$(hash_password "$password")

    {
        cat "$NOBA_USER_DB"
        printf "%s:%s:%s\n" "$username" "$hash" "$role"
    } > "$NOBA_USER_DB.tmp"

    chmod 600 "$NOBA_USER_DB.tmp"
    mv "$NOBA_USER_DB.tmp" "$NOBA_USER_DB"

    log_success "User '$username' added (role: $role)"
}

list_users() {
    if [[ ! -f "$NOBA_USER_DB" ]]; then
        echo "No users found."
        return
    fi
    printf "%-20s %-10s\n" "USERNAME" "ROLE"
    printf "%-20s %-10s\n" "--------" "----"
    awk -F: '{printf "%-20s %-10s\n",$1,$3}' "$NOBA_USER_DB"
}

remove_user() {
    local username="$1"
    init_user_db

    if ! _user_exists "$username"; then
        log_error "User '$username' not found"
        return 1
    fi

    awk -F: -v u="$username" '$1!=u' "$NOBA_USER_DB" > "$NOBA_USER_DB.tmp"

    chmod 600 "$NOBA_USER_DB.tmp"
    mv "$NOBA_USER_DB.tmp" "$NOBA_USER_DB"

    log_success "User '$username' removed"
}

change_password() {
    local username="$1"
    local password="$2"
    init_user_db

    if ! _user_exists "$username"; then
        log_error "User '$username' not found"
        return 1
    fi

    local hash
    hash=$(hash_password "$password")

    awk -F: -v u="$username" -v h="$hash" '
        BEGIN {OFS=FS}
        $1==u {$2=h}
        {print}
    ' "$NOBA_USER_DB" > "$NOBA_USER_DB.tmp"

    chmod 600 "$NOBA_USER_DB.tmp"
    mv "$NOBA_USER_DB.tmp" "$NOBA_USER_DB"

    log_success "Password updated for '$username'"
}

# ── Backup & Restore ──────────────────────────────────────────────────────────
backup_config() {
    local backup_dir="${1:-$HOME/.local/share/noba-backup}"
    mkdir -p "$backup_dir"
    local timestamp=$(date +%Y%m%d-%H%M%S)
    local backup_file="$backup_dir/noba-config-$timestamp.tar.gz"

    local targets=()
    [[ -d "$HOME/.config/noba" ]] && targets+=("noba")
    [[ -d "$HOME/.config/noba-web" ]] && targets+=("noba-web")

    if [[ ${#targets[@]} -eq 0 ]]; then
        log_error "No configuration directories found to backup."
        return 1
    fi

    if tar -czf "$backup_file" -C "$HOME/.config" "${targets[@]}"; then
        log_success "Backup saved to $backup_file"
        echo "$backup_file"
    else
        log_error "Backup creation failed."
        return 1
    fi
}

restore_config() {
    local backup_file="$1"
    if [[ ! -f "$backup_file" ]]; then
        log_error "Backup file not found: $backup_file"
        return 1
    fi
    if tar -xzf "$backup_file" -C "$HOME/.config"; then
        log_success "Restored from $backup_file"
    else
        log_error "Failed to restore from $backup_file."
        return 1
    fi
}

# ── Full help (all options) ───────────────────────────────────────────────────
show_help() {
    cat <<EOF
Usage: noba-web [OPTIONS]
Launch the Nobara Command Center web dashboard (default port: 8080).

Options:
  --host HOST            Bind to a specific host or IP  (default: 0.0.0.0)
  -k, --kill             Stop any running noba-web server and exit
  --restart              Stop any running server, then start a new one
  --status               Show running state (PID, URL, uptime)
  --set-password         Create or update single login credential (legacy)
  --add-user             Add a new user (interactive)
  --list-users           List all users
  --remove-user USER     Remove a user
  --change-password      Change a user's password (interactive)
  --generate-systemd     Print a systemd user-service unit and exit
  --backup [DIR]         Backup configuration to directory (default ~/.local/share/noba-backup)
  --restore FILE         Restore configuration from backup file
  -v, --verbose          Tail the server log after starting  (Ctrl-C to stop)
  --version              Print version information and exit
  --help                 Show this help message and exit

Configuration:
  Runtime config  ~/.config/noba-web.conf   (HOST, LOG_FILE, PID_FILE, …)
  App config      ~/.config/noba/config.yaml
  Credentials     ~/.config/noba-web/users.conf   (multi‑user)
EOF
}
