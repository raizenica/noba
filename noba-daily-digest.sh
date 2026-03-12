#!/bin/bash
# noba-daily-digest.sh – Send daily summary email

EMAIL="${EMAIL:-strikerke@gmail.com}"
LOG_DIR="$HOME/.local/share"

digest=$(mktemp)
{
    echo "Daily Digest for $(hostname) – $(date)"
    echo ""
    echo "=== Last Backup ==="
    tail -5 "$LOG_DIR/backup-to-nas.log" 2>/dev/null || echo "No backup log"
    echo ""
    echo "=== Disk Warnings ==="
    tail -5 "$LOG_DIR/disk-sentinel.log" 2>/dev/null | grep -E "WARNING|exceeded" || echo "None"
    echo ""
    echo "=== Downloads Organized Yesterday ==="
    grep "$(date -d 'yesterday' +%Y-%m-%d)" "$LOG_DIR/download-organizer.log" 2>/dev/null || echo "None"
    echo ""
    echo "=== System Updates ==="
    echo "DNF updates: $(dnf check-update -q 2>/dev/null | wc -l)"
    echo "Flatpak updates: $(flatpak remote-ls --updates 2>/dev/null | wc -l)"
} > "$digest"

mail -s "Daily Digest $(date +%Y-%m-%d)" "$EMAIL" < "$digest"
rm "$digest"
