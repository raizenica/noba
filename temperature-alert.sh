#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"
# temperature-alert.sh – Alert if CPU temp exceeds threshold

THRESHOLD=85
while true; do
    if command -v sensors &>/dev/null; then
        temp=$(sensors | grep -E "Package id 0|Core" | awk '{print $3}' | sed 's/+//;s/°C//' | sort -nr | head -1)
        if [ -n "$temp" ] && [ "${temp%.*}" -ge "$THRESHOLD" ]; then
            notify-send -u critical "CPU Overheat" "${temp}°C exceeded threshold"
        fi
    fi
    sleep 60
done
