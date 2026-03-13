#!/bin/bash
# noba-web.sh – Ultimate dashboard with GPU load, Disk I/O, service resource usage,
# and integrated disk‑sentinel, temperature‑alert, system‑report, service‑watch,
# backup‑verifier, and cloud‑backup – all beautifully displayed!

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
START_PORT="${START_PORT:-8080}"
MAX_PORT="${MAX_PORT:-8090}"
HTML_DIR="${HTML_DIR:-/tmp/noba-web}"
SERVER_PID_FILE="${SERVER_PID_FILE:-/tmp/noba-web-server.pid}"
LOG_FILE="${LOG_FILE:-/tmp/noba-web.log}"
KILL_ONLY=false

DEFAULT_SERVICES="backup-to-nas.service organize-downloads.service noba-web.service syncthing.service"

# -------------------------------------------------------------------
# Load user configuration (if any)
# -------------------------------------------------------------------
load_config || true
if [ "$CONFIG_LOADED" = true ]; then
    START_PORT="$(get_config ".web.start_port" "$START_PORT")"
    MAX_PORT="$(get_config ".web.max_port" "$MAX_PORT")"
    SERVICES_LIST=$(get_config_array ".web.service_list" | tr '\n' ',' | sed 's/,$//')
    if [ -n "$SERVICES_LIST" ]; then
        export NOBA_WEB_SERVICES="$SERVICES_LIST"
    else
        export NOBA_WEB_SERVICES="${DEFAULT_SERVICES// /,}"
    fi
else
    export NOBA_WEB_SERVICES="${DEFAULT_SERVICES// /,}"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "noba-web.sh version 3.0 (integrated scripts)"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Launch an interactive web dashboard for Nobara automation.

Options:
  -p, --port PORT   Start searching from PORT (default: $START_PORT)
  -m, --max PORT    Maximum port to try (default: $MAX_PORT)
  -k, --kill        Kill any running noba-web server and exit
  --help            Show this help message
  --version         Show version information
EOF
    exit 0
}

kill_server() {
    if [ -f "$SERVER_PID_FILE" ]; then
        local pid
        pid=$(cat "$SERVER_PID_FILE" 2>/dev/null || true)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            log_info "Stopping old server (PID $pid)..."
            kill "$pid" 2>/dev/null && sleep 1
            if kill -0 "$pid" 2>/dev/null; then
                log_warn "Force killing server..."
                kill -9 "$pid" 2>/dev/null || true
            fi
        fi
        rm -f "$SERVER_PID_FILE"
    fi
}

find_free_port() {
    local start="$1"
    local max="$2"
    local port
    for port in $(seq "$start" "$max"); do
        if ! ss -tuln 2>/dev/null | grep -q ":$port "; then
            echo "$port"
            return 0
        fi
    done
    return 1
}

# -------------------------------------------------------------------
# Parse arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o p:m:k -l port:,max:,kill,help,version -- "$@"); then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -p|--port)    START_PORT="$2"; shift 2 ;;
        -m|--max)     MAX_PORT="$2"; shift 2 ;;
        -k|--kill)    KILL_ONLY=true; shift ;;
        --help)       show_help ;;
        --version)    show_version ;;
        --)           shift; break ;;
        *)            break ;;
    esac
done

if [ "$KILL_ONLY" = true ]; then
    kill_server
    log_info "Server stopped (if any)."
    exit 0
fi

check_deps python3 ss
if ! command -v ss &>/dev/null; then
    log_warn "ss not found – using lsof as fallback."
    check_deps lsof
fi

PORT=$(find_free_port "$START_PORT" "$MAX_PORT")
if [ -z "$PORT" ]; then
    log_error "No free port found between $START_PORT and $MAX_PORT."
    exit 1
fi
log_info "Using port $PORT"

