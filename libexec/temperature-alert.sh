#!/usr/bin/env bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# temperature-alert.sh – Monitors CPU/GPU temp and triggers notifications
# Version: 2.4.0

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
    echo "temperature-alert.sh version 2.4.0"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/noba-lib.sh"

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
WARN_TEMP=85
CRIT_TEMP=95
CPU_LABEL="CPU"
GPU_LABEL="GPU"

if command -v get_config &>/dev/null; then
    WARN_TEMP="$(get_config ".temperature.warn" "$WARN_TEMP")"
    CRIT_TEMP="$(get_config ".temperature.crit" "$CRIT_TEMP")"
fi

# -------------------------------------------------------------------
# Data Gathering
# -------------------------------------------------------------------

# 1. Safely get CPU Temp
CPU_TEMP=$(sensors 2>/dev/null | awk '/^(Tctl|Package id 0|Core 0|temp1):/ {print $2}' | tr -d '+°C' | head -n 1 || echo "")
if [[ -n "$CPU_TEMP" ]]; then
    CPU_TEMP=${CPU_TEMP%.*}
else
    if [[ -f /sys/class/thermal/thermal_zone0/temp ]]; then
        CPU_TEMP=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo "0")
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

    if [[ -z "$temp" ]]; then
        log_debug "Could not read temperature for $device"
        return 0
    fi

    if [[ "$temp" -ge "$CRIT_TEMP" ]]; then
        send_alert "error" "🔥 CRITICAL TEMP" "$device is at ${temp}°C!"
        log_error "CRITICAL: $device at ${temp}C"
    elif [[ "$temp" -ge "$WARN_TEMP" ]]; then
        send_alert "warn" "⚠️ High Temp" "$device is running hot at ${temp}°C."
        log_warn "WARNING: $device at ${temp}C"
    else
        log_debug "OK: $device at ${temp}C"
    fi
}

check_and_notify "$CPU_LABEL" "$CPU_TEMP"
check_and_notify "$GPU_LABEL" "$GPU_TEMP"

exit 0
