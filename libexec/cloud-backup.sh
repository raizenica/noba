#!/bin/bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# cloud-backup.sh – Sync local backups to cloud using rclone
# Version: 3.1.0

set -euo pipefail

# ── Test harness compliance ────────────────────────────────────────────────────
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: cloud-backup.sh [OPTIONS]"
    exit 0
fi
if [[ "${1:-}" == "--version" ]]; then
    echo "cloud-backup.sh version 3.1.0"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

# ── Defaults (Scrubbed and genericized) ────────────────────────────────────────
CONFIG_FILE="${CLOUD_CONFIG:-$HOME/.config/rclone-backup.conf}"
LOCAL_BACKUP_DIR="${BACKUP_DEST:-$HOME/backups}"
REMOTE_PATH="${CLOUD_REMOTE:-mycloud:backups/$USER}"
DRY_RUN=false
SHOW_PROGRESS=true
CHECK_STATUS=false
LIST_REMOTES=false
BANDWIDTH=""
TRANSFERS=""
RETRIES=3
VERBOSE=false
EXTRA_EXCLUDES=()
LOG_DIR="${LOG_DIR:-$HOME/.local/share}"
LOG_FILE="$LOG_DIR/cloud-backup.log"
STATE_FILE="$LOG_DIR/cloud-backup.state"
LOCK_FILE="${TMPDIR:-/tmp}/cloud-backup.lock"

# Base rclone flags — safe, explicit list (no eval, no string-splitting)
RCLONE_BASE_FLAGS=(--checksum --fast-list --retries 3)

# ── Load configuration ─────────────────────────────────────────────────────────
if command -v get_config &>/dev/null; then
    REMOTE_PATH="$(get_config ".cloud.remote"      "$REMOTE_PATH")"
    LOCAL_BACKUP_DIR="$(get_config ".backup.dest"  "$LOCAL_BACKUP_DIR")"

    config_log_dir="$(get_config ".logs.dir" "$LOG_DIR")"
    LOG_DIR="${config_log_dir/#\~/$HOME}"

    LOG_FILE="$LOG_DIR/cloud-backup.log"
    STATE_FILE="$LOG_DIR/cloud-backup.state"
    BANDWIDTH="$(get_config  ".cloud.bandwidth"    "$BANDWIDTH")"
    TRANSFERS="$(get_config  ".cloud.transfers"    "$TRANSFERS")"
    RETRIES="$(get_config    ".cloud.retries"      "$RETRIES")"
fi

# Parse legacy config as key=value (safe parsing, never sourced)
if [[ -f "$CONFIG_FILE" ]]; then
    while IFS='=' read -r key val; do
        [[ "$key" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$key" ]] && continue
        key="${key// /}"
        val="${val#\"}"
        val="${val%\"}"
        case "$key" in
            REMOTE_PATH)       REMOTE_PATH="$val"       ;;
            LOCAL_BACKUP_DIR)  LOCAL_BACKUP_DIR="$val"  ;;
            BANDWIDTH)         BANDWIDTH="$val"          ;;
            TRANSFERS)         TRANSFERS="$val"          ;;
            RETRIES)           RETRIES="$val"            ;;
        esac
    done < "$CONFIG_FILE"
fi

# ── Functions ──────────────────────────────────────────────────────────────────
show_version() { echo "cloud-backup.sh version 3.1.0"; exit 0; }

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Sync local backups to a cloud provider using rclone.

Options:
  -n, --dry-run          Show what would be synced without transferring
  -r, --remote PATH      Remote path (default: $REMOTE_PATH)
  -c, --config FILE      Legacy config file (key=value, default: $CONFIG_FILE)
  -s, --status           Print current sync status (used by web dashboard)
  -l, --list-remotes     List configured rclone remotes and exit
      --bandwidth LIMIT  Throttle bandwidth e.g. 10M (passed to --bwlimit)
      --transfers N      Parallel transfer count (default: rclone default)
      --retries N        Retry count (default: $RETRIES)
      --exclude PATTERN  Add an exclude rule (repeatable)
      --no-progress      Suppress rclone progress output (for cron/systemd)
  -h, --help             Show this message
      --version          Show version

Exit codes:
  0  Sync completed successfully
  1  Sync failed or runtime error
  2  Configuration or setup error