mkdir -p "$HTML_DIR"
rm -f "$HTML_DIR"/*.html "$HTML_DIR"/server.py "$HTML_DIR"/stats.json 2>/dev/null || true

# -------------------------------------------------------------------
# Modernized HTML file (with glassmorphism, smooth animations, Chart.js)
# -------------------------------------------------------------------
cat > "$HTML_DIR/index.html" <<'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Nobara Interactive Dashboard</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        :root {
            --bg-gradient: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            --card-bg: rgba(30, 41, 59, 0.7);
            --card-border: rgba(255, 255, 255, 0.08);
            --text-primary: #f1f5f9;
            --text-secondary: #94a3b8;
            --accent: #3b82f6;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --glass-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            --card-blur: blur(12px);
        }
        body {
            background: var(--bg-gradient);
            color: var(--text-primary);
            font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            min-height: 100vh;
            padding: 2rem;
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
        }
        h1 {
            font-size: 2.5rem;
            font-weight: 600;
            letter-spacing: -0.02em;
            margin-bottom: 0.5rem;
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }
        h1 i { color: var(--accent); font-size: 2rem; }
        .timestamp {
            color: var(--text-secondary);
            margin-bottom: 2.5rem;
            font-size: 0.95rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        .card {
            background: var(--card-bg);
            backdrop-filter: var(--card-blur);
            -webkit-backdrop-filter: var(--card-blur);
            border: 1px solid var(--card-border);
            border-radius: 1.5rem;
            padding: 1.5rem;
            box-shadow: var(--glass-shadow);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        .card:hover {
            transform: translateY(-4px);
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.4);
        }
        .card-header {
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 1.25rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            color: var(--text-primary);
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            padding-bottom: 0.75rem;
        }
        .card-header i { color: var(--accent); width: 1.5rem; }
        .stat-row {
            display: flex;
            justify-content: space-between;
            margin: 0.75rem 0;
            font-size: 0.95rem;
        }
        .stat-label { color: var(--text-secondary); }
        .stat-value { font-weight: 500; color: var(--text-primary); }
        .success { color: var(--success); }
        .warning { color: var(--warning); }
        .danger { color: var(--danger); }

        .disk-item {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            margin: 0.75rem 0;
        }
        .disk-item span:first-child {
            min-width: 80px;
            font-size: 0.9rem;
            color: var(--text-secondary);
        }
        .disk-bar {
            flex: 1;
            height: 0.5rem;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 1rem;
            overflow: hidden;
        }
        .disk-bar-fill {
            height: 100%;
            border-radius: 1rem;
            transition: width 0.3s ease;
        }
        .disk-percent {
            min-width: 3rem;
            text-align: right;
            font-weight: 500;
        }

        pre {
            background: rgba(0, 0, 0, 0.3);
            padding: 0.75rem;
            border-radius: 0.75rem;
            font-size: 0.8rem;
            font-family: 'Fira Code', monospace;
            overflow-x: auto;
            white-space: pre-wrap;
            word-wrap: break-word;
            color: var(--text-secondary);
            border: 1px solid rgba(255, 255, 255, 0.05);
            margin: 1rem 0 0.5rem;
        }

        .button-grid {
            display: flex;
            gap: 0.75rem;
            margin-top: 1rem;
            flex-wrap: wrap;
        }
        .btn {
            padding: 0.6rem 1.2rem;
            border: none;
            border-radius: 2rem;
            background: rgba(255, 255, 255, 0.1);
            color: var(--text-primary);
            font-size: 0.9rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            backdrop-filter: blur(4px);
            border: 1px solid rgba(255, 255, 255, 0.05);
        }
        .btn:hover {
            background: rgba(255, 255, 255, 0.2);
            transform: translateY(-2px);
        }
        .btn-primary {
            background: var(--accent);
            border-color: rgba(59, 130, 246, 0.5);
        }
        .btn-primary:hover { background: #2563eb; }

        .modal {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.6);
            backdrop-filter: blur(8px);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }
        .modal-content {
            background: var(--card-bg);
            backdrop-filter: var(--card-blur);
            border: 1px solid var(--card-border);
            border-radius: 1.5rem;
            padding: 2rem;
            max-width: 600px;
            width: 90%;
            max-height: 80vh;
            overflow-y: auto;
            box-shadow: var(--glass-shadow);
        }
        .modal-header {
            font-size: 1.5rem;
            font-weight: 600;
            margin-bottom: 1rem;
            color: var(--text-primary);
        }

        .footer {
            margin-top: 2rem;
            text-align: center;
            color: var(--text-secondary);
            display: flex;
            justify-content: center;
            gap: 1.5rem;
            align-items: center;
            font-size: 0.9rem;
        }
        .footer .btn {
            background: transparent;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }

        canvas.sparkline {
            width: 100%;
            height: 40px;
            max-height: 40px;
            page-break-inside: avoid;
            break-inside: avoid;
        }

        /* Collapsible */
        .collapsible {
            cursor: pointer;
            user-select: none;
        }
        .collapsible i {
            transition: transform 0.2s;
        }
        .collapsible.open i {
            transform: rotate(90deg);
        }
        .collapsible-content {
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease-out;
        }
        .collapsible-content.open {
            max-height: 500px; /* adjust as needed */
        }

        @media (max-width: 640px) {
            body { padding: 1rem; }
            h1 { font-size: 2rem; }
        }
    </style>
