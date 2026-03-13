#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"
# service-watch.sh – Check and restart failed services

SERVICES=("sshd" "docker" "NetworkManager")
for svc in "${SERVICES[@]}"; do
    if systemctl is-failed "$svc" &>/dev/null; then
        echo "$svc is failed, restarting..." | systemd-cat -t service-watch
        sudo systemctl restart "$svc"
        notify-send -u critical "Service restarted" "$svc was down and restarted"
    fi
done
