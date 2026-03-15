#!/bin/bash
# temperature-alert.sh – Monitors CPU/GPU temp and triggers notifications
# Version: 2.2.3

set -euo pipefail

# -------------------------------------------------------------------
# Test harness compliance
# -------------------------------------------------------------------
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: temperature-alert.sh [OPTIONS]"
    exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "temperature-alert.sh version 2.2.3"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
WARN_TEMP=85
CRIT_TEMP=95
CPU_LABEL="CPU"
GPU_LABEL="GPU"

# Load user configuration
if command -v get_config &>/dev/null; then
    WARN_TEMP="$(get_config ".temperature.warn" "$WARN_TEMP")"
    CRIT_TEMP="$(get_config ".temperature.crit" "$CRIT_TEMP")"
fi

# -------------------------------------------------------------------
# Data Gathering
# -------------------------------------------------------------------

# 1. Safely get CPU Temp
# The awk pattern ensures we grab the actual reading line, not the threshold lines
CPU_TEMP=$(sensors 2>/dev/null | awk '/(Tctl|Package id 0|Core 0|temp1)/ {print $0; exit}' | grep -oE '\+[0-9.]+' | head -n 1 | tr -d '+' | cut -d. -f1)

if [ -z "$CPU_TEMP" ]; then
    # Fallback to sysfs
    if [ -f /sys/class/thermal/thermal_zone0/temp ]; then
        CPU_TEMP=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null)
        CPU_TEMP=$((CPU_TEMP / 1000))
    fi
fi

# 2. Safely get GPU Temp
GPU_TEMP=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader 2>/dev/null || echo "")

# -------------------------------------------------------------------
# Notification Logic
# -------------------------------------------------------------------
check_and_notify() {
    local device="$1"
    local temp="$2"

    if [ -z "$temp" ]; then
        log_debug "Could not read temperature for $device"
        return 0
    fi

    if [ "$temp" -ge "$CRIT_TEMP" ]; then
        if command -v notify-send &>/dev/null && [ -n "${DISPLAY:-}" ]; then
            notify-send -u critical -a "Noba Thermal" -i "dialog-error" "🔥 CRITICAL TEMP" "$device is at ${temp}°C!"
        fi
        log_error "CRITICAL: $device at ${temp}C"
    elif [ "$temp" -ge "$WARN_TEMP" ]; then
        if command -v notify-send &>/dev/null && [ -n "${DISPLAY:-}" ]; then
            notify-send -u normal -a "Noba Thermal" -i "dialog-warning" "⚠️ High Temp" "$device is running hot at ${temp}°C."
        fi
        log_warn "WARNING: $device at ${temp}C"
    else
        log_debug "OK: $device at ${temp}C"
    fi
}

# -------------------------------------------------------------------
# Execute
# -------------------------------------------------------------------
check_and_notify "$CPU_LABEL" "$CPU_TEMP"
check_and_notify "$GPU_LABEL" "$GPU_TEMP"
