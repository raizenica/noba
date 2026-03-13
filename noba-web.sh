#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"
# noba-web.sh – Modern dashboard with instant startup and background updates

set -u
set -o pipefail

PORT="${1:-8080}"
HTML_DIR="/tmp/noba-web"
HTML_FILE="$HTML_DIR/index.html"
PID_FILE="/tmp/noba-web.pid"
LOG_FILE="/tmp/noba-web.log"

mkdir -p "$HTML_DIR" || { echo "Failed to create $HTML_DIR"; exit 1; }

# Stop previous instance
if [ -f "$PID_FILE" ]; then
    old_pid=$(cat "$PID_FILE")
    if kill -0 "$old_pid" 2>/dev/null; then
        echo "Stopping old server (PID $old_pid)..."
        kill "$old_pid" && sleep 1
    fi
    rm -f "$PID_FILE"
fi

# Create a minimal placeholder page (so server has something to serve)
cat > "$HTML_FILE" <<EOF
<!DOCTYPE html>
<html>
<head><title>Loading Nobara Dashboard...</title></head>
<body><h1>Dashboard is loading...</h1></body>
</html>
EOF

# Start the HTTP server in background and detach
cd "$HTML_DIR" || exit 1
nohup python3 -m http.server "$PORT" >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!
disown $SERVER_PID
echo $SERVER_PID > "$PID_FILE"

