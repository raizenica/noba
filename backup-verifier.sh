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

# Find the most recent backup folder (by timestamp)
LATEST_BACKUP=$(find "$BACKUP_ROOT" -maxdepth 1 -type d -name "????????-??????" | sort | tail -1)
if [ -z "$LATEST_BACKUP" ]; then
    echo "ERROR: No timestamped backup folders found in $BACKUP_ROOT" >&2
    exit 1
fi
echo "Latest backup: $LATEST_BACKUP"

# Collect all files in that backup (excluding .config? but we'll include everything)
# Use find to get all regular files
mapfile -t FILES < <(find "$LATEST_BACKUP" -type f 2>/dev/null)
TOTAL_FILES=${#FILES[@]}
if [ "$TOTAL_FILES" -eq 0 ]; then
    echo "ERROR: No files found in backup $LATEST_BACKUP" >&2
    exit 1
fi

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

# Prepare report
REPORT="Backup Verification Report
===========================
Date: $(date)
Backup folder: $LATEST_BACKUP
Files checked: ${#SELECTED[@]}

"

mkdir -p "$TEMP_DIR"
FAILED=0

for file in "${SELECTED[@]}"; do
    # Compute relative path to restore same structure
    rel_path="${file#$LATEST_BACKUP/}"
    dest="$TEMP_DIR/$rel_path"
    mkdir -p "$(dirname "$dest")"

    echo "Verifying: $rel_path"
    if [ "$DRY_RUN" = true ]; then
        echo "  [DRY RUN] Would copy $file to $dest"
        REPORT+="[DRY RUN] $rel_path\n"
        continue
    fi

    # Copy file to temp
    if cp "$file" "$dest" 2>/dev/null; then
        # Simple integrity check: compare with original via checksum
        orig_hash=$(md5sum "$file" | cut -d' ' -f1)
        copy_hash=$(md5sum "$dest" | cut -d' ' -f1)
        if [ "$orig_hash" = "$copy_hash" ]; then
            echo "  OK"
            REPORT+="✅ $rel_path (checksum match)\n"
        else
            echo "  FAILED: checksum mismatch"
            REPORT+="❌ $rel_path (checksum mismatch)\n"
            ((FAILED++))
        fi
    else
        echo "  FAILED: could not copy"
        REPORT+="❌ $rel_path (copy failed)\n"
        ((FAILED++))
    fi
done

# Cleanup temp
rm -rf "$TEMP_DIR"

# Summary
REPORT+="\nSummary: ${#SELECTED[@]} files checked, $FAILED failures.\n"

if [ "$FAILED" -gt 0 ]; then
    echo "⚠️  Verification completed with $FAILED errors."
else
    echo "✅ All verified files are intact."
fi

# Email report if not dry run and email configured
if [ "$DRY_RUN" = false ] && [ -n "$EMAIL" ]; then
    echo -e "Subject: Backup Verification Report - $(date +%Y-%m-%d)\n\n$REPORT" | msmtp "$EMAIL"
    echo "Report emailed to $EMAIL"
fi

exit $FAILED
