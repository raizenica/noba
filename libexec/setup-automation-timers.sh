#!/bin/bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# setup-automation-timers.sh – Create systemd user timer units for automation scripts
# Version: 2.4.0

set -euo pipefail

# -------------------------------------------------------------------
# Test harness compliance
# -------------------------------------------------------------------
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: setup-automation-timers.sh [OPTIONS]"
    exit 0
fi
if [[ "${1:-}" == "--version" ]]; then
    echo "setup-automation-timers.sh version 2.4.0"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/noba-lib.sh"

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
USER_UNIT_DIR="${HOME}/.config/systemd/user"
SCRIPTS_DIR="${HOME}/.local/bin"
DRY_RUN=false
FORCE=false

declare -A TIMERS=(
    [backup-to-nas]="Daily NAS Backup|daily|15m"
    [cloud-backup]="Daily Cloud Sync|daily|30m"
    [disk-sentinel]="Daily Disk Monitor|daily|5m"
    [system-report]="Weekly System Report|weekly|10m"
    [noba-daily-digest]="Daily Morning Digest|*-*-* 07:00:00|5m"
    [service-watch]="Hourly Service Watchdog|hourly|2m"
)

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Generate and install systemd user timers for the automation scripts.

Options:
  -f, --force      Overwrite existing unit files
  -d, --dry-run    Show what would be written without making changes
  --help           Show this message
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -f|--force)   FORCE=true; shift ;;
        -d|--dry-run) DRY_RUN=true; shift ;;
        --help|-h)    show_help; exit 0 ;;
        *)            log_error "Unknown option: $1"; exit 1 ;;
    esac
done

create_timer() {
    local name="$1"
    local desc="$2"
    local sched="$3"
    local delay="$4"
    local timer_file="${USER_UNIT_DIR}/${name}.timer"

    if [[ -f "$timer_file" ]] && [[ "$FORCE" == false ]]; then
        log_warn "Timer $name.timer already exists. Use --force to overwrite."
        return
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY RUN] Would create $name.timer"
        return
    fi

    cat > "$timer_file" <<EOF
[Unit]
Description=$desc Timer

[Timer]
OnCalendar=$sched
RandomizedDelaySec=$delay
Persistent=true

[Install]
WantedBy=timers.target
EOF
    log_success "Created $timer_file"
}

create_service() {
    local name="$1"
    local desc="$2"
    local service_file="${USER_UNIT_DIR}/${name}.service"

    if [[ -f "$service_file" ]] && [[ "$FORCE" == false ]]; then
        log_warn "Service $name.service already exists. Use --force to overwrite."
        return
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY RUN] Would create $name.service"
        return
    fi

    cat > "$service_file" <<EOF
[Unit]
Description=$desc Service
After=network-online.target

[Service]
Type=oneshot
Environment="PATH=$PATH"
ExecStart=${SCRIPTS_DIR}/${name}.sh
EOF
    log_success "Created $service_file"
}

# -------------------------------------------------------------------
# Main Execution
# -------------------------------------------------------------------
if [[ "$DRY_RUN" == false ]]; then
    mkdir -p "$USER_UNIT_DIR"
fi

log_info "Setting up systemd timers in $USER_UNIT_DIR..."

for name in "${!TIMERS[@]}"; do
    if [[ ! -x "${SCRIPTS_DIR}/${name}.sh" ]]; then
        log_warn "Target script ${name}.sh not found or not executable in $SCRIPTS_DIR. Skipping..."
        continue
    fi

    IFS='|' read -r desc sched delay <<< "${TIMERS[$name]}"
    create_timer "$name" "$desc" "$sched" "$delay"
    create_service "$name" "$desc"
done

if [[ "$DRY_RUN" == false ]]; then
    log_info "Reloading systemd user daemon..."
    systemctl --user daemon-reload || log_warn "Failed to reload systemd daemon."

    log_info "To enable a timer, run: systemctl --user enable --now <name>.timer"
fi
