#!/bin/bash
# log-rotator.sh – Compress logs older than 30 days

LOG_DIR="$HOME/.local/share"
DAYS=30

find "$LOG_DIR" -type f -name "*.log" -mtime +$DAYS -print0 | while IFS= read -r -d '' log; do
    gzip "$log"
    echo "Compressed $log"
done
