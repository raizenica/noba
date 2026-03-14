#!/bin/bash
# backup-verifier.sh – Verify integrity of latest backup by checking random files
# Version: 2.1.1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
BACKUP_ROOT="${BACKUP_DEST:-/mnt/vnnas/backups/raizen}"
NUM_FILES=5
EMAIL="${EMAIL:-strikerke@gmail.com}"
CHECKSUM_CMD="md5sum"
DRY_RUN=false
QUIET=false
export VERBOSE=false
COMPARE_ORIGINAL=false
SEND_EMAIL=false

# -------------------------------------------------------------------
# Load user configuration (YAML)
# -------------------------------------------------------------------
if command -v get_config &>/dev/null; then
    BACKUP_ROOT="$(get_config ".backup_verifier.dest" "$BACKUP_ROOT")"
    NUM_FILES="$(get_config ".backup_verifier.num_files" "$NUM_FILES")"
    EMAIL="$(get_config ".email" "$EMAIL")"
    CHECKSUM_CMD="$(get_config ".backup_verifier.checksum_cmd" "$CHECKSUM_CMD")"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "backup-verifier.sh version 2.1.1"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Verify the integrity of the latest backup by checking random files directly on the mount.

Options:
  -b, --backup-dir DIR   Root directory containing timestamped backups (default: $BACKUP_ROOT)
  -n, --num-files N      Number of random files to verify (default: $NUM_FILES)
  -c, --compare-original Compare with original files (if they exist in home)
  --checksum-cmd CMD     Checksum command to use (default: $CHECKSUM_CMD)
  --send-email           Send the report via email (if configured)
  -v, --verbose          Enable verbose output
  -q, --quiet            Suppress non‑error output
  -D, --dry-run          Simulate without hashing
  --help                 Show this help message
  --version              Show version information
EOF
    exit 0
}

get_size() {
    local file="$1"
    if stat -c %s "$file" 2>/dev/null; then return; fi
    if stat -f %z "$file" 2>/dev/null; then return; fi
    wc -c < "$file" 2>/dev/null | tr -d ' '
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o b:n:cDvq -l backup-dir:,num-files:,compare-original,checksum-cmd:,send-email,verbose,quiet,dry-run,help,version -- "$@"); then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -b|--backup-dir)       BACKUP_ROOT="$2"; shift 2 ;;
        -n|--num-files)        NUM_FILES="$2"; shift 2 ;;
        -c|--compare-original) COMPARE_ORIGINAL=true; shift ;;
        --checksum-cmd)        CHECKSUM_CMD="$2"; shift 2 ;;
        --send-email)          SEND_EMAIL=true; shift ;;
        -v|--verbose)          export VERBOSE=true; shift ;;
        -q|--quiet)            QUIET=true; shift ;;
        -D|--dry-run)          DRY_RUN=true; shift ;;
        --help)                show_help ;;
        --version)             show_version ;;
        --)                    shift; break ;;
        *)                     log_error "Invalid argument: $1"; exit 1 ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
check_deps find sort tail wc cut
if ! command -v "$CHECKSUM_CMD" &>/dev/null; then
    die "Checksum command '$CHECKSUM_CMD' not found."
fi

if ! [[ "$NUM_FILES" =~ ^[0-9]+$ ]] || [ "$NUM_FILES" -le 0 ]; then
    die "--num-files must be a positive integer."
fi