EOF
    exit 0
}

# ── File lock (atomic via flock) ──────────────────────────────────────────────
LOCK_FD=""
acquire_lock() {
    exec {LOCK_FD}>"$LOCK_FILE"
    if ! flock -n "$LOCK_FD"; then
        die "Another cloud-backup instance is already running."
    fi
}

cleanup() {
    local exit_code=$?
    if [[ -n "$LOCK_FD" ]]; then
        flock -u "$LOCK_FD" 2>/dev/null || true
    fi
    exit "$exit_code"
}
trap cleanup EXIT INT TERM

# ── Safe state file handling ───────────────────────────────────────────────────
write_state() {
    local status="$1"
    local sync_time="$2"
    local size="$3"

    mkdir -p "$(dirname "$STATE_FILE")"
    printf 'LAST_STATUS=%s\nLAST_SYNC_TIME=%s\nLAST_SIZE=%s\n' \
        "$status" "$sync_time" "$size" > "$STATE_FILE"
}

parse_state() {
    if [[ ! -r "$STATE_FILE" ]]; then
        return 1
    fi

    ST_STATUS="Unknown"
    ST_TIME="Unknown"
    ST_SIZE="Unknown"

    while IFS='=' read -r key val; do
        [[ -z "$key" ]] && continue
        case "$key" in
            LAST_STATUS)    ST_STATUS="$val" ;;
            LAST_SYNC_TIME) ST_TIME="$val"   ;;
            LAST_SIZE)      ST_SIZE="$val"   ;;
        esac
    done < "$STATE_FILE"
}

parse_rclone_size() {
    local json="$1"
    if command -v python3 &>/dev/null; then
        python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('bytes', 0))" "$json" 2>/dev/null || echo 0
    else
        echo "$json" | awk -F'[:,]' '{
            for(i=1;i<=NF;i++) {
                gsub(/[" {}]/,"",$i)
                if ($i=="bytes") { gsub(/[^0-9]/,"",$((i+1))); print $((i+1)); exit }
            }
        }' || echo 0
    fi
}

# ── Argument parsing ───────────────────────────────────────────────────────────
if ! PARSED_ARGS=$(getopt \
        -o nr:c:slh \
        -l dry-run,remote:,config:,status,list-remotes,bandwidth:,transfers:,retries:,exclude:,no-progress,help,version \
        -- "$@" 2>/dev/null); then
    log_error "Invalid argument. Run with --help for usage."
    exit 2
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -n|--dry-run)      DRY_RUN=true;              shift   ;;
        -r|--remote)       REMOTE_PATH="$2";          shift 2 ;;
        -c|--config)       CONFIG_FILE="$2";          shift 2 ;;
        -s|--status)       CHECK_STATUS=true;         shift   ;;
        -l|--list-remotes) LIST_REMOTES=true;         shift   ;;
           --bandwidth)    BANDWIDTH="$2";            shift 2 ;;
           --transfers)    TRANSFERS="$2";            shift 2 ;;
           --retries)      RETRIES="$2";              shift 2 ;;
           --exclude)      EXTRA_EXCLUDES+=("$2");    shift 2 ;;
           --no-progress)  SHOW_PROGRESS=false;       shift   ;;
        -v|--verbose)      VERBOSE=true;              shift   ;;
        -h|--help)         show_help ;;
           --version)      show_version ;;
        --)                shift; break ;;
        *)                 log_error "Unknown argument: $1"; exit 2 ;;
    esac
done

# ── Validate numeric args ──────────────────────────────────────────────────────
if [[ ! "$RETRIES" =~ ^[0-9]+$ ]]; then
    log_error "--retries must be a positive integer."
    exit 2
fi

if [[ -n "$TRANSFERS" && ! "$TRANSFERS" =~ ^[0-9]+$ ]]; then
    log_error "--transfers must be a positive integer."
    exit 2
fi

# ── List remotes mode ──────────────────────────────────────────────────────────
if [[ "$LIST_REMOTES" == true ]]; then
    check_deps rclone
    log_info "Configured rclone remotes:"
    rclone listremotes
    exit 0
fi

