#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"
# undo-organizer.sh – Undo last download organizer run

set -u
set -o pipefail

UNDO_LOG="$HOME/.local/share/download-organizer-undo.log"
DRY_RUN=false
FORCE=false

usage() {
    cat <<EOF
Usage: $0 [options]

Options:
  -d, --dry-run   Show what would be undone without moving
  -f, --force     Skip confirmation prompt
  --help          Show this help
EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -f|--force)
            FORCE=true
            shift
            ;;
        --help)
            usage
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

if [ ! -f "$UNDO_LOG" ] || [ ! -s "$UNDO_LOG" ]; then
    echo "No undo log found at $UNDO_LOG"
    exit 1
fi

# Count entries
count=$(wc -l < "$UNDO_LOG")
echo "This will undo the last download organizer run, moving $count file(s) back."

if [ "$FORCE" = false ]; then
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 0
    fi
fi

# Function to reverse a file line by line (portable)
reverse_lines() {
    if command -v tac &>/dev/null; then
        tac "$1"
    elif command -v tail -r &>/dev/null; then
        tail -r "$1"
    else
        # awk fallback
        awk '{a[NR]=$0} END {for (i=NR;i>=1;i--) print a[i]}' "$1"
    fi
}

# Process undo log in reverse order, handling both old (|) and new (^_) separators
reverse_lines "$UNDO_LOG" | while IFS= read -r line; do
    # Remove trailing carriage return if any
    line=${line%$'\r'}
    # Try new separator (ASCII unit separator \037)
    if [[ "$line" == *$'\037'* ]]; then
        src="${line%%$'\037'*}"
        rest="${line#*$'\037'}"
        dest="${rest%%$'\037'*}"
    # Fallback to old pipe separator
    elif [[ "$line" == *'|'* ]]; then
        src="${line%%|*}"
        dest="${line#*|}"
    else
        echo "WARNING: Malformed undo entry, skipping: $line" >&2
        continue
    fi

    if [ -z "$src" ] || [ -z "$dest" ]; then
        echo "WARNING: Empty src or dest in entry, skipping: $line" >&2
        continue
    fi

    if [ ! -f "$dest" ]; then
        echo "WARNING: $dest not found, skipping" >&2
        continue
    fi

    if [ "$DRY_RUN" = true ]; then
        echo "[DRY RUN] Would restore: $dest → $src"
    else
        mkdir -p "$(dirname "$src")"
        mv "$dest" "$src"
        echo "Restored: $dest → $src"
    fi
done

if [ "$DRY_RUN" = false ]; then
    # Clear undo log
    : > "$UNDO_LOG"
    echo "Undo complete."
fi