</head>
<body x-data="dashboard()" x-init="init()">
    <h1><i class="fas fa-chart-pie"></i> Nobara Dashboard</h1>
    <div class="timestamp"><i class="far fa-clock"></i> Last updated: <span x-text="timestamp"></span></div>

    <div class="grid">
        <!-- System Health Card -->
        <div class="card">
            <div class="card-header"><i class="fas fa-microchip"></i> System Health</div>
            <div class="stat-row"><span class="stat-label">Uptime</span><span class="stat-value" x-text="uptime"></span></div>
            <div class="stat-row"><span class="stat-label">Load Average</span><span class="stat-value" x-text="loadavg"></span></div>
            <div class="stat-row"><span class="stat-label">Memory</span><span class="stat-value" x-text="memory"></span></div>
            <div class="stat-row"><span class="stat-label">CPU Temp</span><span class="stat-value" :class="tempClass" x-text="cpuTemp"></span></div>
        </div>

        <!-- Battery Card -->
        <div class="card" x-show="battery.present">
            <div class="card-header"><i class="fas fa-battery-three-quarters"></i> Battery</div>
            <div class="stat-row"><span class="stat-label">Status</span><span class="stat-value" x-text="battery.status"></span></div>
            <div class="stat-row"><span class="stat-label">Capacity</span><span class="stat-value" x-text="battery.capacity + '%'"></span></div>
            <div class="stat-row"><span class="stat-label">Health</span><span class="stat-value" x-text="battery.health"></span></div>
            <div class="stat-row" x-show="battery.voltage !== 'N/A'"><span class="stat-label">Voltage</span><span class="stat-value" x-text="battery.voltage"></span></div>
            <div class="stat-row" x-show="battery.power !== 'N/A'"><span class="stat-label">Power</span><span class="stat-value" x-text="battery.power"></span></div>
        </div>

        <!-- GPU Card -->
        <div class="card">
            <div class="card-header"><i class="fas fa-microchip"></i> GPU</div>
            <div class="stat-row"><span class="stat-label">Temperature</span><span class="stat-value" x-text="gpuTemp"></span></div>
            <div class="stat-row"><span class="stat-label">Load</span><span class="stat-value" x-text="gpuLoad"></span></div>
        </div>

        <!-- Backup Card (existing) -->
        <div class="card">
            <div class="card-header"><i class="fas fa-database"></i> Backup</div>
            <div class="stat-row"><span class="stat-label">Last backup</span><span class="stat-value" :class="backupClass" x-text="backupStatus"></span></div>
            <div class="stat-row"><span class="stat-label">Time</span><span class="stat-value" x-text="backupTime"></span></div>
            <pre x-text="backupLog"></pre>
            <div class="button-grid">
                <button class="btn btn-primary" @click="runScript('backup')"><i class="fas fa-play"></i> Run Backup</button>
                <button class="btn" @click="runScript('verify')"><i class="fas fa-check"></i> Verify</button>
            </div>
        </div>

        <!-- Updates Card -->
        <div class="card">
            <div class="card-header"><i class="fas fa-sync-alt"></i> Updates</div>
            <div class="stat-row"><span class="stat-label">DNF</span><span class="stat-value" x-text="dnfUpdates"></span></div>
            <div class="stat-row"><span class="stat-label">Flatpak</span><span class="stat-value" x-text="flatpakUpdates"></span></div>
            <div class="stat-row"><span class="stat-label">Total</span><span class="stat-value" x-text="totalUpdates"></span></div>
        </div>

        <!-- Disk Usage Card -->
        <div class="card" style="grid-column: span 2;">
            <div class="card-header"><i class="fas fa-hdd"></i> Disk Usage</div>
            <template x-for="disk in disks" :key="disk.mount">
                <div class="disk-item">
                    <span x-text="disk.mount"></span>
                    <div class="disk-bar"><div class="disk-bar-fill" :style="'width:'+disk.percent+'%; background: var(--'+disk.barClass+');'"></div></div>
                    <span class="disk-percent" x-text="disk.percent+'%'"></span>
                </div>
            </template>
        </div>

        <!-- Disk I/O Card -->
        <div class="card" style="grid-column: span 2;">
            <div class="card-header"><i class="fas fa-tachometer-alt"></i> Disk I/O</div>
            <template x-for="disk in diskio" :key="disk.name">
                <div class="stat-row"><span class="stat-label" x-text="disk.name"></span><span class="stat-value" x-text="'R:' + disk.read + ' W:' + disk.write"></span></div>
            </template>
            <template x-if="diskio.length === 0"><div class="stat-row"><span class="stat-label">No disk I/O data</span></div></template>
        </div>

        <!-- ZFS Card -->
        <div class="card" x-show="zfs.pools && zfs.pools.length > 0">
            <div class="card-header"><i class="fas fa-database"></i> ZFS Pools</div>
            <template x-for="pool in zfs.pools" :key="pool.name">
                <div class="stat-row"><span class="stat-label" x-text="pool.name"></span><span class="stat-value" :class="{'success': pool.health==='ONLINE','warning': pool.health==='DEGRADED','danger': pool.health==='FAULTED'}" x-text="pool.health"></span></div>
            </template>
        </div>

        <!-- Download Organizer Card -->
        <div class="card">
            <div class="card-header"><i class="fas fa-download"></i> Download Organizer</div>
            <div class="stat-row"><span class="stat-label">Files moved</span><span class="stat-value" x-text="movedFiles"></span></div>
            <div class="stat-row"><span class="stat-label">Last move</span><span class="stat-value" x-text="lastMove"></span></div>
            <pre x-text="organizerLog"></pre>
            <div class="button-grid"><button class="btn btn-primary" @click="runScript('organize')"><i class="fas fa-play"></i> Organize Now</button></div>
        </div>

        <!-- Network Card -->
        <div class="card">
            <div class="card-header"><i class="fas fa-network-wired"></i> Network</div>
            <div class="stat-row"><span class="stat-label">Default IP</span><span class="stat-value" x-text="defaultIp"></span></div>
            <template x-for="iface in interfaces" :key="iface.name">
                <div class="stat-row"><span class="stat-label" x-text="iface.name"></span><span class="stat-value" x-text="'↓' + iface.rx + ' ↑' + iface.tx"></span></div>
            </template>
            <template x-if="interfaces.length === 0"><div class="stat-row"><span class="stat-label">No data</span></div></template>
            <div class="button-grid" style="margin-top:1rem;"><button class="btn" @click="runScript('speedtest')"><i class="fas fa-tachometer-alt"></i> Speed Test</button></div>
        </div>

        <!-- Services Card -->
        <div class="card">
            <div class="card-header"><i class="fas fa-cogs"></i> User Services</div>
            <template x-for="svc in services" :key="svc.name">
                <div class="stat-row"><span class="stat-label" x-text="svc.name.replace('.service','')"></span><span class="stat-value" :class="{'success': svc.status==='active','warning': svc.status==='inactive','danger': svc.status==='failed'}" x-text="svc.status"></span></div>
                <div class="stat-row" style="font-size:0.9rem; margin-top:-0.5rem;" x-show="svc.memory"><span class="stat-label">Memory</span><span class="stat-value" x-text="svc.memory"></span></div>
                <div class="stat-row" style="font-size:0.9rem;" x-show="svc.cpu"><span class="stat-label">CPU Time</span><span class="stat-value" x-text="svc.cpu"></span></div>
            </template>
        </div>

        <!-- Docker Card -->
        <div class="card">
            <div class="card-header"><i class="fab fa-docker"></i> Docker Containers</div>
            <template x-if="dockerContainers.length === 0"><div class="stat-row"><span class="stat-label">No running containers</span></div></template>
            <template x-for="container in dockerContainers" :key="container">
                <div class="stat-row"><span class="stat-label" x-text="container.split('(')[0]"></span><span class="stat-value success" x-text="container.split('(')[1].replace(')','')"></span></div>
            </template>
        </div>

        <!-- ========== NEW INTEGRATED CARDS ========== -->

        <!-- Disk Sentinel with Sparkline -->
        <div class="card">
            <div class="card-header"><i class="fas fa-exclamation-triangle"></i> Disk Sentinel</div>
            <pre x-text="diskSentinel.output"></pre>
            <canvas class="sparkline" x-ref="diskChart"></canvas>
            <div class="button-grid"><button class="btn" @click="runScript('diskcheck')"><i class="fas fa-search"></i> Check Now</button></div>
        </div>

        <!-- Temperature Alerts with Sparkline -->
        <div class="card">
            <div class="card-header"><i class="fas fa-thermometer-half"></i> Temperature Alerts</div>
            <div class="stat-row"><span class="stat-label">Current CPU</span><span class="stat-value" :class="cpuTempClass" x-text="cpuTemp"></span></div>
            <div class="stat-row"><span class="stat-label">Current GPU</span><span class="stat-value" :class="gpuTempClass" x-text="gpuTemp"></span></div>
            <pre x-text="temperatureAlert.output"></pre>
            <canvas class="sparkline" x-ref="tempChart"></canvas>
        </div>

        <!-- System Report (collapsible) -->
        <div class="card" x-data="{ open: false }">
            <div class="card-header collapsible" @click="open = !open">
                <i class="fas fa-chevron-right" :class="{ 'open': open }"></i> System Report
            </div>
            <div class="collapsible-content" :class="{ 'open': open }">
                <pre x-text="systemReport.output"></pre>
            </div>
        </div>

        <!-- Service Watch -->
        <div class="card">
            <div class="card-header"><i class="fas fa-heartbeat"></i> Service Watch</div>
            <template x-for="svc in serviceWatch" :key="svc.name">
                <div class="stat-row">
                    <span class="stat-label" x-text="svc.name"></span>
                    <span class="stat-value" :class="{
                        'success': svc.status === 'running',
                        'warning': svc.status === 'degraded',
                        'danger': svc.status === 'failed'
                    }" x-text="svc.status"></span>
                    <span class="stat-value" x-show="svc.response" x-text="svc.response"></span>
                </div>
            </template>
            <template x-if="serviceWatch.length === 0">
                <div class="stat-row"><span class="stat-label">No monitored services</span></div>
            </template>
        </div>

        <!-- Backup Verifier -->
        <div class="card">
            <div class="card-header"><i class="fas fa-check-circle"></i> Backup Verifier</div>
            <div class="stat-row"><span class="stat-label">Last result</span><span class="stat-value" :class="backupVerifierClass" x-text="backupVerifier.result"></span></div>
            <pre x-text="backupVerifier.output"></pre>
            <div class="button-grid"><button class="btn" @click="runScript('verify')"><i class="fas fa-redo"></i> Verify Now</button></div>
        </div>

        <!-- Cloud Backup -->
        <div class="card">
            <div class="card-header"><i class="fas fa-cloud-upload-alt"></i> Cloud Backup</div>
            <div class="stat-row"><span class="stat-label">Status</span><span class="stat-value" :class="cloudBackupClass" x-text="cloudBackup.status"></span></div>
            <div class="stat-row"><span class="stat-label">Last sync</span><span class="stat-value" x-text="cloudBackup.lastSync"></span></div>
            <div class="stat-row"><span class="stat-label">Size</span><span class="stat-value" x-text="cloudBackup.size"></span></div>
            <pre x-text="cloudBackup.output"></pre>
            <div class="button-grid"><button class="btn" @click="runScript('cloudbackup')"><i class="fas fa-sync"></i> Sync Now</button></div>
        </div>
    </div>

    <!-- Modal for script output -->
    <div x-show="showModal" class="modal" @click.self="showModal=false">
        <div class="modal-content">
            <div class="modal-header" x-text="modalTitle"></div>
            <pre x-text="modalOutput"></pre>
            <div class="button-grid" style="justify-content: flex-end;">
                <button class="btn" @click="showModal=false">Close</button>
            </div>
        </div>
    </div>

    <div class="footer">
        <i class="fas fa-sync-alt fa-spin" x-show="refreshing"></i>
        <span>Auto‑refreshes every minute</span>
        <button class="btn" @click="refreshStats"><i class="fas fa-redo"></i> Refresh Now</button>
    </div>

    <script>
        function dashboard() {
            return {
                // existing properties
                diskChart: null,
                tempChart: null,
                timestamp: '', uptime: '', loadavg: '', memory: '', cpuTemp: '',
                tempClass: '', backupStatus: '', backupClass: '', backupTime: '',
                backupLog: '', dnfUpdates: 0, flatpakUpdates: 0, totalUpdates: 0,
                disks: [], movedFiles: 0, lastMove: '', organizerLog: '',
                diskAlerts: '', showModal: false, modalTitle: '', modalOutput: '',
                runningScript: false, refreshing: false,
                defaultIp: '', interfaces: [], services: [],
                gpuTemp: '', gpuLoad: '', dockerContainers: [],
                battery: {}, zfs: { pools: [] }, diskio: [],

                // new integrated data
                diskSentinel: { output: '' },
                diskSentinelHistory: [],
                temperatureAlert: { output: '' },
                tempHistory: [],
                systemReport: { output: '' },
                serviceWatch: [],
                backupVerifier: { result: '', output: '' },
                cloudBackup: { status: '', lastSync: '', size: '', output: '' },

                // computed classes
                get cpuTempClass() {
                    const t = parseInt(this.cpuTemp) || 0;
                    return t > 80 ? 'danger' : t > 60 ? 'warning' : '';
                },
                get gpuTempClass() {
                    const t = parseInt(this.gpuTemp) || 0;
                    return t > 85 ? 'danger' : t > 70 ? 'warning' : '';
                },
                get backupVerifierClass() {
                    return this.backupVerifier.result.includes('OK') ? 'success' : this.backupVerifier.result.includes('Failed') ? 'danger' : '';
                },
                get cloudBackupClass() {
                    return this.cloudBackup.status === 'OK' ? 'success' : this.cloudBackup.status === 'Syncing' ? 'warning' : 'danger';
                },

                async init() {
                    await this.refreshStats();
                    setInterval(() => this.refreshStats(), 60000);
                },

                async refreshStats() {
                    this.refreshing = true;
                    try {
                        const response = await fetch('/api/stats');
                        if (!response.ok) return;
                        const data = await response.json();
                        // existing updates
                        this.timestamp = data.timestamp;
                        this.uptime = data.uptime;
                        this.loadavg = data.loadavg;
                        this.memory = data.memory;
                        this.cpuTemp = data.cpuTemp;
                        this.backupStatus = data.backupStatus;
                        this.backupClass = data.backupStatus.includes('OK') ? 'success' : data.backupStatus.includes('Failed') ? 'danger' : '';
                        this.backupTime = data.backupTime;
                        this.backupLog = data.backupLog;
                        this.dnfUpdates = data.dnfUpdates;
                        this.flatpakUpdates = data.flatpakUpdates;
                        this.totalUpdates = data.dnfUpdates + data.flatpakUpdates;
                        this.disks = data.disks;
                        this.movedFiles = data.movedFiles;
                        this.lastMove = data.lastMove;
                        this.organizerLog = data.organizerLog;
                        this.diskAlerts = data.diskAlerts;
                        this.defaultIp = data.defaultIp || 'N/A';
                        this.interfaces = data.interfaces || [];
                        this.services = data.services || [];
                        this.gpuTemp = data.gpuTemp || 'N/A';
                        this.gpuLoad = data.gpuLoad || 'N/A';
                        this.dockerContainers = data.dockerContainers || [];
                        this.battery = data.battery || {};
                        this.zfs = data.zfs || { pools: [] };
                        this.diskio = data.diskio || [];

                        // new integrated data
                        this.diskSentinel = data.diskSentinel || { output: '' };
                        this.diskSentinelHistory = data.diskSentinelHistory || [];
                        this.temperatureAlert = data.temperatureAlert || { output: '' };
                        this.tempHistory = data.tempHistory || [];
                        this.systemReport = data.systemReport || { output: '' };
                        this.serviceWatch = data.serviceWatch || [];
                        this.backupVerifier = data.backupVerifier || { result: '', output: '' };
                        this.cloudBackup = data.cloudBackup || { status: '', lastSync: '', size: '', output: '' };

                        // Draw sparklines after data update
                        this.$nextTick(() => this.drawCharts());
                    } catch (e) {
                        console.error('Stats fetch failed', e);
                    } finally {
                        this.refreshing = false;
                    }
                },

                drawCharts() {
                    // Destroy existing charts if they exist
                    if (this.diskChart) this.diskChart.destroy();
                    if (this.tempChart) this.tempChart.destroy();

                    // Disk Sentinel sparkline
                    if (this.$refs.diskChart && this.diskSentinelHistory.length) {
                        this.diskChart = new Chart(this.$refs.diskChart, {
                            type: 'line',
                            data: {
                                labels: this.diskSentinelHistory.map((_, i) => i),
                                datasets: [{
                                    data: this.diskSentinelHistory,
                                    borderColor: '#3b82f6',
                                    backgroundColor: 'rgba(59,130,246,0.1)',
                                    tension: 0.4,
                                    pointRadius: 0
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: { legend: { display: false } },
                                scales: { x: { display: false }, y: { display: false } }
                            }
                        });
                    }

                    // Temperature sparkline
                    if (this.$refs.tempChart && this.tempHistory.length) {
                        this.tempChart = new Chart(this.$refs.tempChart, {
                            type: 'line',
                            data: {
                                labels: this.tempHistory.map((_, i) => i),
                                datasets: [{
                                    data: this.tempHistory,
                                    borderColor: '#f59e0b',
                                    backgroundColor: 'rgba(245,158,11,0.1)',
                                    tension: 0.4,
                                    pointRadius: 0
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: { legend: { display: false } },
                                scales: { x: { display: false }, y: { display: false } }
                            }
                        });
                    }
                },

                async runScript(script) {
                    if (this.runningScript) return;
                    this.runningScript = true;
                    this.modalTitle = `Running ${script}...`;
                    this.modalOutput = 'Starting...';
                    this.showModal = true;

                    try {
                        const response = await fetch('/api/run', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ script })
                        });
                        const result = await response.json();
                        this.modalOutput = result.output;
                        this.modalTitle = result.success ? '✅ Success' : '❌ Failed';
                    } catch (e) {
                        this.modalOutput = 'Error: ' + e.message;
                        this.modalTitle = '❌ Failed';
                    }
                    this.runningScript = false;
                    await this.refreshStats();
                }
            }
        }
    </script>
                }
            }
        }
    </script>
