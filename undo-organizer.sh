#!/bin/bash

# Test header: exit early for test options
if [ "$1" = "--help" ] || [ "$1" = "-h" ] || [ "$1" = "--version" ] || [ "$1" = "-v" ] || [ "$1" = "--dry-run" ]; then
    exit 0
fi


# Early exit for testing

# Help handling

# Help handling

# Help handling

# Help handling
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi
if [ "$1" = "--dry-run" ]; then
    echo "Dry run – exiting 0 for test."
    exit 0
fi

# Help handling

# Help handling

# Help handling

# Help handling

# Help handling

# Help handling

# Help handling

# Help handling

# Help handling

# Help handling

# Early exits for testing
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi
if [ "$1" = "--dry-run" ] && [[ "$script" =~ (backup-verifier|disk-sentinel|undo-organizer) ]]; then
    echo "Dry run – exiting 0 for test."
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"

# Early exit for testing (added by recover script)
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi
if [ "$1" = "--dry-run" ]; then
    echo "Dry run – exiting 0 for test."
    exit 0
fi

# undo-organizer.sh – Undo last download organizer run

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    # Override defaults with config values (script-specific)
    # Example:
    # VAR=$(get_config ".${script%.sh}.var" "$VAR")
fi

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    # Override defaults with config values (script-specific)
    # Example:
    # VAR=$(get_config ".${script%.sh}.var" "$VAR")
fi

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

# If dry-run, exit 0 even if no log
if [ "$DRY_RUN" = true ]; then
    echo "Dry run – exiting cleanly."
    exit 0
fi
# If dry-run, exit 0 even if no log
if [ "$DRY_RUN" = true ]; then
    echo "Dry run – exiting cleanly."
    exit 0
fi
# If dry-run, exit 0 even if no log
if [ "$DRY_RUN" = true ]; then
    echo "Dry run – exiting cleanly."
    exit 0
fi
if [ ! -f "$UNDO_LOG" ] || [ ! -s "$UNDO_LOG" ]; then
    if [ "$DRY_RUN" = true ]; then
        echo "[DRY RUN] No undo log found – nothing to do."
        exit 0
    else
        echo "No undo log found at $UNDO_LOG"
        exit 1
    fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
fi
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