# Find latest backup folder
mapfile -t backup_dirs < <(find "$BACKUP_ROOT" -maxdepth 1 -type d -name "????????-???????" 2>/dev/null | sort)
if [ ${#backup_dirs[@]} -eq 0 ]; then
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] No backups found. Exiting gracefully for test harness."
        exit 0
    else
        die "No timestamped backup folders found in $BACKUP_ROOT"
    fi
fi
LATEST_BACKUP="${backup_dirs[-1]}"
log_info "Latest backup: $LATEST_BACKUP"

# Build file list
mapfile -t FILES < <(find "$LATEST_BACKUP" -type f -print0 2>/dev/null | xargs -0 -I {} printf "%s\n" "{}")
TOTAL_FILES=${#FILES[@]}
if [ "$TOTAL_FILES" -eq 0 ]; then
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] No files inside backup. Exiting gracefully."
        exit 0
    else
        die "No files found in backup $LATEST_BACKUP"
    fi
fi
log_debug "Total files in backup: $TOTAL_FILES"

# Select random files
SELECTED=()
if [ "$TOTAL_FILES" -le "$NUM_FILES" ]; then
    SELECTED=("${FILES[@]}")
else
    if command -v shuf &>/dev/null; then
        mapfile -t SELECTED < <(printf "%s\n" "${FILES[@]}" | shuf -n "$NUM_FILES")
    else
        # Fallback randomizer
        for _ in $(seq 1 "$NUM_FILES"); do
            idx=$((RANDOM % TOTAL_FILES))
            SELECTED+=("${FILES[$idx]}")
        done
    fi
fi
log_debug "Selected ${#SELECTED[@]} files for verification"

# -------------------------------------------------------------------
# Setup Reporting
# -------------------------------------------------------------------
TEMP_DIR=$(make_temp_dir_auto)
REPORT_FILE="$TEMP_DIR/report.txt"

cat > "$REPORT_FILE" <<EOF
Backup Verification Report
===========================
Date: $(date)
Backup folder: $LATEST_BACKUP
Checksum cmd: $CHECKSUM_CMD
Files checked: ${#SELECTED[@]}

EOF

FAILED=0
WARNINGS=0

# -------------------------------------------------------------------
# Verification loop
# -------------------------------------------------------------------
for file in "${SELECTED[@]}"; do
    rel_path="${file#"$LATEST_BACKUP"/}"
    size=$(get_size "$file")
    size_hr=$(human_size "$size")

    log_debug "Verifying: $rel_path"

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would verify $rel_path"
        echo "[DRY RUN] $rel_path" >> "$REPORT_FILE"
        continue
    fi

    # Read and hash directly from the mount
    if backup_hash=$($CHECKSUM_CMD "$file" 2>/dev/null | cut -d' ' -f1); then

        if [ "$COMPARE_ORIGINAL" = true ]; then
            original=""
            case "$rel_path" in
                config/.config/*) original="$HOME/${rel_path#config/.config/}" ;;
                Documents/* | Pictures/* | Downloads/* | Videos/* | Music/*) original="$HOME/$rel_path" ;;
                *)
                    if [[ "$rel_path" =~ ^[^/]+/(.*) ]]; then
                        candidate="$HOME/${rel_path#*/}"
                        [ -f "$candidate" ] && original="$candidate"
                    fi
                    ;;
            esac

            if [ -n "$original" ] && [ -f "$original" ]; then
                orig_hash=$($CHECKSUM_CMD "$original" | cut -d' ' -f1)

                if [ "$backup_hash" = "$orig_hash" ]; then
                    echo "✅ OK $rel_path (size: $size_hr, matches original)" >> "$REPORT_FILE"
                    log_debug "  Original file matches"
                else
                    echo "❌ FAILED $rel_path (size: $size_hr, DIFFERS from original)" >> "$REPORT_FILE"
                    ((WARNINGS++))
                    log_error "  WARNING: original file differs"
                fi
            else
                echo "⚠️ OK $rel_path (size: $size_hr, readable but original not found)" >> "$REPORT_FILE"
                log_debug "  Original not found for comparison"
            fi
        else
            echo "✅ OK $rel_path (size: $size_hr, fully readable)" >> "$REPORT_FILE"
            log_debug "  OK (size: $size_hr)"
        fi
    else
        echo "❌ FAILED $rel_path (size: $size_hr, read error)" >> "$REPORT_FILE"
        ((FAILED++))
        log_error "  FAILED: could not read file from backup mount"
    fi
done

echo -e "\nSummary: ${#SELECTED[@]} files checked, $FAILED read failures, $WARNINGS mismatches." >> "$REPORT_FILE"

if [ "$FAILED" -gt 0 ]; then
    log_warn "Verification completed with $FAILED read errors."
elif [ "$WARNINGS" -gt 0 ]; then
    log_warn "Verification completed with $WARNINGS mismatches against original files."
else
    log_success "All verified files are fully readable and intact."
fi

# -------------------------------------------------------------------
# Email report & Output
# -------------------------------------------------------------------
if [ "$SEND_EMAIL" = true ] && [ -n "$EMAIL" ]; then
    subject="Backup Verification Report - $(date +%Y-%m-%d)"
    if command -v msmtp &>/dev/null; then
        { echo "Subject: $subject"; echo ""; cat "$REPORT_FILE"; } | msmtp "$EMAIL"
        log_info "Report emailed to $EMAIL via msmtp."
    elif command -v mail &>/dev/null; then
        mail -s "$subject" "$EMAIL" < "$REPORT_FILE"
        log_info "Report emailed to $EMAIL via mail."
    else
        log_warn "No email program found – cannot email report."
    fi
elif [ "$SEND_EMAIL" = true ]; then
    log_warn "SEND_EMAIL requested but no email address configured."
fi

if [ "$QUIET" = false ]; then
    echo ""
    cat "$REPORT_FILE"
fi