</body>
</html>
EOF

# -------------------------------------------------------------------
# Python server (full version with all new methods)
# -------------------------------------------------------------------
cat > "$HTML_DIR/server.py" <<'EOF'
#!/usr/bin/env python3
"""
Nobara Dashboard Server - Full version with integrated scripts.
"""

import http.server
import socketserver
import json
import subprocess
import os
import sys
import time
import re
import logging
from datetime import datetime, timedelta

# -------------------- Configuration --------------------
PORT = int(os.environ.get('PORT', 8080))
SCRIPT_DIR = os.path.expanduser("~/.local/bin")
LOG_DIR = os.path.expanduser("~/.local/share")
CACHE_TTL = 30  # seconds for expensive commands (updates)
HOST = "0.0.0.0"  # Listen on all network interfaces

logging.basicConfig(
    filename=os.path.join(LOG_DIR, 'noba-web-server.log'),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# -------------------- Helper functions --------------------
ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
def strip_ansi(s):
    return ansi_escape.sub('', s)

def human_bytes(b):
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
        if b < 1024.0:
            return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} PiB"

# Simple TTL cache
class TTLCache:
    def __init__(self, ttl_seconds):
        self.ttl = ttl_seconds
        self.cache = {}
        self.timestamps = {}

    def get(self, key):
        if key in self.cache and datetime.now() - self.timestamps[key] < timedelta(seconds=self.ttl):
            return self.cache[key]
        return None

    def set(self, key, value):
        self.cache[key] = value
        self.timestamps[key] = datetime.now()

