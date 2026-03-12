#!/bin/bash
# Backup Verifier – test integrity of random files from backups

set -u
set -o pipefail

# Source central config
# shellcheck source=/dev/null
if [ -f "$HOME/.config/automation.conf" ]; then
    source "$HOME/.config/automation.conf"
fi

# Defaults
BACKUP_ROOT="${BACKUP_DEST:-/mnt/vnnas/backups/raizen}"
TEMP_DIR="/tmp/backup-verify"
NUM_FILES=5
EMAIL="${EMAIL:-strikerke@gmail.com}"
DRY_RUN=false
QUIET=false
VERBOSE=false
COMPARE_ORIGINAL=false

# Function to show version
show_version() {
    if command -v git &>/dev/null && git rev-parse --git-dir &>/dev/null; then
        version=$(git describe --tags --always --dirty 2>/dev/null)
        echo "$(basename "$0") version $version"
    else
        echo "$(basename "$0") version unknown (not in git repo)"
    fi
    exit 0
}

# Function to show usage
usage() {
    cat <<EOF
Usage: $0 [options]

Options:
  -b, --backup-dir DIR   Root directory containing timestamped backups (default: $BACKUP_ROOT)
  -n, --num-files N      Number of random files to verify (default: $NUM_FILES)
  -v, --verbose          Print detailed progress
  -q, --quiet            Suppress non‑error output
  -c, --compare-original Compare with original files (if they exist in home)
  --dry-run              Simulate without actually copying
  --help                 Show this help
  --version              Show version information
EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -b|--backup-dir)
            BACKUP_ROOT="$2"
            shift 2
            ;;
        -n|--num-files)
            NUM_FILES="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -q|--quiet)
            QUIET=true
            shift
            ;;
        -c|--compare-original)
            COMPARE_ORIGINAL=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help)
            usage
            ;;
        --version)
            show_version
            ;;
        -*)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
        *)
            echo "Unexpected argument: $1" >&2
            exit 1
            ;;
    esac
done

# Logging function (respects quiet)
log() {
    if [ "$QUIET" = false ]; then
        echo "$@"
    fi
}

# Verbose logging
vlog() {
    if [ "$VERBOSE" = true ] && [ "$QUIET" = false ]; then
        echo "[VERBOSE]" "$@"
    fi
}

# Find the most recent backup folder (by timestamp)
LATEST_BACKUP=$(find "$BACKUP_ROOT" -maxdepth 1 -type d -name "????????-??????" | sort | tail -1)
if [ -z "$LATEST_BACKUP" ]; then
    echo "ERROR: No timestamped backup folders found in $BACKUP_ROOT" >&2
    exit 1
fi
log "Latest backup: $LATEST_BACKUP"

# Collect all files in that backup
mapfile -t FILES < <(find "$LATEST_BACKUP" -type f 2>/dev/null)
TOTAL_FILES=${#FILES[@]}
if [ "$TOTAL_FILES" -eq 0 ]; then
    echo "ERROR: No files found in backup $LATEST_BACKUP" >&2
    exit 1
fi
vlog "Total files in backup: $TOTAL_FILES"

# Randomly select N files
SELECTED=()
if [ "$TOTAL_FILES" -le "$NUM_FILES" ]; then
    SELECTED=("${FILES[@]}")
else
    # Use shuf to pick random indices
    for idx in $(shuf -i 0-$((TOTAL_FILES-1)) -n "$NUM_FILES"); do
        SELECTED+=("${FILES[$idx]}")
    done
fi
vlog "Selected ${#SELECTED[@]} files for verification"

# Prepare report
REPORT="Backup Verification Report
===========================
Date: $(date)
Backup folder: $LATEST_BACKUP
Files checked: ${#SELECTED[@]}

"

mkdir -p "$TEMP_DIR"
FAILED=0
WARNINGS=0

for file in "${SELECTED[@]}"; do
    # Compute relative path to restore same structure
    rel_path="${file#$LATEST_BACKUP/}"
    dest="$TEMP_DIR/$rel_path"
    mkdir -p "$(dirname "$dest")"

    vlog "Verifying: $rel_path"
    if [ "$DRY_RUN" = true ]; then
        log "[DRY RUN] Would verify $rel_path"
        REPORT+="[DRY RUN] $rel_path\n"
        continue
    fi

    # Get file size
    size=$(stat -c %s "$file" 2>/dev/null || echo "unknown")
    size_hr=$(numfmt --to=iec "$size" 2>/dev/null || echo "$size bytes")

    # Copy file to temp
    if cp "$file" "$dest" 2>/dev/null; then
        # Compare checksum
        orig_hash=$(md5sum "$file" | cut -d' ' -f1)
        copy_hash=$(md5sum "$dest" | cut -d' ' -f1)
        if [ "$orig_hash" = "$copy_hash" ]; then
            result="✅ OK"
            REPORT+="$result $rel_path (size: $size_hr, checksum match)\n"
            vlog "  OK (size: $size_hr)"
        else
            result="❌ FAILED (checksum mismatch)"
            REPORT+="$result $rel_path (size: $size_hr)\n"
            ((FAILED++))
            vlog "  FAILED: checksum mismatch"
        fi

        # If compare-original is enabled, try to find the original file
        if [ "$COMPARE_ORIGINAL" = true ]; then
            # Guess original path: if rel_path starts with config/.config/, map to $HOME/.config/...
            # Also handle Documents, Pictures, etc.
            original=""
            case "$rel_path" in
                config/.config/*)
                    original="$HOME/${rel_path#config/.config/}"
                    ;;
                Documents/*)
                    original="$HOME/$rel_path"
                    ;;
                Pictures/*)
                    original="$HOME/$rel_path"
                    ;;
                # Add more mappings as needed
                *)
                    original=""
                    ;;
            esac
            if [ -n "$original" ] && [ -f "$original" ]; then
                orig_hash_original=$(md5sum "$original" | cut -d' ' -f1)
                if [ "$orig_hash" = "$orig_hash_original" ]; then
                    REPORT+="  (matches original on disk)\n"
                    vlog "  Original file matches"
                else
                    REPORT+="  ⚠️  ORIGINAL FILE DIFFERS from backup\n"
                    ((WARNINGS++))
                    vlog "  WARNING: original file differs"
                fi
            elif [ -n "$original" ]; then
                REPORT+="  (original file not found on disk)\n"
                vlog "  Original not found"
            fi
        fi
    else
        result="❌ FAILED (copy failed)"
        REPORT+="$result $rel_path\n"
        ((FAILED++))
        vlog "  FAILED: could not copy file"
    fi
done

# Cleanup temp
rm -rf "$TEMP_DIR"

# Summary
REPORT+="\nSummary: ${#SELECTED[@]} files checked, $FAILED failures, $WARNINGS warnings (if compare-original).\n"

if [ "$FAILED" -gt 0 ]; then
    log "⚠️  Verification completed with $FAILED errors."
elif [ "$WARNINGS" -gt 0 ]; then
    log "⚠️  Verification completed with $WARNINGS warnings (original files differ)."
else
    log "✅ All verified files are intact."
fi

# Email report if not dry run and email configured
if [ "$DRY_RUN" = false ] && [ -n "$EMAIL" ]; then
    echo -e "Subject: Backup Verification Report - $(date +%Y-%m-%d)\n\n$REPORT" | msmtp "$EMAIL"
    log "Report emailed to $EMAIL"
fi

exit $FAILED
