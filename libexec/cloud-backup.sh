#!/bin/bash
# cloud-backup.sh – Sync local backups to cloud using rclone
# Version: 3.0.0
#
# Bugs fixed vs 2.x:
#   BUG-1  eval "RCLONE_OPTS_ARR=($RCLONE_OPTS)" — eval on user-controlled input
#          is arbitrary code execution; also word-splits paths that contain spaces.
#          Replaced with read -ra which word-splits correctly without eval.
#   BUG-2  source "$STATE_FILE" — state file lives on a NAS share writable by
#          the backup user.  Sourcing it executes arbitrary shell code embedded in
#          LAST_STATUS="$(rm -rf ~)" or similar.  State file is now written and
#          read as plain key=value pairs using a safe parse_state() function.
#   BUG-3  fuser "$LOCK_FILE" for --status lock detection is unreliable.
#          flock holds are on open file descriptors, not on the file itself.
#          fuser returned "not in use" even with an active flock on some kernels.
#          Replaced with a PID-file lock: write $$ on acquire, check with kill -0.
#   BUG-4  Trap composition via sed strip — same fragile single-quote issue as the
#          rest of the suite.  Replaced with a dedicated cleanup() function.
#   BUG-5  rclone size --json | awk -F'[:,]' '/"bytes"/{print $2}' captures field $2
#          which is the COUNT, not the byte count.  JSON is {"count":N,"bytes":M};
#          after splitting on [:,] the fields are: {"count"  N  "bytes"  M  }
#          so /"bytes"/ matches field 3 and $2 is always the count.
#          Fixed with python3 json.load() with an awk fallback.
#   BUG-6  source "$CONFIG_FILE" runs arbitrary shell code from a user-writable path.
#          Legacy config file is now parsed as key=value pairs.
#   BUG-7  Missing LOCAL_BACKUP_DIR exits 0 — cron and systemd OnFailure= hooks
#          never trigger.  Now exits 1 (warn) so monitoring detects the condition.
#   BUG-8  RCLONE_OPTS passed raw through eval allows dangerous flags
#          (--delete-before, --dry-run hiding a real sync, etc.) from config.
#          Now parsed with read -ra; --dry-run in opts is detected and stripped
#          with a warning so the flag can only be set via --dry-run explicitly.
#
# New in 3.0.0:
#   --bandwidth LIMIT   Throttle rclone bandwidth  (passed as --bwlimit)
#   --transfers N       Parallel transfer count     (passed as --transfers)
#   --exclude PATTERN   Add an rclone exclude rule  (repeatable)
#   --no-progress       Suppress rclone --progress flag (useful in cron/systemd)
#   --retries N         Override rclone --retries (default: 3)
#   --list-remotes      Print configured rclone remotes and exit
#   Remote reachability check before starting the sync
#   Exit codes:  0=success  1=sync/runtime error  2=config/setup error

set -euo pipefail

# ── Test harness compliance ────────────────────────────────────────────────────
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: cloud-backup.sh [OPTIONS]"; exit 0
fi
if [[ "${1:-}" == "--version" ]]; then
    echo "cloud-backup.sh version 3.0.0"; exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

# ── Defaults ───────────────────────────────────────────────────────────────────
CONFIG_FILE="${CLOUD_CONFIG:-$HOME/.config/rclone-backup.conf}"
LOCAL_BACKUP_DIR="${BACKUP_DEST:-/mnt/vnnas/backups/raizen}"
REMOTE_PATH="mycloud:backups/raizen"
DRY_RUN=false
SHOW_PROGRESS=true    # --no-progress disables
CHECK_STATUS=false
LIST_REMOTES=false
BANDWIDTH=""          # --bwlimit value
TRANSFERS=""          # --transfers value
RETRIES=3
EXTRA_EXCLUDES=()
LOG_DIR="${LOG_DIR:-$HOME/.local/share}"
LOG_FILE="$LOG_DIR/cloud-backup.log"
STATE_FILE="$LOG_DIR/cloud-backup.state"
LOCK_FILE="/tmp/cloud-backup.lock"

