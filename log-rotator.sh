#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"
# log-rotator.sh – Compress logs older than 30 days

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    true
    # Override defaults with config values (script-specific)
    # Example:
    # VAR=$(get_config ".${script%.sh}.var" "$VAR")
fi

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    true
    # Override defaults with config values (script-specific)
    # Example:
    # VAR=$(get_config ".${script%.sh}.var" "$VAR")
fi

LOG_DIR="$HOME/.local/share"
DAYS=30

find "$LOG_DIR" -type f -name "*.log" -mtime +$DAYS -print0 | while IFS= read -r -d '' log; do
    gzip "$log"
    echo "Compressed $log"
done