# Start the background updater (with timeouts for slow commands)
(
    # Helper functions (copied inside for nohup)
    get_dnf_updates()    { timeout 5 dnf check-update -q 2>/dev/null | wc -l; }
    get_flatpak_updates() { timeout 5 flatpak remote-ls --updates 2>/dev/null | wc -l; }
    get_cpu_temp() {
        if command -v sensors &>/dev/null; then
            sensors 2>/dev/null | grep -E "Package id 0|Core" | awk '{print $3}' | sed 's/+//;s/°C//' | sort -nr | head -1
        else
            echo "N/A"
        fi
    }
    get_memory_usage() {
        free -h | awk '/^Mem:/ {printf "%s/%s (%.0f%%)", $3, $2, $3/$2*100}'
    }
    get_uptime() {
        uptime -p | sed 's/up //'
    }
    get_loadavg() {
        uptime | awk -F'load average:' '{print $2}'
    }

    while true; do
        # Generate full page with data
        dnf_updates=$(get_dnf_updates)
        flatpak_updates=$(get_flatpak_updates)
        cpu_temp=$(get_cpu_temp)
        mem_usage=$(get_memory_usage)
        uptime=$(get_uptime)
        loadavg=$(get_loadavg)

        disk_usage=$(df -h | grep '^/dev/' | grep -v snap | grep -v loop)

        backup_log="$HOME/.local/share/backup-to-nas.log"
        if [ -f "$backup_log" ]; then
            last_backup=$(tail -5 "$backup_log" | grep -E "Backup finished|ERROR" | tail -1)
            if echo "$last_backup" | grep -q "ERROR"; then
                backup_status="❌ Failed"
            elif echo "$last_backup" | grep -q "Backup finished"; then
                backup_status="✅ OK"
            else
                backup_status="❓ Unknown"
            fi
            backup_time=$(tail -1 "$backup_log" | cut -d' ' -f1-2)
        else
            backup_status="No log"
            backup_time=""
        fi

        organizer_log="$HOME/.local/share/download-organizer.log"
        if [ -f "$organizer_log" ]; then
            moved_files=$(grep -c "Moved:" "$organizer_log" 2>/dev/null || echo 0)
            last_move=$(grep "Moved:" "$organizer_log" | tail -1 | sed 's/.*Moved: //')
        else
            moved_files=0
            last_move="Never"
        fi

        # Build the HTML
        cat > "$HTML_FILE" <<EOF
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Nobara Dashboard</title>
    <meta http-equiv="refresh" content="60">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        :root {
            --bg: #1a1e24;
            --card: #252b33;
            --text: #e4e7eb;
            --text-muted: #9aa5b5;
            --accent: #3b82f6;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: var(--bg);
            color: var(--text);
            font-family: 'Inter', system-ui, sans-serif;
            padding: 2rem;
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 {
            font-size: 2rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        h1 i { color: var(--accent); }
        .timestamp {
            color: var(--text-muted);
            font-size: 0.9rem;
            margin-bottom: 2rem;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 1.5rem;
        }
        .card {
            background: var(--card);
            border-radius: 1rem;
            padding: 1.5rem;
            box-shadow: 0 10px 25px rgba(0,0,0,0.3);
            transition: transform 0.2s;
        }
        .card:hover { transform: translateY(-4px); }
        .card-header {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 1.25rem;
            color: var(--accent);
            border-bottom: 1px solid #3a4452;
            padding-bottom: 0.75rem;
        }
        .card-header i { font-size: 1.5rem; }
        .stat-row {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            padding: 0.5rem 0;
            border-bottom: 1px solid #2e3843;
        }
        .stat-label { color: var(--text-muted); font-size: 0.95rem; }
        .stat-value { font-weight: 600; font-size: 1.1rem; }
        .disk-item {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.5rem 0;
        }
        .disk-bar {
            flex: 1;
            height: 0.5rem;
            background: #2e3843;
            border-radius: 1rem;
            overflow: hidden;
        }
        .disk-bar-fill { height: 100%; border-radius: 1rem; }
        .disk-percent {
            font-weight: 600;
            min-width: 3rem;
            text-align: right;
        }
        .success { color: var(--success); }
        .warning { color: var(--warning); }
        .danger { color: var(--danger); }
        pre {
            background: #1a1e24;
            padding: 0.75rem;
            border-radius: 0.5rem;
            overflow-x: auto;
            font-size: 0.9rem;
            margin-top: 0.5rem;
        }
        .footer {
            margin-top: 2rem;
            text-align: center;
            color: var(--text-muted);
            font-size: 0.9rem;
        }
    </style>
</head>
<body>
<div class="container">
    <h1><i class="fas fa-chart-line"></i> Nobara System Dashboard</h1>
    <div class="timestamp"><i class="far fa-clock"></i> Last updated: $(date)</div>

    <div class="grid">
        <div class="card">
            <div class="card-header"><i class="fas fa-microchip"></i> System Health</div>
            <div class="stat-row"><span class="stat-label">Uptime</span><span class="stat-value">$uptime</span></div>
            <div class="stat-row"><span class="stat-label">Load Average</span><span class="stat-value">$loadavg</span></div>
            <div class="stat-row"><span class="stat-label">Memory</span><span class="stat-value">$mem_usage</span></div>
            <div class="stat-row"><span class="stat-label">CPU Temp</span>
                <span class="stat-value $(awk -v t="$cpu_temp" 't>80 {print "danger"} t>60 {print "warning"}')">${cpu_temp}°C</span>
            </div>
        </div>

        <div class="card">
            <div class="card-header"><i class="fas fa-database"></i> Backup</div>
            <div class="stat-row"><span class="stat-label">Last backup</span>
                <span class="stat-value $( [ "$backup_status" = "✅ OK" ] && echo "success" )">$backup_status</span>
            </div>
            <div class="stat-row"><span class="stat-label">Time</span><span class="stat-value">$backup_time</span></div>
            <pre>$(tail -3 "$backup_log" 2>/dev/null || echo "No log")</pre>
        </div>

        <div class="card">
            <div class="card-header"><i class="fas fa-sync-alt"></i> Updates</div>
            <div class="stat-row"><span class="stat-label">DNF</span>
                <span class="stat-value $( [ "$dnf_updates" -gt 0 ] && echo "warning" )">$dnf_updates available</span>
            </div>
            <div class="stat-row"><span class="stat-label">Flatpak</span>
                <span class="stat-value $( [ "$flatpak_updates" -gt 0 ] && echo "warning" )">$flatpak_updates available</span>
            </div>
            <div class="stat-row"><span class="stat-label">Total</span>
                <span class="stat-value">$((dnf_updates + flatpak_updates)) pending</span>
            </div>
        </div>

        <div class="card" style="grid-column: span 2;">
            <div class="card-header"><i class="fas fa-hdd"></i> Disk Usage</div>
            $(echo "$disk_usage" | while read -r line; do
                if [ -n "$line" ]; then
                    percent=$(echo "$line" | awk '{print $5}' | sed 's/%//')
                    mount=$(echo "$line" | awk '{print $6}')
                    if [ "$percent" -ge 90 ]; then bar_class="danger"
                    elif [ "$percent" -ge 75 ]; then bar_class="warning"
                    else bar_class="success"
                    fi
                    echo '<div class="disk-item">'
                    echo "  <span style=\"min-width:80px;\">${mount}</span>"
                    echo '  <div class="disk-bar"><div class="disk-bar-fill" style="width:'"$percent"'; background: var(--'"$bar_class"');"></div></div>'
                    echo "  <span class=\"disk-percent\">${percent}%</span>"
                    echo '</div>'
                fi
            done)
        </div>

        <div class="card">
            <div class="card-header"><i class="fas fa-download"></i> Download Organizer</div>
            <div class="stat-row"><span class="stat-label">Files moved</span><span class="stat-value">$moved_files</span></div>
            <div class="stat-row"><span class="stat-label">Last move</span><span class="stat-value">$(echo "$last_move" | cut -c1-50)…</span></div>
            <pre>$(tail -3 "$organizer_log" 2>/dev/null || echo "No log")</pre>
        </div>

        <div class="card">
            <div class="card-header"><i class="fas fa-exclamation-triangle"></i> Recent Alerts</div>
            <pre>$(grep -E "WARNING|ERROR" "$HOME/.local/share/disk-sentinel.log" 2>/dev/null | tail -5 || echo "No recent alerts")</pre>
        </div>
    </div>

    <div class="footer">
        <i class="fas fa-sync-alt"></i> Auto‑refreshes every minute • noba-web.sh
    </div>
</div>
</body>
</html>
EOF
        echo "Page updated at $(date)" >> "$LOG_FILE"
        sleep 60
    done
) >> "$LOG_FILE" 2>&1 &
UPDATER_PID=$!
disown $UPDATER_PID

echo "✅ Server started on http://localhost:$PORT (PID $SERVER_PID)"
echo "Dashboard is live. Use 'kill $SERVER_PID' to stop."
exit 0