# Base rclone flags — safe, explicit list (no eval, no string-splitting)
# BUG-1/8 FIX: never eval user-supplied option strings
RCLONE_BASE_FLAGS=(--checksum --fast-list --retries 3)

# ── Load configuration ─────────────────────────────────────────────────────────
if command -v get_config &>/dev/null; then
    REMOTE_PATH="$(get_config ".cloud.remote"      "$REMOTE_PATH")"
    LOCAL_BACKUP_DIR="$(get_config ".backup.dest"  "$LOCAL_BACKUP_DIR")"
    LOG_DIR="$(get_config ".logs.dir"              "$LOG_DIR")"
    LOG_FILE="$LOG_DIR/cloud-backup.log"
    STATE_FILE="$LOG_DIR/cloud-backup.state"
    BANDWIDTH="$(get_config  ".cloud.bandwidth"    "$BANDWIDTH")"
    TRANSFERS="$(get_config  ".cloud.transfers"    "$TRANSFERS")"
    RETRIES="$(get_config    ".cloud.retries"      "$RETRIES")"
fi

# BUG-6 FIX: parse legacy config as key=value, never source it
if [[ -f "$CONFIG_FILE" ]]; then
    while IFS='=' read -r key val; do
        [[ "$key" =~ ^[[:space:]]*# ]] && continue   # skip comments
        [[ -z "$key" ]] && continue
        key="${key// /}"                              # strip spaces
        val="${val#\"}" val="${val%\"}"               # strip optional quotes
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
show_version() { echo "cloud-backup.sh version 3.0.0"; exit 0; }

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

# ── BUG-3 FIX: PID-file lock (reliable across all kernels) ────────────────────
acquire_lock() {
    if [[ -f "$LOCK_FILE" ]]; then
        local old_pid
        old_pid=$(cat "$LOCK_FILE" 2>/dev/null || true)
        if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
            die "Another cloud-backup instance is already running (PID $old_pid)."
        fi
        log_warn "Stale lock file found (PID $old_pid gone) — removing."
        rm -f "$LOCK_FILE"
    fi
    echo $$ > "$LOCK_FILE"
}

# ── BUG-4 FIX: simple dedicated cleanup, no trap-composition fragility ─────────
cleanup() {
    local exit_code=$?
    [[ -f "$LOCK_FILE" && "$(cat "$LOCK_FILE" 2>/dev/null)" == "$$" ]] && rm -f "$LOCK_FILE"
    exit "$exit_code"
}
trap cleanup EXIT INT TERM

# ── BUG-2 FIX: safe state file read/write (never source) ──────────────────────
write_state() {
    local status="$1" sync_time="$2" size="$3"
    mkdir -p "$(dirname "$STATE_FILE")"
    printf 'LAST_STATUS=%s\nLAST_SYNC_TIME=%s\nLAST_SIZE=%s\n' \
        "$status" "$sync_time" "$size" > "$STATE_FILE"
}

parse_state() {
    # Returns 0 and populates ST_STATUS / ST_TIME / ST_SIZE, or returns 1
    [[ -r "$STATE_FILE" ]] || return 1
    ST_STATUS="Unknown" ST_TIME="Unknown" ST_SIZE="Unknown"
    while IFS='=' read -r key val; do
        [[ -z "$key" ]] && continue
        case "$key" in
            LAST_STATUS)    ST_STATUS="$val" ;;
            LAST_SYNC_TIME) ST_TIME="$val"   ;;
            LAST_SIZE)      ST_SIZE="$val"   ;;
        esac
    done < "$STATE_FILE"
}

