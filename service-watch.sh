#!/bin/bash
# service-watch.sh – Check and restart failed services

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"

# Default services to monitor (can be overridden in config)
SERVICES=("sshd" "docker" "NetworkManager")

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    true
    # Read services array from config if present
    yaml_services=()
    while IFS= read -r line; do
        [ -n "$line" ] && yaml_services+=("$line")
    done < <(get_config_array '.services.monitor')
    if [ ${#yaml_services[@]} -gt 0 ]; then
        SERVICES=("${yaml_services[@]}")
    fi
fi

for svc in "${SERVICES[@]}"; do
    if systemctl is-failed "$svc" &>/dev/null; then
        log_warn "Service $svc is failed, restarting..."
        echo "$svc is failed, restarting..." | systemd-cat -t service-watch
        sudo systemctl restart "$svc"
        if command -v notify-send &>/dev/null; then
            notify-send -u critical "Service restarted" "$svc was down and restarted"
        fi
    fi
done

exit 0
