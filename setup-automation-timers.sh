#!/bin/bash
# setup-automation-timers.sh – Create systemd user timer units for automation scripts

set -euo pipefail

# Configuration
USER_UNIT_DIR="${HOME}/.config/systemd/user"
SCRIPTS_DIR="${HOME}/.local/bin"

# List of timer-service pairs with descriptions and schedules
declare -A TIMERS=(
    [disk-sentinel]="Daily disk sentinel check;OnCalendar=daily"
    [system-report]="Weekly system report;OnCalendar=weekly"
    [cloud-backup]="Daily cloud backup;OnCalendar=daily"
    [log-rotator]="Weekly log rotation;OnCalendar=weekly"
    [service-watch]="Service watch every 15 minutes;OnCalendar=*:0/15"
    [temperature-alert]="Temperature alert every 5 minutes;OnCalendar=*:0/5"
)

# Create unit directory if missing
mkdir -p "$USER_UNIT_DIR"

# Function to create a .timer file
create_timer() {
    local name="$1"
    local description="$2"
    local schedule="$3"
    local timer_file="${USER_UNIT_DIR}/${name}.timer"

    if [ -f "$timer_file" ]; then
        echo "Timer $timer_file already exists. Skipping."
        return
    fi

    cat > "$timer_file" <<EOF
[Unit]
Description=$description

[Timer]
$schedule
Persistent=true

[Install]
WantedBy=timers.target
EOF
    echo "Created $timer_file"
}

# Function to create a .service file
create_service() {
    local name="$1"
    local description="$2"
    local service_file="${USER_UNIT_DIR}/${name}.service"

    if [ -f "$service_file" ]; then
        echo "Service $service_file already exists. Skipping."
        return
    fi

    cat > "$service_file" <<EOF
[Unit]
Description=$description

[Service]
Type=oneshot
ExecStart=${SCRIPTS_DIR}/${name}.sh

[Install]
WantedBy=multi-user.target
EOF
    echo "Created $service_file"
}

# Main loop
for name in "${!TIMERS[@]}"; do
    IFS=';' read -r desc schedule <<< "${TIMERS[$name]}"
    create_timer "$name" "$desc" "$schedule"
    create_service "$name" "$desc"
done

echo
echo "All timer and service files created. To enable and start a timer, run:"
echo "  systemctl --user enable --now <name>.timer"
echo
echo "For example:"
echo "  systemctl --user enable --now disk-sentinel.timer"
echo
echo "To see all timers: systemctl --user list-timers"