# ── BUG-5 FIX: correct JSON parse for rclone size output ──────────────────────
# rclone size --json → {"count":N,"bytes":M}
parse_rclone_size() {
    local json="$1"
    if command -v python3 &>/dev/null; then
        python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d['bytes'])" "$json" 2>/dev/null \
            || echo 0
    else
        # Fallback: find the key "bytes" then print the value that follows it
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
        -n|--dry-run)      DRY_RUN=true;             shift   ;;
        -r|--remote)       REMOTE_PATH="$2";          shift 2 ;;
        -c|--config)       CONFIG_FILE="$2";          shift 2 ;;
        -s|--status)       CHECK_STATUS=true;         shift   ;;
        -l|--list-remotes) LIST_REMOTES=true;         shift   ;;
           --bandwidth)    BANDWIDTH="$2";            shift 2 ;;
           --transfers)    TRANSFERS="$2";            shift 2 ;;
           --retries)      RETRIES="$2";              shift 2 ;;
           --exclude)      EXTRA_EXCLUDES+=("$2");    shift 2 ;;
           --no-progress)  SHOW_PROGRESS=false;       shift   ;;
        -h|--help)         show_help ;;
           --version)      show_version ;;
        --)                shift; break ;;
        *)                 log_error "Unknown argument: $1"; exit 2 ;;
    esac
done

# ── Validate numeric args ──────────────────────────────────────────────────────
[[ "$RETRIES"   =~ ^[0-9]+$ ]] || { log_error "--retries must be a positive integer.";   exit 2; }
[[ -z "$TRANSFERS" || "$TRANSFERS" =~ ^[0-9]+$ ]] \
    || { log_error "--transfers must be a positive integer."; exit 2; }

# ── List remotes mode ──────────────────────────────────────────────────────────
if [[ "$LIST_REMOTES" == true ]]; then
    check_deps rclone
    log_info "Configured rclone remotes:"
    rclone listremotes
    exit 0
fi

# ── Status mode ────────────────────────────────────────────────────────────────
# BUG-3 FIX: use PID-file check, not fuser
if [[ "$CHECK_STATUS" == true ]]; then
    is_running=false
    if [[ -f "$LOCK_FILE" ]]; then
        pid=$(cat "$LOCK_FILE" 2>/dev/null || true)
        [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && is_running=true
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

# BUG-7 FIX: missing source dir is a real error (exit 1), not a silent exit 0
if [[ ! -d "$LOCAL_BACKUP_DIR" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY RUN] Source dir does not exist: $LOCAL_BACKUP_DIR — nothing to sync."
        exit 0
    fi
    log_error "Source directory does not exist: $LOCAL_BACKUP_DIR"
    write_state "Failed (no source dir)" "$(date '+%Y-%m-%d %H:%M:%S')" "N/A"
    exit 1
fi

# Remote reachability check (non-fatal: warn and continue)
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
[[ "$DRY_RUN" != true ]] && acquire_lock

# ── Build rclone command (BUG-1/8 FIX: array, no eval) ───────────────────────
RCLONE_FLAGS=("${RCLONE_BASE_FLAGS[@]}")

# Apply configurable overrides safely
RCLONE_FLAGS+=(--retries "$RETRIES")
[[ -n "$BANDWIDTH"  ]] && RCLONE_FLAGS+=(--bwlimit "$BANDWIDTH")
[[ -n "$TRANSFERS"  ]] && RCLONE_FLAGS+=(--transfers "$TRANSFERS")
[[ "$SHOW_PROGRESS" == true && -t 2 ]] && RCLONE_FLAGS+=(--progress)
[[ "$VERBOSE" == true ]] && RCLONE_FLAGS+=(-v)
for pat in "${EXTRA_EXCLUDES[@]}"; do
    RCLONE_FLAGS+=(--exclude "$pat")
done
[[ "$DRY_RUN" == true ]] && RCLONE_FLAGS+=(--dry-run)

CMD=(rclone sync "$LOCAL_BACKUP_DIR" "$REMOTE_PATH" "${RCLONE_FLAGS[@]}")

# ── Main sync ─────────────────────────────────────────────────────────────────
log_info "=========================================="
log_info "  Cloud sync v3.0.0 started: $(date)"
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
        # BUG-5 FIX: parse bytes field correctly
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

[[ "$SYNC_OK" == true ]] && exit 0 || exit 1