# ── Status mode ────────────────────────────────────────────────────────────────
if [[ "$CHECK_STATUS" == true ]]; then
    is_running=false
    if [[ -f "$LOCK_FILE" ]]; then
        pid=$(cat "$LOCK_FILE" 2>/dev/null || true)
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            is_running=true
        fi
    fi

    if [[ "$is_running" == true ]]; then
        echo "Status: Syncing"
    elif parse_state; then
        echo "Status: $ST_STATUS"
        echo "Last sync: $ST_TIME"
        echo "Size: $ST_SIZE"
    else
        echo "Status: No data"
        echo "Last sync: N/A"
        echo "Size: N/A"
    fi
    exit 0
fi

# ── Pre-flight ────────────────────────────────────────────────────────────────
check_deps rclone

if [[ ! -d "$LOCAL_BACKUP_DIR" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY RUN] Source dir does not exist: $LOCAL_BACKUP_DIR — nothing to sync."
        exit 0
    fi
    log_error "Source directory does not exist: $LOCAL_BACKUP_DIR"
    write_state "Failed (no source dir)" "$(date '+%Y-%m-%d %H:%M:%S')" "N/A"
    exit 1
fi

if ! rclone lsd "$REMOTE_PATH" --max-depth 1 >/dev/null 2>&1; then
    if [[ "$DRY_RUN" == false ]]; then
        log_warn "Remote '$REMOTE_PATH' does not appear reachable — attempting sync anyway."
    fi
fi

# ── Logging setup ──────────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"
touch "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

# ── Lock ──────────────────────────────────────────────────────────────────────
if [[ "$DRY_RUN" != true ]]; then
    acquire_lock
fi

# ── Build rclone command ───────────────────────────────────────────────────────
RCLONE_FLAGS=("${RCLONE_BASE_FLAGS[@]}")
RCLONE_FLAGS+=(--retries "$RETRIES")

if [[ -n "$BANDWIDTH" ]]; then
    RCLONE_FLAGS+=(--bwlimit "$BANDWIDTH")
fi

if [[ -n "$TRANSFERS" ]]; then
    RCLONE_FLAGS+=(--transfers "$TRANSFERS")
fi

if [[ "$SHOW_PROGRESS" == true && -t 2 ]]; then
    RCLONE_FLAGS+=(--progress)
fi

if [[ "$VERBOSE" == true ]]; then
    RCLONE_FLAGS+=(-v)
fi

for pat in "${EXTRA_EXCLUDES[@]}"; do
    RCLONE_FLAGS+=(--exclude "$pat")
done

if [[ "$DRY_RUN" == true ]]; then
    RCLONE_FLAGS+=(--dry-run)
fi

CMD=(rclone sync "$LOCAL_BACKUP_DIR" "$REMOTE_PATH" "${RCLONE_FLAGS[@]}")

# ── Main sync ─────────────────────────────────────────────────────────────────
log_info "=========================================="
log_info "  Cloud sync v3.1.0 started: $(date)"
log_info "  Source : $LOCAL_BACKUP_DIR"
log_info "  Remote : $REMOTE_PATH"
log_info "  Dry run: $DRY_RUN"
log_info "=========================================="
log_verbose "Command: ${CMD[*]}"

START_TIME=$SECONDS
SYNC_OK=false

if "${CMD[@]}"; then
    SYNC_OK=true
    log_info "Sync completed successfully."
else
    log_error "rclone sync exited with an error."
fi

DURATION=$(( SECONDS - START_TIME ))

# ── Update state file ─────────────────────────────────────────────────────────
if [[ "$DRY_RUN" != true ]]; then
    now=$(date '+%Y-%m-%d %H:%M:%S')

    if [[ "$SYNC_OK" == true ]]; then
        raw_json=$(rclone size "$REMOTE_PATH" --json 2>/dev/null || echo '{"count":0,"bytes":0}')
        size_bytes=$(parse_rclone_size "$raw_json")
        human_sz=$(human_size "$size_bytes" 2>/dev/null || echo "${size_bytes}B")
        write_state "OK" "$now" "$human_sz"
        log_info "Remote size: $human_sz"
    else
        write_state "Failed" "$now" "Unknown"
    fi
fi

log_info "=========================================="
log_info "  Cloud sync finished: $(date)  (${DURATION}s)"
log_info "=========================================="

if [[ "$SYNC_OK" == true ]]; then
    exit 0
else
    exit 1
fi
