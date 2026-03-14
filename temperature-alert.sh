#!/bin/bash
# temperature-alert.sh - Monitors CPU/GPU temp and triggers KDE notifications
# Version: 2.2.2

# Thresholds (in Celsius)
WARN_TEMP=85
CRIT_TEMP=95

# 1. Safely get CPU Temp (Fixed greedy regex grabbing the 100C threshold)
CPU_TEMP=$(sensors 2>/dev/null | awk '/(Tctl|Package id 0|Core 0|temp1)/ {print $0; exit}' | grep -oE '\+[0-9.]+' | head -n 1 | tr -d '+' | cut -d. -f1)

if [ -z "$CPU_TEMP" ]; then
    # Fallback to sysfs if sensors fails
    if [ -f /sys/class/thermal/thermal_zone0/temp ]; then
        CPU_TEMP=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null)
        CPU_TEMP=$((CPU_TEMP / 1000))
    fi
fi

# 2. Safely get GPU Temp
GPU_TEMP=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader 2>/dev/null || echo "")

check_and_notify() {
    local device="$1"
    local temp="$2"

    if [ -z "$temp" ]; then return 0; fi

    if [ "$temp" -ge "$CRIT_TEMP" ]; then
        notify-send -u critical -i "dialog-error" "CRITICAL TEMPERATURE" "$device is at ${temp}°C! Thermal throttling likely."
        echo "CRITICAL: $device at ${temp}C"
    elif [ "$temp" -ge "$WARN_TEMP" ]; then
        notify-send -u normal -i "dialog-warning" "High Temperature Alert" "$device is running hot at ${temp}°C."
        echo "WARNING: $device at ${temp}C"
    else
        echo "OK: $device at ${temp}C"
    fi
}

check_and_notify "CPU (i7-10870H)" "$CPU_TEMP"
check_and_notify "GPU (RTX 3080)" "$GPU_TEMP"
