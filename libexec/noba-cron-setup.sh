#!/usr/bin/env bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# noba-cron-setup.sh – Interactive setup of cron jobs for automation scripts
# Version: 2.4.0

set -euo pipefail

# -------------------------------------------------------------------
# Test harness compliance
# -------------------------------------------------------------------
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: noba-cron-setup.sh [OPTIONS]"
    exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "noba-cron-setup.sh version 2.4.0"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
# ALIGNED WITH NEW ARCHITECTURE
SCRIPTS_DIR="${HOME}/.local/libexec/noba"
DRY_RUN=false
DEFAULT_SCHEDULE="0 2 * * *"

AUTOMATION_SCRIPTS=(
    "backup-to-nas.sh"
    "cloud-backup.sh"
    "disk-sentinel.sh"
    "organize-downloads.sh"
    "service-watch.sh"
    "system-report.sh"
    "noba-daily-digest.sh"
)

# -------------------------------------------------------------------
# Parse Arguments
# -------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            log_error "Unknown argument: $1"
            exit 1
            ;;
    esac
done

# -------------------------------------------------------------------
# Execution
# -------------------------------------------------------------------
echo "Select a script to schedule:"
select script_name in "${AUTOMATION_SCRIPTS[@]}" "Quit"; do
    if [[ "$script_name" == "Quit" ]]; then
        break
    elif [[ -n "$script_name" ]]; then
        script_path="$SCRIPTS_DIR/$script_name"

        if [[ ! -x "$script_path" ]]; then
            log_warn "Script not found or not executable: $script_path"
            continue
        fi

        read -r -p "Enter cron schedule (default: $DEFAULT_SCHEDULE): " schedule
        schedule=${schedule:-$DEFAULT_SCHEDULE}

        if ! [[ "$schedule" =~ ^([0-9*/,-]+[[:space:]]+){4}[0-9*/,-]+$ ]] && ! [[ "$schedule" =~ ^@[a-z]+$ ]]; then
            log_warn "Invalid cron format. Using default: $DEFAULT_SCHEDULE"
            schedule="$DEFAULT_SCHEDULE"
        fi

        cron_line="$schedule $script_path >/dev/null 2>&1"
        current_crontab=$(crontab -l 2>/dev/null || true)

        if echo "$current_crontab" | grep -Fq "$script_path"; then
            log_warn "A job for $script_name already exists:"
            echo "$current_crontab" | grep "$script_path"

            read -r -p "Overwrite existing job(s) for this script? (y/n): " overwrite
            if [[ "$overwrite" =~ ^[Yy]$ ]]; then
                new_crontab=$(echo "$current_crontab" | grep -vF "$script_path")
                if [[ "$DRY_RUN" == true ]]; then
                    log_info "[DRY RUN] Would replace with: $cron_line"
                else
                    { echo "$new_crontab"; echo "$cron_line"; } | sed '/^$/d' | crontab -
                    log_success "Job updated."
                fi
            fi
        else
            if [[ "$DRY_RUN" == true ]]; then
                log_info "[DRY RUN] Would add: $cron_line"
            else
                { echo "$current_crontab"; echo "$cron_line"; } | sed '/^$/d' | crontab -
                log_success "Job added."
            fi
        fi
        break
    else
        echo "Invalid selection."
    fi
done