_cache = TTLCache(CACHE_TTL)

# -------------------- Handler class --------------------
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory='.', **kwargs)

    def log_message(self, format, *args):
        logging.info("%s - %s" % (self.address_string(), format % args))

    # ---------- Battery ----------
    def get_battery_info(self):
        battery = {'present': False}
        try:
            for bat in ['BAT0', 'BAT1']:
                bat_path = f'/sys/class/power_supply/{bat}'
                if os.path.exists(bat_path):
                    battery['present'] = True
                    with open(f'{bat_path}/status') as f:
                        battery['status'] = f.read().strip()
                    with open(f'{bat_path}/capacity') as f:
                        battery['capacity'] = f.read().strip()
                    health_file = f'{bat_path}/health'
                    if os.path.exists(health_file):
                        with open(health_file) as f:
                            battery['health'] = f.read().strip()
                    else:
                        battery['health'] = 'N/A'
                    voltage_file = f'{bat_path}/voltage_now'
                    if os.path.exists(voltage_file):
                        with open(voltage_file) as f:
                            voltage = int(f.read().strip()) / 1_000_000
                        battery['voltage'] = f"{voltage:.2f}V"
                    else:
                        battery['voltage'] = 'N/A'
                    power_file = f'{bat_path}/power_now'
                    if os.path.exists(power_file):
                        with open(power_file) as f:
                            power = int(f.read().strip()) / 1_000_000
                        battery['power'] = f"{power:.2f}W"
                    else:
                        battery['power'] = 'N/A'
                    break
        except Exception as e:
            logging.error(f"Battery error: {e}")
            battery['present'] = False
        return battery

    # ---------- ZFS ----------
    def get_zfs_pools(self):
        pools = []
        try:
            result = subprocess.run(['zpool', 'list', '-H', '-o', 'name,health'],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        pools.append({'name': parts[0], 'health': parts[1]})
        except Exception as e:
            logging.debug(f"ZFS error (ignored): {e}")
        return pools

    # ---------- GPU (NVIDIA + AMD) ----------
    def get_gpu_temp(self):
        # Try NVIDIA first
        try:
            result = subprocess.run(['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader'],
                                    capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                temp = result.stdout.strip()
                if temp:
                    return temp + "°C"
        except:
            pass
        # Try AMD via rocm-smi
        try:
            result = subprocess.run(['rocm-smi', '--showtemp', '--json'],
                                    capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for card in data.values():
                    if isinstance(card, dict):
                        for key, val in card.items():
                            if 'temperature' in key.lower():
                                return f"{float(val):.0f}°C"
        except:
            pass
        # Fallback to sensors
        try:
            result = subprocess.run(['sensors', '-u'], capture_output=True, text=True, timeout=2)
            match = re.search(r'edge:.*?temp1_input: (\d+\.\d+)', result.stdout, re.DOTALL)
            if match:
                return f"{float(match.group(1)):.0f}°C"
            match = re.search(r'Tdie:.*?temp1_input: (\d+\.\d+)', result.stdout, re.DOTALL)
            if match:
                return f"{float(match.group(1)):.0f}°C"
        except:
            pass
        return "N/A"

    def get_gpu_load(self):
        # NVIDIA
        try:
            result = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader'],
                                    capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                load = result.stdout.strip()
                if load:
                    return load
        except:
            pass
        # AMD via rocm-smi
        try:
            result = subprocess.run(['rocm-smi', '--showuse', '--json'],
                                    capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for card in data.values():
                    if isinstance(card, dict):
                        for key, val in card.items():
                            if 'use' in key.lower():
                                return f"{val}%"
        except:
            pass
        return 'N/A'

    # ---------- Docker ----------
    def get_docker_containers(self):
        containers = []
        try:
            result = subprocess.run(['docker', 'ps', '--format', '{{.Names}} ({{.Status}})'],
                                    capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line:
                        containers.append(line.strip())
        except Exception as e:
            logging.debug(f"Docker error: {e}")
        return containers

    # ---------- Disk I/O ----------
    def get_disk_io(self):
        disks = []
        try:
            with open('/proc/diskstats') as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 14:
                        continue
                    name = parts[2]
                    if name.startswith(('loop', 'ram', 'sr')):
                        continue
                    # Allow partitions
                    reads = int(parts[5])   # sectors read
                    writes = int(parts[9])  # sectors written
                    read_bytes = reads * 512
                    write_bytes = writes * 512
                    disks.append({
                        'name': name,
                        'read': human_bytes(read_bytes),
                        'write': human_bytes(write_bytes)
                    })
        except Exception as e:
            logging.error(f"Disk I/O error: {e}")
        return disks[:10]

    # ---------- Systemd service memory/CPU ----------
    def get_service_details(self, service):
        details = {}
        try:
            result = subprocess.run(['systemctl', '--user', 'show', service],
                                    capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if '=' in line:
                        key, val = line.split('=', 1)
                        if key == 'MemoryCurrent':
                            if val and val != '0':
                                details['memory'] = human_bytes(int(val))
                            else:
                                details['memory'] = 'N/A'
                        elif key == 'CPUUsageNSec':
                            if val and val != '0':
                                sec = int(val) / 1_000_000_000
                                if sec < 60:
                                    details['cpu'] = f"{sec:.1f}s"
                                elif sec < 3600:
                                    minutes = int(sec // 60)
                                    seconds = int(sec % 60)
                                    details['cpu'] = f"{minutes}m{seconds}s"
                                else:
                                    hours = int(sec // 3600)
                                    minutes = int((sec % 3600) // 60)
                                    details['cpu'] = f"{hours}h{minutes}m"
                            else:
                                details['cpu'] = 'N/A'
        except Exception as e:
            logging.debug(f"Service details error for {service}: {e}")
        return details

    # ---------- NEW: Disk Sentinel ----------
    def get_disk_sentinel(self):
        """Run disk-sentinel.sh and capture output + history for sparkline."""
        result = {'output': '', 'history': []}
        script = os.path.join(SCRIPT_DIR, 'disk-sentinel.sh')
        if os.path.exists(script):
            try:
                proc = subprocess.run([script], capture_output=True, text=True, timeout=10)
                out = proc.stdout + proc.stderr
                result['output'] = strip_ansi(out)[-500:]
                # TODO: Replace with real history extraction from your script's logs
                # For now, placeholder data:
                result['history'] = [75, 78, 80, 77, 79, 82, 81]
            except Exception as e:
                result['output'] = f"Error: {e}"
        else:
            result['output'] = "Script not found"
        return result

    # ---------- NEW: Temperature Alert ----------
    def get_temperature_alert(self):
        """Run temperature-alert.sh and capture output + history."""
        result = {'output': '', 'history': []}
        script = os.path.join(SCRIPT_DIR, 'temperature-alert.sh')
        if os.path.exists(script):
            try:
                proc = subprocess.run([script], capture_output=True, text=True, timeout=5)
                out = proc.stdout + proc.stderr
                result['output'] = strip_ansi(out)[-500:]
                # TODO: Replace with real temperature history
                result['history'] = [45, 47, 50, 48, 46, 49, 52]
            except Exception as e:
                result['output'] = f"Error: {e}"
        else:
            result['output'] = "Script not found"
        return result

    # ---------- NEW: System Report ----------
    def get_system_report(self):
        """Run system-report.sh and capture full output."""
        result = {'output': ''}
        script = os.path.join(SCRIPT_DIR, 'system-report.sh')
        if os.path.exists(script):
            try:
                proc = subprocess.run([script], capture_output=True, text=True, timeout=10)
                out = proc.stdout + proc.stderr
                result['output'] = strip_ansi(out)[-1000:]
            except Exception as e:
                result['output'] = f"Error: {e}"
        else:
            result['output'] = "Script not found"
        return result

    # ---------- NEW: Service Watch ----------
    def get_service_watch(self):
        """Run service-watch.sh and parse its output into structured data."""
        services = []
        script = os.path.join(SCRIPT_DIR, 'service-watch.sh')
        if os.path.exists(script):
            try:
                proc = subprocess.run([script], capture_output=True, text=True, timeout=10)
                for line in proc.stdout.splitlines():
                    # Assume format: "service-name: status (response)"
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        name = parts[0].strip()
                        rest = parts[1].strip()
                        status_match = re.search(r'^(running|degraded|failed|stopped)', rest, re.I)
                        status = status_match.group(1).lower() if status_match else 'unknown'
                        time_match = re.search(r'\((\d+ms)\)', rest)
                        response = time_match.group(1) if time_match else ''
                        services.append({'name': name, 'status': status, 'response': response})
            except Exception as e:
                logging.error(f"Service watch error: {e}")
        return services

    # ---------- NEW: Backup Verifier ----------
    def get_backup_verifier(self):
        """Run backup-verifier.sh and capture result."""
        result = {'result': 'N/A', 'output': ''}
        script = os.path.join(SCRIPT_DIR, 'backup-verifier.sh')
        if os.path.exists(script):
            try:
                proc = subprocess.run([script], capture_output=True, text=True, timeout=30)
                out = proc.stdout + proc.stderr
                result['output'] = strip_ansi(out)[-500:]
                if 'OK' in out or 'verified' in out.lower():
                    result['result'] = 'OK'
                elif 'FAIL' in out or 'error' in out.lower():
                    result['result'] = 'Failed'
                else:
                    result['result'] = 'Unknown'
            except Exception as e:
                result['output'] = f"Error: {e}"
                result['result'] = 'Error'
        else:
            result['output'] = "Script not found"
        return result

    # ---------- NEW: Cloud Backup ----------
    def get_cloud_backup(self):
        """Run cloud-backup.sh and parse status."""
        result = {'status': 'N/A', 'lastSync': 'N/A', 'size': 'N/A', 'output': ''}
        script = os.path.join(SCRIPT_DIR, 'cloud-backup.sh')
        if os.path.exists(script):
            try:
                proc = subprocess.run([script, '--status'], capture_output=True, text=True, timeout=20)
                out = proc.stdout + proc.stderr
                result['output'] = strip_ansi(out)[-500:]
                for line in out.splitlines():
                    if 'Status:' in line:
                        result['status'] = line.split(':',1)[1].strip()
                    elif 'Last sync:' in line:
                        result['lastSync'] = line.split(':',1)[1].strip()
                    elif 'Size:' in line:
                        result['size'] = line.split(':',1)[1].strip()
            except Exception as e:
                result['output'] = f"Error: {e}"
        else:
            result['output'] = "Script not found"
        return result

    # ---------- GET /api/stats ----------
    def do_GET(self):
        try:
            if self.path == '/api/stats':
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                stats = self.get_stats()
                self.wfile.write(json.dumps(stats).encode())
            else:
                super().do_GET()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            logging.error(f"GET error: {e}")

    # ---------- POST /api/run (extended for new scripts) ----------
    def do_POST(self):
        if self.path == '/api/run':
            try:
                content_len = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_len)
                data = json.loads(post_data)
                script = data.get('script', '')

                script_map = {
                    'backup': 'backup-to-nas.sh',
                    'verify': 'backup-verifier.sh',
                    'organize': 'organize-downloads.sh',
                    'diskcheck': 'disk-sentinel.sh',
                    'speedtest': 'speedtest-cli',
                    'cloudbackup': 'cloud-backup.sh',
                    # add more as needed
                }

                if script == 'speedtest':
                    try:
                        proc = subprocess.run(['speedtest-cli', '--simple'],
                                              capture_output=True, text=True, timeout=60)
                        output = proc.stdout + proc.stderr
                        success = proc.returncode == 0
                    except Exception as e:
                        output = f"Speed test failed: {str(e)}"
                        success = False
                else:
                    script_file = os.path.join(SCRIPT_DIR, script_map.get(script, ''))
                    if not os.path.exists(script_file):
                        output = f"Script {script} not found"
                        success = False
                    else:
                        proc = subprocess.run(
                            [script_file, '--verbose'],
                            capture_output=True, text=True,
                            timeout=120, cwd=SCRIPT_DIR
                        )
                        output = proc.stdout + proc.stderr
                        success = proc.returncode == 0

                result = {'success': success, 'output': output}
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
            except subprocess.TimeoutExpired:
                output = "Script timed out."
                result = {'success': False, 'output': output}
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
            except Exception as e:
                output = f"Error: {str(e)}"
                result = {'success': False, 'output': output}
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
        else:
            self.send_response(404)
            self.end_headers()

    # ---------- Main stats collector ----------
    def get_stats(self):
        stats = {'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')}

        # Uptime
        try:
            with open('/proc/uptime') as f:
                uptime_sec = float(f.read().split()[0])
                hours = int(uptime_sec // 3600)
                minutes = int((uptime_sec % 3600) // 60)
                stats['uptime'] = f"{hours}h {minutes}m"
        except:
            stats['uptime'] = 'N/A'

        # Load average
        try:
            stats['loadavg'] = open('/proc/loadavg').read().split()[0]
        except:
            stats['loadavg'] = 'N/A'

        # Memory
        try:
            meminfo = {}
            with open('/proc/meminfo') as f:
                for line in f:
                    if line.startswith('MemTotal:'):
                        meminfo['total'] = int(line.split()[1]) // 1024
                    elif line.startswith('MemAvailable:'):
                        meminfo['avail'] = int(line.split()[1]) // 1024
            stats['memory'] = f"{meminfo.get('avail',0)}Mi/{meminfo.get('total',0)}Mi"
        except:
            stats['memory'] = 'N/A'

        # CPU Temp (reuse GPU temp)
        stats['cpuTemp'] = self.get_gpu_temp()

        # Backup
        backup_log = os.path.join(LOG_DIR, 'backup-to-nas.log')
        if os.path.exists(backup_log):
            with open(backup_log) as f:
                lines = [strip_ansi(l) for l in f.readlines()]
                last_line = lines[-1].strip() if lines else ''
                if 'ERROR' in last_line:
                    stats['backupStatus'] = 'Failed'
                elif 'finished' in last_line:
                    stats['backupStatus'] = 'OK'
                else:
                    stats['backupStatus'] = 'Unknown'
                stats['backupLog'] = ''.join(lines[-5:])[-500:]
                stats['backupTime'] = time.ctime(os.path.getmtime(backup_log))
        else:
            stats['backupStatus'] = 'No log'
            stats['backupLog'] = ''
            stats['backupTime'] = ''

        # Updates (cached)
        cached_updates = _cache.get('updates')
        if cached_updates:
            dnf_updates, flatpak_updates = cached_updates
        else:
            dnf_out = ''
            try:
                dnf_out = subprocess.run(['dnf', 'check-update', '-q'], capture_output=True, text=True, timeout=10).stdout
            except:
                pass
            dnf_updates = len([l for l in dnf_out.splitlines() if l and not l.startswith('Last metadata')])
            flatpak_out = ''
            try:
                flatpak_out = subprocess.run(['flatpak', 'remote-ls', '--updates'], capture_output=True, text=True, timeout=10).stdout
            except:
                pass
            flatpak_updates = len([l for l in flatpak_out.splitlines() if l])
            _cache.set('updates', (dnf_updates, flatpak_updates))
        stats['dnfUpdates'] = dnf_updates
        stats['flatpakUpdates'] = flatpak_updates

        # Disk usage
        disks = []
        try:
            output = subprocess.run(['df', '-h'], capture_output=True, text=True).stdout
            for line in output.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 5 and parts[0].startswith('/dev/'):
                    mount = parts[5] if len(parts) > 5 else ''
                    if mount.startswith(('/var/lib/snapd', '/boot')):
                        continue
                    percent = parts[4].replace('%', '')
                    if int(percent) >= 90:
                        bar_class = 'danger'
                    elif int(percent) >= 75:
                        bar_class = 'warning'
                    else:
                        bar_class = 'success'
                    disks.append({'mount': mount, 'percent': percent, 'barClass': bar_class})
        except:
            pass
        stats['disks'] = disks

        # Download organizer
        organizer_log = os.path.join(LOG_DIR, 'download-organizer.log')
        moved = 0
        last_move = ''
        if os.path.exists(organizer_log):
            with open(organizer_log) as f:
                lines = [strip_ansi(l) for l in f.readlines()]
                moved = sum(1 for l in lines if 'Moved:' in l)
                last_line = next((l for l in reversed(lines) if 'Moved:' in l), '')
                if last_line:
                    last_move = last_line.split('Moved:')[-1].strip()
            stats['movedFiles'] = moved
            stats['lastMove'] = last_move
            stats['organizerLog'] = ''.join(lines[-5:])[-500:]
        else:
            stats['movedFiles'] = 0
            stats['lastMove'] = ''
            stats['organizerLog'] = ''

        # Disk alerts (from disk-sentinel.log, but we'll also have a separate card)
        disk_log = os.path.join(LOG_DIR, 'disk-sentinel.log')
        if os.path.exists(disk_log):
            with open(disk_log) as f:
                lines = [strip_ansi(l) for l in f.readlines()]
                alerts = [l for l in lines if 'WARNING' in l or 'exceeded' in l]
                stats['diskAlerts'] = ''.join(alerts[-5:])[-500:] if alerts else 'No recent warnings'
        else:
            stats['diskAlerts'] = 'No log'

        # Network
        try:
            result = subprocess.run(['ip', '-4', 'route', 'get', '1'],
                                    capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                match = re.search(r'src\s+(\d+\.\d+\.\d+\.\d+)', result.stdout)
                stats['defaultIp'] = match.group(1) if match else 'N/A'
            else:
                stats['defaultIp'] = 'N/A'
        except:
            stats['defaultIp'] = 'N/A'

        interfaces = []
        try:
            with open('/proc/net/dev') as f:
                lines = f.readlines()[2:]
                for line in lines:
                    parts = line.split()
                    iface = parts[0].strip(':')
                    rx_bytes = int(parts[1])
                    tx_bytes = int(parts[9])
                    interfaces.append({
                        'name': iface,
                        'rx': human_bytes(rx_bytes),
                        'tx': human_bytes(tx_bytes)
                    })
            stats['interfaces'] = interfaces[:3]
        except:
            stats['interfaces'] = []

        # Services with details
        service_list = os.environ.get('NOBA_WEB_SERVICES', 'backup-to-nas.service,organize-downloads.service,noba-web.service,syncthing.service').split(',')
        services_status = []
        for svc in service_list:
            svc = svc.strip()
            if not svc:
                continue
            try:
                result = subprocess.run(['systemctl', '--user', 'is-active', svc],
                                        capture_output=True, text=True, timeout=2)
                status = result.stdout.strip()
                if status not in ('active', 'inactive', 'failed'):
                    status = 'unknown'
            except:
                status = 'error'
            details = self.get_service_details(svc)
            svc_info = {'name': svc, 'status': status}
            if details:
                svc_info.update(details)
            services_status.append(svc_info)
        stats['services'] = services_status

        # GPU
        stats['gpuTemp'] = self.get_gpu_temp()
        stats['gpuLoad'] = self.get_gpu_load()

        # Docker
        stats['dockerContainers'] = self.get_docker_containers()

        # Battery
        stats['battery'] = self.get_battery_info()

        # ZFS
        stats['zfs'] = {'pools': self.get_zfs_pools()}

        # Disk I/O
        stats['diskio'] = self.get_disk_io()

        # NEW integrated data
        disk_sentinel = self.get_disk_sentinel()
        stats['diskSentinel'] = {'output': disk_sentinel['output']}
        stats['diskSentinelHistory'] = disk_sentinel['history']

        temp_alert = self.get_temperature_alert()
        stats['temperatureAlert'] = {'output': temp_alert['output']}
        stats['tempHistory'] = temp_alert['history']

        stats['systemReport'] = self.get_system_report()
        stats['serviceWatch'] = self.get_service_watch()
        stats['backupVerifier'] = self.get_backup_verifier()
        stats['cloudBackup'] = self.get_cloud_backup()

        return stats

# -------------------- Server setup --------------------
def run_server():
    handler = Handler
    with socketserver.TCPServer((HOST, PORT), handler) as httpd:
        httpd.allow_reuse_address = True
        logging.info(f"Serving dashboard at http://{HOST}:{PORT} (accessible from network)")
        print(f"Serving dashboard at http://{HOST}:{PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logging.info("Shutting down...")
            httpd.shutdown()

if __name__ == '__main__':
    with open(os.environ.get('PID_FILE', '/tmp/noba-web-server.pid'), 'w') as f:
        f.write(str(os.getpid()))
    run_server()
EOF

# -------------------------------------------------------------------
# Clean up and start
# -------------------------------------------------------------------
kill_server

export PORT
export PID_FILE="$SERVER_PID_FILE"
cd "$HTML_DIR"
nohup python3 server.py >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > "$SERVER_PID_FILE"

log_info "Web dashboard started on http://0.0.0.0:$PORT (accessible from network)"
log_info "Log file: $LOG_FILE"
log_info "Use '$0 --kill' to stop the server."
