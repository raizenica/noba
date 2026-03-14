#!/bin/bash
# noba-web.sh – Ultimate Modular Dashboard v7.1.0 (Pi-hole v6 API & Alerts Fix)
# Version: 7.1.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/noba-lib.sh"

START_PORT="${START_PORT:-8080}"
MAX_PORT="${MAX_PORT:-8090}"
HTML_DIR="${HTML_DIR:-/tmp/noba-web}"
SERVER_PID_FILE="${SERVER_PID_FILE:-/tmp/noba-web-server.pid}"
LOG_FILE="${LOG_FILE:-/tmp/noba-web.log}"
KILL_ONLY=false
HOST="${HOST:-0.0.0.0}"

show_version() { echo "noba-web.sh version 7.1.0"; exit 0; }
show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]
Launch an interactive web dashboard for the Nobara Automation Suite.
Options:
  -p, --port PORT  Start searching from PORT (default: 8080)
  -m, --max PORT   Maximum port to try (default: 8090)
  --host HOST      Bind to specific host/IP
  -k, --kill       Kill any running noba-web server and exit
  --help           Show this help message
  --version        Show version information
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
            if kill -0 "$pid" 2>/dev/null; then kill -9 "$pid" 2>/dev/null || true; fi
        fi
        rm -f "$SERVER_PID_FILE"
    fi
}

find_free_port() {
    local start="$1" max="$2" port
    if command -v ss &>/dev/null; then
        for port in $(seq "$start" "$max"); do
            if ! ss -tuln 2>/dev/null | grep -q ":$port[[:space:]]"; then echo "$port"; return 0; fi
        done
    elif command -v lsof &>/dev/null; then
        for port in $(seq "$start" "$max"); do
            if ! lsof -i:"$port" -sTCP:LISTEN -t 2>/dev/null | grep -q .; then echo "$port"; return 0; fi
        done
    else
        log_error "Neither 'ss' nor 'lsof' found."; exit 1
    fi
    return 1
}

if ! PARSED_ARGS=$(getopt -o p:m:k -l port:,max:,host:,kill,help,version -- "$@"); then show_help; fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -p|--port) START_PORT="$2"; shift 2 ;; -m|--max) MAX_PORT="$2"; shift 2 ;; --host) HOST="$2"; shift 2 ;;
        -k|--kill) KILL_ONLY=true; shift ;; --help) show_help ;; --version) show_version ;; --) shift; break ;;
        *) log_error "Internal error parsing arguments."; exit 1 ;;
    esac
done

if [ "$KILL_ONLY" = true ]; then kill_server; log_info "Server stopped."; exit 0; fi
check_deps python3
PORT=$(find_free_port "$START_PORT" "$MAX_PORT") || die "No free port found."
log_info "Using port $PORT"

mkdir -p "$HTML_DIR"
rm -f "$HTML_DIR"/*.html "$HTML_DIR"/server.py "$HTML_DIR"/stats.json 2>/dev/null || true

# -------------------------------------------------------------------
# Write index.html
# -------------------------------------------------------------------
cat > "$HTML_DIR/index.html" <<'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Nobara Modular Dashboard</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
    <script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>

    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        :root {
            --bg-dark: #0f172a; --bg-card: #1e293b; --card-border: #334155; --text-main: #f8fafc; --text-muted: #94a3b8;
            --accent: #3b82f6; --accent-hover: #2563eb; --success: #10b981; --warning: #f59e0b; --danger: #ef4444;
            --success-bg: rgba(16, 185, 129, 0.15); --warning-bg: rgba(245, 158, 11, 0.15); --danger-bg: rgba(239, 68, 68, 0.15);
        }
        [data-theme="dracula"] {
            --bg-dark: #282a36; --bg-card: #44475a; --card-border: #6272a4; --text-main: #f8f8f2; --text-muted: #bfbfbf;
            --accent: #bd93f9; --accent-hover: #ff79c6; --success: #50fa7b; --warning: #f1fa8c; --danger: #ff5555;
            --success-bg: rgba(80, 250, 123, 0.15); --warning-bg: rgba(241, 250, 140, 0.15); --danger-bg: rgba(255, 85, 85, 0.15);
        }
        [data-theme="nord"] {
            --bg-dark: #2e3440; --bg-card: #3b4252; --card-border: #4c566a; --text-main: #ECEFF4; --text-muted: #d8dee9;
            --accent: #88c0d0; --accent-hover: #81a1c1; --success: #a3be8c; --warning: #ebcb8b; --danger: #bf616a;
            --success-bg: rgba(163, 190, 140, 0.15); --warning-bg: rgba(235, 203, 139, 0.15); --danger-bg: rgba(191, 97, 106, 0.15);
        }
        [data-theme="catppuccin"] {
            --bg-dark: #24273a; --bg-card: #363a4f; --card-border: #494d64; --text-main: #cad3f5; --text-muted: #a5adcb;
            --accent: #8aadf4; --accent-hover: #b7bdf8; --success: #a6da95; --warning: #eed49f; --danger: #ed8796;
            --success-bg: rgba(166, 218, 149, 0.15); --warning-bg: rgba(238, 212, 159, 0.15); --danger-bg: rgba(237, 135, 150, 0.15);
        }
        [data-theme="tokyo"] {
            --bg-dark: #1a1b26; --bg-card: #24283b; --card-border: #414868; --text-main: #c0caf5; --text-muted: #a9b1d6;
            --accent: #7aa2f7; --accent-hover: #89ddff; --success: #9ece6a; --warning: #e0af68; --danger: #f7768e;
            --success-bg: rgba(158, 206, 106, 0.15); --warning-bg: rgba(224, 175, 104, 0.15); --danger-bg: rgba(247, 118, 142, 0.15);
        }
        [data-theme="gruvbox"] {
            --bg-dark: #282828; --bg-card: #3c3836; --card-border: #504945; --text-main: #ebdbb2; --text-muted: #a89984;
            --accent: #83a598; --accent-hover: #458588; --success: #b8bb26; --warning: #fabd2f; --danger: #fb4934;
            --success-bg: rgba(184, 187, 38, 0.15); --warning-bg: rgba(250, 189, 47, 0.15); --danger-bg: rgba(251, 73, 52, 0.15);
        }

        body { background-color: var(--bg-dark); color: var(--text-main); font-family: 'Inter', system-ui, sans-serif; padding: 2rem; line-height: 1.5; overflow-x: hidden; transition: background-color 0.3s; }
        .header-container { display: flex; justify-content: space-between; align-items: center; margin-bottom: 2rem; flex-wrap: wrap; gap: 1rem;}
        h1 { font-size: 2rem; font-weight: 700; display: flex; align-items: center; gap: 0.75rem; margin: 0; }
        h1 i { color: var(--accent); transition: color 0.3s; }
        .controls { display: flex; gap: 1rem; align-items: center; }

        .theme-select { background: var(--bg-card); color: var(--text-main); border: 1px solid var(--card-border); border-radius: 0.5rem; padding: 0.5rem; outline: none; cursor: pointer; }
        .status-pill { background: var(--card-border); padding: 0.5rem 1rem; border-radius: 2rem; font-size: 0.85rem; display: flex; align-items: center; gap: 0.5rem; transition: background 0.2s; min-width: 150px; justify-content: center; }
        .status-icon-btn { background: var(--card-border); padding: 0.5rem 1rem; border-radius: 2rem; cursor: pointer; transition: background 0.2s; }
        .status-icon-btn:hover { background: var(--accent); color: white; }

        .dashboard-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 1.5rem; align-items: start; }
        .module-card { background: var(--bg-card); border: 1px solid var(--card-border); border-radius: 1rem; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); transition: box-shadow 0.2s, background-color 0.3s; will-change: transform; }
        .module-header { padding: 1.25rem 1.5rem; background: rgba(0,0,0,0.2); border-bottom: 1px solid var(--card-border); font-weight: 600; font-size: 1.1rem; display: flex; align-items: center; gap: 0.75rem; cursor: grab; user-select: none; }
        .module-header:active { cursor: grabbing; }
        .module-header .icon-main { color: var(--accent); transition: color 0.3s;}
        .drag-handle { margin-left: auto; color: var(--text-muted); opacity: 0.3; transition: opacity 0.2s; }
        .module-card:hover .drag-handle { opacity: 1; }

        .sortable-ghost { opacity: 0.4; border: 2px dashed var(--accent); }
        .sortable-drag { cursor: grabbing !important; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5) !important; opacity: 1 !important; z-index: 100; }

        .module-body { padding: 1.5rem; }
        .data-row { display: flex; justify-content: space-between; align-items: flex-start; padding: 0.5rem 0; border-bottom: 1px dashed rgba(255,255,255,0.05); }
        .data-row:last-child { border-bottom: none; }
        .data-label { color: var(--text-muted); font-size: 0.95rem; white-space: nowrap; margin-right: 1rem; }
        .data-val { font-weight: 500; text-align: right; }

        .badge { padding: 0.25rem 0.75rem; border-radius: 1rem; font-size: 0.8rem; font-weight: 600; letter-spacing: 0.05em; display: inline-flex; align-items: center; gap: 0.25rem; white-space: nowrap; overflow: hidden; }
        .badge-success { background: var(--success-bg); color: var(--success); }
        .badge-warning { background: var(--warning-bg); color: var(--warning); }
        .badge-danger { background: var(--danger-bg); color: var(--danger); }
        .badge-neutral { background: var(--card-border); color: var(--text-muted); }

        .progress-container { margin: 0.75rem 0; }
        .progress-header { display: flex; justify-content: space-between; font-size: 0.85rem; margin-bottom: 0.3rem; }
        .progress-track { width: 100%; height: 6px; background: var(--card-border); border-radius: 3px; overflow: hidden; }
        .progress-fill { height: 100%; border-radius: 3px; transition: width 0.4s ease; }

        .mini-card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0.75rem; }
        .mini-card { background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.05); padding: 0.75rem; border-radius: 0.5rem; display: flex; flex-direction: column; gap: 0.5rem; }
        .mini-card-title { font-size: 0.85rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: flex; justify-content: space-between; align-items: center; }
        .svc-controls { display: flex; gap: 0.4rem; }
        .svc-btn { background: none; border: none; color: var(--text-muted); cursor: pointer; transition: color 0.2s; font-size: 0.9rem; }
        .svc-btn:hover { color: var(--accent); }
        .svc-btn:disabled { opacity: 0.3; cursor: not-allowed; }

        textarea.custom-notes { width: 100%; height: 120px; background: rgba(0,0,0,0.2); color: var(--text-main); border: 1px solid var(--card-border); border-radius: 0.5rem; padding: 0.75rem; font-family: inherit; resize: vertical; outline: none; transition: border-color 0.2s; }
        textarea.custom-notes:focus { border-color: var(--accent); }
        input.custom-input, textarea.custom-input { width: 100%; padding: 0.5rem; background: rgba(0,0,0,0.2); border: 1px solid var(--card-border); color: var(--text-main); border-radius: 0.25rem; font-family: monospace; font-size: 0.85rem; }
        input.custom-input:focus, textarea.custom-input:focus { border-color: var(--accent); outline: none; }

        .action-grid { display: grid; grid-template-columns: 1fr; gap: 0.75rem; }
        .btn { padding: 0.75rem 1rem; border: none; border-radius: 0.5rem; font-weight: 600; font-size: 0.95rem; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 0.5rem; transition: all 0.2s; background: var(--card-border); color: var(--text-main); }
        .btn:hover:not(:disabled) { background: rgba(255,255,255,0.1); }
        .btn-primary { background: var(--accent); color: white; }
        .btn-primary:hover:not(:disabled) { background: var(--accent-hover); }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }

        .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.7); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; z-index: 50; }
        .modal-box { background: var(--bg-card); border: 1px solid var(--card-border); border-radius: 1rem; width: 90%; max-width: 800px; padding: 2rem; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5); max-height: 90vh; overflow-y: auto;}
        pre.console-output { background: #000; color: #a3be8c; padding: 1rem; border-radius: 0.5rem; overflow-x: auto; max-height: 50vh; font-family: 'Fira Code', monospace; font-size: 0.85rem; }

        .settings-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1.5rem;}
        .setting-item { display: flex; align-items: center; gap: 0.75rem; cursor: pointer;}
        @media (max-width: 768px) { .dashboard-grid { grid-template-columns: 1fr; } .settings-grid { grid-template-columns: 1fr; } }
    </style>
</head>
<body x-data="dashboard()" x-init="init()" :data-theme="theme">

    <div class="header-container">
        <h1><i class="fas fa-layer-group"></i> Nobara Command Center</h1>
        <div class="controls">
            <select class="theme-select" x-model="theme" @change="saveSettings()">
                <option value="default">Default Dark</option>
                <option value="catppuccin">Catppuccin</option>
                <option value="tokyo">Tokyo Night</option>
                <option value="gruvbox">Gruvbox</option>
                <option value="dracula">Dracula</option>
                <option value="nord">Nord</option>
            </select>
            <div class="status-icon-btn" @click="showSettings = true" title="Manage Settings">
                <i class="fas fa-cog"></i>
            </div>
            <div class="status-pill">
                <i class="fas fa-sync-alt" :class="refreshing ? 'fa-spin' : ''"></i>
                <span x-text="refreshing ? 'Updating...' : 'Live: ' + timestamp"></span>
            </div>
        </div>
    </div>

    <div class="dashboard-grid" id="sortable-dashboard">

        <div class="module-card" data-id="card-core" x-show="visibleCards.core">
            <div class="module-header"><i class="fas fa-microchip icon-main"></i> Core System<i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="module-body">
                <div class="data-row"><span class="data-label">OS</span><span class="data-val" x-text="osName"></span></div>
                <div class="data-row"><span class="data-label">Kernel</span><span class="data-val" x-text="kernel"></span></div>
                <div class="data-row"><span class="data-label">Uptime</span><span class="data-val" x-text="uptime"></span></div>
                <div class="data-row"><span class="data-label">Load Average</span><span class="data-val" x-text="loadavg"></span></div>
                <div class="data-row"><span class="data-label">Memory</span><span class="data-val" x-text="memory"></span></div>
                <div class="data-row"><span class="data-label">CPU Temp</span><span class="badge" :class="cpuTempClass" x-text="cpuTemp"></span></div>
            </div>
        </div>

        <div class="module-card" data-id="card-battery" x-show="visibleCards.battery">
            <div class="module-header"><i class="fas fa-battery-half icon-main"></i> Power State<i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="module-body">
                <div class="data-row">
                    <span class="data-label">Status</span>
                    <span class="badge" :class="battery.status === 'Charging' || battery.status === 'Full' ? 'badge-success' : (battery.status === 'Discharging' ? 'badge-warning' : 'badge-neutral')" x-text="battery.status"></span>
                </div>
                <div class="progress-container" style="margin-top: 1rem;">
                    <div class="progress-header"><span>Battery Level</span><span x-text="battery.percent+'%'"></span></div>
                    <div class="progress-track"><div class="progress-fill" :style="`width: ${battery.percent}%; background: var(--${battery.percent > 20 ? 'success' : 'danger'});`"></div></div>
                </div>
            </div>
        </div>

        <div class="module-card" data-id="card-bookmarks" x-show="visibleCards.bookmarks">
            <div class="module-header"><i class="fas fa-bookmark icon-main"></i> Homelab Links<i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="module-body" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 0.75rem;">
                <template x-for="b in parsedBookmarks" :key="b.name">
                    <a :href="b.url" target="_blank" class="btn" style="text-decoration: none; justify-content: flex-start; padding: 0.5rem 0.75rem; background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.05); color: var(--text-main);">
                        <i class="fas" :class="b.icon" style="color: var(--accent); width: 20px; text-align: center;"></i>
                        <span x-text="b.name" style="font-size: 0.85rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-left: 0.5rem;"></span>
                    </a>
                </template>
            </div>
        </div>

        <div class="module-card" data-id="card-pihole" x-show="visibleCards.pihole">
            <div class="module-header"><i class="fas fa-shield-alt icon-main"></i> Pi-hole Adblock<i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="module-body">
                <template x-if="pihole">
                    <div>
                        <div class="data-row"><span class="data-label">DNS Status</span>
                            <span class="badge" :class="pihole.status === 'enabled' ? 'badge-success' : 'badge-danger'" x-text="pihole.status"></span>
                        </div>
                        <div class="data-row"><span class="data-label">Total Queries</span><span class="data-val" x-text="pihole.queries"></span></div>
                        <div class="data-row"><span class="data-label">Ads Blocked</span><span class="data-val" style="color: var(--danger); font-weight: bold;" x-text="pihole.blocked"></span></div>
                        <div class="progress-container" style="margin-top: 1rem;">
                            <div class="progress-header"><span>Block Percentage</span><span x-text="pihole.percent + '%'"></span></div>
                            <div class="progress-track"><div class="progress-fill" :style="`width: ${parseFloat(pihole.percent)}%; background: var(--accent);`"></div></div>
                        </div>
                    </div>
                </template>
                <template x-if="!pihole">
                    <div style="color: var(--text-muted); font-size: 0.85rem; font-style: italic;">Unable to reach Pi-hole API. Ensure Pi-hole URL and App Password (v6) are set in Settings.</div>
                </template>
            </div>
        </div>

        <div class="module-card" data-id="card-hw" x-show="visibleCards.hw">
            <div class="module-header"><i class="fas fa-memory icon-main"></i> Hardware Profile<i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="module-body">
                <div class="data-row"><span class="data-label">CPU Info</span><span class="data-val" style="font-size:0.85rem;" x-html="hwCpu"></span></div>
                <div class="data-row"><span class="data-label">GPU Info</span><span class="data-val" style="font-size:0.85rem; line-height:1.6;" x-html="hwGpu"></span></div>
                <div class="data-row" x-show="gpuTemp !== 'N/A'"><span class="data-label">GPU Temp</span><span class="badge" :class="gpuTempClass" x-text="gpuTemp"></span></div>
            </div>
        </div>

        <div class="module-card" data-id="card-procs" x-show="visibleCards.procs">
            <div class="module-header"><i class="fas fa-chart-line icon-main"></i> Resource Hogs<i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="module-body">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                    <div>
                        <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 0.5rem; border-bottom: 1px solid var(--card-border); padding-bottom: 0.2rem;">Top CPU</div>
                        <template x-for="p in topCpu" :key="p.name">
                            <div style="display: flex; justify-content: space-between; font-size: 0.8rem; padding: 0.2rem 0;">
                                <span x-text="p.name" style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 80px;"></span>
                                <span style="color: var(--warning);" x-text="p.val"></span>
                            </div>
                        </template>
                    </div>
                    <div>
                        <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 0.5rem; border-bottom: 1px solid var(--card-border); padding-bottom: 0.2rem;">Top Memory</div>
                        <template x-for="p in topMem" :key="p.name">
                            <div style="display: flex; justify-content: space-between; font-size: 0.8rem; padding: 0.2rem 0;">
                                <span x-text="p.name" style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 80px;"></span>
                                <span style="color: var(--accent);" x-text="p.val"></span>
                            </div>
                        </template>
                    </div>
                </div>
            </div>
        </div>

        <div class="module-card" data-id="card-radar" x-show="visibleCards.radar">
            <div class="module-header"><i class="fas fa-satellite-dish icon-main"></i> Network Radar<i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="module-body">
                <template x-for="target in radar" :key="target.ip">
                    <div class="data-row" style="align-items: center;">
                        <span class="data-label" style="font-family: monospace;" x-text="target.ip"></span>
                        <span class="badge" :class="target.status === 'Up' ? 'badge-success' : 'badge-danger'">
                            <i class="fas" :class="target.status === 'Up' ? 'fa-check-circle' : 'fa-times-circle'"></i> <span x-text="target.status"></span>
                        </span>
                    </div>
                </template>
            </div>
        </div>

        <div class="module-card" data-id="card-storage" x-show="visibleCards.storage">
            <div class="module-header"><i class="fas fa-hdd icon-main"></i> Storage Matrix<i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="module-body">
                <template x-for="pool in zfs.pools" :key="pool.name">
                    <div class="data-row" style="align-items: center;"><span class="data-label" x-text="'ZFS: ' + pool.name"></span><span class="badge" :class="{'badge-success': pool.health==='ONLINE','badge-warning': pool.health==='DEGRADED','badge-danger': pool.health==='FAULTED'}" x-text="pool.health"></span></div>
                </template>
                <div style="margin-top: 1rem;" x-show="zfs.pools && zfs.pools.length > 0"></div>
                <template x-for="disk in disks" :key="disk.mount">
                    <div class="progress-container">
                        <div class="progress-header"><span x-text="disk.mount"></span><span x-text="disk.percent+'%'"></span></div>
                        <div class="progress-track"><div class="progress-fill" :style="`width: ${disk.percent}%; background: var(--${disk.barClass});`"></div></div>
                    </div>
                </template>
            </div>
        </div>

        <div class="module-card" style="grid-column: 1 / -1;" data-id="card-services" x-show="visibleCards.services">
            <div class="module-header"><i class="fas fa-cogs icon-main"></i> Interactive Services<i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="module-body mini-card-grid">
                <template x-for="svc in services" :key="svc.name">
                    <div class="mini-card">
                        <div class="mini-card-title">
                            <span x-text="svc.name.replace('.service','')"></span>
                            <div class="svc-controls">
                                <button class="svc-btn" title="Start" :disabled="svc.status === 'active' || svc.status === 'timer-active'" @click="manageService(svc.name, 'start', svc.is_user)"><i class="fas fa-play"></i></button>
                                <button class="svc-btn" title="Stop" :disabled="svc.status === 'inactive' || svc.status === 'not-found'" @click="manageService(svc.name, 'stop', svc.is_user)"><i class="fas fa-square"></i></button>
                                <button class="svc-btn" title="Restart" :disabled="svc.status === 'not-found'" @click="manageService(svc.name, 'restart', svc.is_user)"><i class="fas fa-sync"></i></button>
                            </div>
                        </div>
                        <div class="data-row" style="border:none; padding:0; align-items: center;">
                            <span class="badge" :class="{'badge-success': svc.status==='active' || svc.status==='timer-active','badge-warning': svc.status==='inactive','badge-danger': svc.status==='failed' || svc.status==='not-found'}" x-text="svc.status === 'timer-active' ? 'active (timer)' : svc.status"></span>
                            <span style="font-size: 0.8rem; color: var(--text-muted);" x-show="svc.memory" x-text="'Mem: ' + svc.memory"></span>
                        </div>
                    </div>
                </template>
            </div>
        </div>

        <div class="module-card" data-id="card-logs" x-show="visibleCards.logs" style="grid-column: 1 / -1;">
            <div class="module-header" style="justify-content: space-between;">
                <div style="display: flex; align-items: center; gap: 0.75rem;">
                    <i class="fas fa-terminal icon-main"></i> System Logs
                </div>
                <select class="theme-select" style="font-size: 0.85rem; padding: 0.2rem;" x-model="selectedLog" @change="fetchLogData()">
                    <option value="syserr">System Errors (journalctl)</option>
                    <option value="action">Dashboard Action Log</option>
                    <option value="backup">NAS Backup Log</option>
                </select>
            </div>
            <div class="module-body">
                <pre style="background: rgba(0,0,0,0.3); padding: 1rem; border-radius: 0.5rem; font-size: 0.8rem; font-family: 'Fira Code', monospace; color: var(--text-muted); white-space: pre-wrap; overflow-y: auto; max-height: 250px;" x-text="logContent"></pre>
            </div>
        </div>

        <div class="module-card" data-id="card-actions" x-show="visibleCards.actions">
            <div class="module-header"><i class="fas fa-bolt icon-main"></i> Quick Actions<i class="fas fa-grip-lines drag-handle"></i></div>
            <div class="module-body action-grid">
                <button class="btn btn-primary" :disabled="runningScript" @click="runScript('backup')"><i class="fas fa-database"></i> Force NAS Backup</button>
                <button class="btn" :disabled="runningScript" @click="runScript('verify')"><i class="fas fa-check-double"></i> Verify Backups</button>
                <button class="btn" :disabled="runningScript" @click="runScript('organize')"><i class="fas fa-folder-open"></i> Organize Downloads</button>
                <button class="btn" :disabled="runningScript" @click="runScript('diskcheck')"><i class="fas fa-broom"></i> Run Disk Cleanup</button>
                <button class="btn" :disabled="runningScript" @click="runScript('speedtest')"><i class="fas fa-tachometer-alt"></i> Network Speed Test</button>
            </div>
        </div>
    </div>

    <div x-show="showModal" class="modal-overlay" style="display: none;" @click.self="showModal=false">
        <div class="modal-box">
            <h2 style="margin-bottom: 1rem; font-size: 1.5rem;" x-text="modalTitle"></h2>
            <pre id="console-out" class="console-output" x-text="modalOutput"></pre>
            <div style="display: flex; justify-content: flex-end; margin-top: 1.5rem;">
                <button class="btn" @click="showModal=false" :disabled="runningScript">Close</button>
            </div>
        </div>
    </div>

    <div x-show="showSettings" class="modal-overlay" style="display: none;" @click.self="showSettings=false">
        <div class="modal-box" style="max-width: 700px;">
            <h2 style="margin-bottom: 1rem; font-size: 1.5rem;"><i class="fas fa-cog icon-main"></i> Dashboard Settings</h2>

            <p style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 0.5rem; font-weight: bold;">Toggle Visibility</p>
            <div class="settings-grid">
                <label class="setting-item"><input type="checkbox" x-model="visibleCards.core" @change="saveSettings()"> Core System</label>
                <label class="setting-item"><input type="checkbox" x-model="visibleCards.battery" @change="saveSettings()"> Power & Battery</label>
                <label class="setting-item"><input type="checkbox" x-model="visibleCards.bookmarks" @change="saveSettings()"> Bookmarks</label>
                <label class="setting-item"><input type="checkbox" x-model="visibleCards.pihole" @change="saveSettings()"> Pi-hole Stats</label>
                <label class="setting-item"><input type="checkbox" x-model="visibleCards.hw" @change="saveSettings()"> Hardware Profile</label>
                <label class="setting-item"><input type="checkbox" x-model="visibleCards.procs" @change="saveSettings()"> Resource Hogs</label>
                <label class="setting-item"><input type="checkbox" x-model="visibleCards.radar" @change="saveSettings()"> Network Radar</label>
                <label class="setting-item"><input type="checkbox" x-model="visibleCards.storage" @change="saveSettings()"> Storage Matrix</label>
                <label class="setting-item"><input type="checkbox" x-model="visibleCards.services" @change="saveSettings()"> Interactive Services</label>
                <label class="setting-item"><input type="checkbox" x-model="visibleCards.logs" @change="saveSettings()"> Multi-Log Viewer</label>
                <label class="setting-item"><input type="checkbox" x-model="visibleCards.actions" @change="saveSettings()"> Quick Actions</label>
            </div>

            <p style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 0.5rem; font-weight: bold; border-top: 1px solid var(--card-border); padding-top: 1rem;">Data Sources</p>
            <div style="display: flex; flex-direction: column; gap: 1rem;">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                    <div>
                        <label class="data-label" style="display:block; margin-bottom: 0.25rem;">Pi-hole IP/URL</label>
                        <input class="custom-input" type="text" x-model="piholeUrl" @change="saveSettings()" placeholder="dnsa01.vannieuwenhove.org">
                    </div>
                    <div>
                        <label class="data-label" style="display:block; margin-bottom: 0.25rem;">Pi-hole v6 App Password</label>
                        <input class="custom-input" type="password" x-model="piholeToken" @change="saveSettings()" placeholder="Paste Pi-hole Auth Token">
                    </div>
                </div>
                <div>
                    <label class="data-label" style="display:block; margin-bottom: 0.25rem;">Bookmarks (Format: Name | URL | FontAwesome-Icon)</label>
                    <textarea class="custom-input" x-model="bookmarksStr" @change="saveSettings()" style="height: 60px; font-family: monospace; font-size: 0.75rem; resize: vertical;"></textarea>
                </div>
                <div>
                    <label class="data-label" style="display:block; margin-bottom: 0.25rem;">Services (comma-separated)</label>
                    <input class="custom-input" type="text" x-model="monitoredServices" @change="saveSettings()">
                </div>
                <div>
                    <label class="data-label" style="display:block; margin-bottom: 0.25rem;">Radar IPs (comma-separated)</label>
                    <input class="custom-input" type="text" x-model="radarIps" @change="saveSettings()">
                </div>
            </div>

            <div style="display: flex; justify-content: flex-end; margin-top: 2rem;"><button class="btn btn-primary" @click="showSettings=false; refreshStats();">Save & Reload</button></div>
        </div>
    </div>

    <script>
        function dashboard() {
            // Default visibility
            const defaultCards = { core: true, battery: true, bookmarks: true, pihole: true, hw: true, procs: true, radar: true, storage: true, services: true, logs: true, actions: true };
            const savedCards = JSON.parse(localStorage.getItem('noba-visible-cards'));

            // Pre-populated bookmarks based on your browser tabs
            const defaultBookmarks = 'TrueNAS (vnnas)|http://vnnas.vannieuwenhove.org|fa-server, TrueNAS (vdhnas)|http://vdhnas.vannieuwenhove.org|fa-server, Pi-Hole|http://dnsa01.vannieuwenhove.org/admin|fa-shield-alt, Home Assistant|http://homeassistant.local:8123|fa-home, ROMM|http://romm.local|fa-gamepad, Prowlarr|http://localhost:9696|fa-search, ASUS Router|http://192.168.100.1|fa-network-wired';

            return {
                theme: localStorage.getItem('noba-theme') || 'default',
                visibleCards: savedCards || defaultCards,

                piholeUrl: localStorage.getItem('noba-pihole') || 'dnsa01.vannieuwenhove.org',
                piholeToken: localStorage.getItem('noba-pihole-token') || '',
                bookmarksStr: localStorage.getItem('noba-bookmarks') || defaultBookmarks,
                monitoredServices: localStorage.getItem('noba-services') || 'backup-to-nas.service, organize-downloads.service, sshd, podman, syncthing.service',
                radarIps: localStorage.getItem('noba-radar') || '192.168.100.1, 1.1.1.1, 8.8.8.8',

                timestamp: '--:--', uptime: '--', loadavg: '--', memory: '--', cpuTemp: '--', gpuTemp: '--',
                osName: '--', kernel: '--', hwCpu: '--', hwGpu: '--',
                defaultIp: '--', netRx: '0 B/s', netTx: '0 B/s', dnfUpdates: 0, flatpakUpdates: 0,
                battery: { percent: 0, status: 'Unknown' },
                disks: [], services: [], zfs: { pools: [] }, radar: [], topCpu: [], topMem: [], pihole: null,

                selectedLog: 'syserr', logContent: 'Loading...',
                showModal: false, showSettings: false, modalTitle: '', modalOutput: '', runningScript: false, refreshing: false,

                get cpuTempClass() { const t = parseInt(this.cpuTemp) || 0; return t > 80 ? 'badge-danger' : t > 60 ? 'badge-warning' : 'badge-neutral'; },
                get gpuTempClass() { const t = parseInt(this.gpuTemp) || 0; return t > 85 ? 'badge-danger' : t > 70 ? 'badge-warning' : 'badge-neutral'; },

                get parsedBookmarks() {
                    return this.bookmarksStr.split(',').map(b => {
                        const parts = b.split('|');
                        return { name: parts[0] ? parts[0].trim() : 'Link', url: parts[1] ? parts[1].trim() : '#', icon: parts[2] ? parts[2].trim() : 'fa-link' };
                    });
                },

                async init() {
                    this.initSortable();
                    await this.refreshStats();
                    this.fetchLogData();
                    setInterval(() => { this.refreshStats(); if(this.visibleCards.logs) this.fetchLogData(); }, 5000);
                },

                saveSettings() {
                    localStorage.setItem('noba-theme', this.theme);
                    localStorage.setItem('noba-pihole', this.piholeUrl);
                    localStorage.setItem('noba-pihole-token', this.piholeToken);
                    localStorage.setItem('noba-bookmarks', this.bookmarksStr);
                    localStorage.setItem('noba-services', this.monitoredServices);
                    localStorage.setItem('noba-radar', this.radarIps);
                    localStorage.setItem('noba-visible-cards', JSON.stringify(this.visibleCards));
                },

                initSortable() {
                    const grid = document.getElementById('sortable-dashboard');
                    Sortable.create(grid, {
                        animation: 200, easing: "cubic-bezier(1, 0, 0, 1)", handle: '.module-header', ghostClass: 'sortable-ghost', dragClass: 'sortable-drag',
                        forceFallback: true, fallbackOnBody: true, group: "noba-dashboard",
                        store: {
                            get: function (sortable) { const order = localStorage.getItem(sortable.options.group.name); return order ? order.split('|') : []; },
                            set: function (sortable) { localStorage.setItem(sortable.options.group.name, sortable.toArray().join('|')); }
                        }
                    });
                },

                async fetchLogData() {
                    try {
                        const res = await fetch('/api/log-viewer?type=' + this.selectedLog);
                        this.logContent = await res.text();
                    } catch(e) { this.logContent = "Error fetching logs."; }
                },

                async manageService(service, action, is_user) {
                    try {
                        await fetch('/api/service-control', {
                            method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ service, action, is_user })
                        });
                        setTimeout(() => this.refreshStats(), 1000);
                    } catch(e) { alert("Failed to control service: " + e); }
                },

                async refreshStats() {
                    if(this.refreshing) return;
                    this.refreshing = true;
                    try {
                        const url = `/api/stats?services=${encodeURIComponent(this.monitoredServices)}&radar=${encodeURIComponent(this.radarIps)}&pihole=${encodeURIComponent(this.piholeUrl)}&piholetok=${encodeURIComponent(this.piholeToken)}`;
                        const response = await fetch(url);
                        if (!response.ok) return;
                        const data = await response.json();
                        Object.assign(this, data);
                        this.pihole = data.pihole || null;
                    } catch (e) {} finally { this.refreshing = false; }
                },

                async runScript(script) {
                    if (this.runningScript) return;
                    this.runningScript = true;
                    this.modalTitle = `Executing: ${script}...`;
                    this.modalOutput = '>> Starting process...\n';
                    this.showModal = true;

                    const logInterval = setInterval(async () => {
                        try {
                            const res = await fetch('/api/action-log');
                            if(res.ok) {
                                this.modalOutput = await res.text();
                                const pre = document.getElementById('console-out');
                                if(pre) pre.scrollTop = pre.scrollHeight;
                            }
                        } catch(e) {}
                    }, 1000);

                    try {
                        const response = await fetch('/api/run', {
                            method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ script })
                        });
                        const result = await response.json();
                        this.modalTitle = result.success ? '✅ Process Successful' : '❌ Process Failed';
                    } catch (e) {
                        this.modalTitle = '❌ Connection Error';
                        this.modalOutput += '\n\nHTTP Error: ' + e.message;
                    } finally {
                        clearInterval(logInterval);
                        try {
                            const res = await fetch('/api/action-log');
                            if(res.ok) {
                                this.modalOutput = await res.text();
                                const pre = document.getElementById('console-out');
                                if(pre) pre.scrollTop = pre.scrollHeight;
                            }
                        } catch(e) {}
                        this.runningScript = false;
                        await this.refreshStats();
                    }
                }
            }
        }
    </script>
</body>
</html>
EOF

# -------------------------------------------------------------------
# Write server.py
# -------------------------------------------------------------------
cat > "$HTML_DIR/server.py" <<'EOF'
#!/usr/bin/env python3
import http.server, socketserver, json, subprocess, os, time, re, logging, glob, urllib.request
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get('PORT', 8080))
HOST = os.environ.get('HOST', '0.0.0.0')
SCRIPT_DIR = os.environ.get('NOBA_SCRIPT_DIR', os.path.expanduser("~/.local/bin"))
LOG_DIR = os.path.expanduser("~/.local/share")
CACHE_TTL = 30
PID_FILE = os.environ.get('PID_FILE', '/tmp/noba-web-server.pid')
ACTION_LOG = '/tmp/noba-action.log'
DEFAULT_PING = os.environ.get('NOBA_PING_TARGETS', '192.168.100.1,1.1.1.1,8.8.8.8').split(',')

logging.basicConfig(filename=os.path.join(LOG_DIR, 'noba-web-server.log'), level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
def strip_ansi(s): return ansi_escape.sub('', s)

def human_bytes(b):
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
        if b < 1024.0: return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} PiB"

def human_bps(b):
    for unit in ['B/s', 'KB/s', 'MB/s', 'GB/s']:
        if b < 1024.0: return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} TB/s"

class TTLCache:
    def __init__(self, ttl_seconds):
        self.ttl = ttl_seconds
        self.cache = {}
        self.timestamps = {}
    def get(self, key):
        if key in self.cache and datetime.now() - self.timestamps[key] < timedelta(seconds=self.ttl): return self.cache[key]
        return None
    def set(self, key, value):
        self.cache[key] = value
        self.timestamps[key] = datetime.now()
    def invalidate(self, key):
        if key in self.cache: del self.cache[key]

_cache = TTLCache(CACHE_TTL)
net_state = {'time': time.time(), 'rx': 0, 'tx': 0}

def run_cmd(cmd_list, timeout=2, cache_ttl=None, ignore_rc=False):
    cache_key = " ".join(cmd_list)
    if cache_ttl:
        cached = _cache.get(cache_key)
        if cached is not None: return cached
    try:
        res = subprocess.run(cmd_list, capture_output=True, text=True, timeout=timeout)
        out = res.stdout.strip() if (res.returncode == 0 or ignore_rc) else ""
        if cache_ttl and out: _cache.set(cache_key, out)
        return out
    except: return ""

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory='.', **kwargs)
    def log_message(self, format, *args): pass

    def get_service_status(self, svc):
        usr_out = run_cmd(['systemctl', '--user', 'show', '-p', 'ActiveState,LoadState', svc], timeout=1)
        ud = dict(l.split('=', 1) for l in usr_out.splitlines() if '=' in l)
        if ud.get('LoadState') not in [None, 'not-found']:
            state = ud.get('ActiveState', 'unknown')
            if state == 'inactive' and svc.endswith('.service'):
                t_out = run_cmd(['systemctl', '--user', 'show', '-p', 'ActiveState', svc.replace('.service', '.timer')], timeout=1)
                if 'ActiveState=active' in t_out: return 'timer-active', True
            return state, True

        sys_out = run_cmd(['systemctl', 'show', '-p', 'ActiveState,LoadState', svc], timeout=1)
        sd = dict(l.split('=', 1) for l in sys_out.splitlines() if '=' in l)
        if sd.get('LoadState') not in [None, 'not-found']:
            state = sd.get('ActiveState', 'unknown')
            if state == 'inactive' and svc.endswith('.service'):
                t_out = run_cmd(['systemctl', 'show', '-p', 'ActiveState', svc.replace('.service', '.timer')], timeout=1)
                if 'ActiveState=active' in t_out: return 'timer-active', False
            return state, False

        return 'not-found', False

    def get_battery(self):
        bats = glob.glob('/sys/class/power_supply/BAT*')
        if not bats: return {'percent': 0, 'status': 'Unknown (Desktop)'}
        try:
            with open(os.path.join(bats[0], 'capacity')) as f: pct = int(f.read().strip())
            with open(os.path.join(bats[0], 'status')) as f: stat = f.read().strip()
            return {'percent': pct, 'status': stat}
        except: return {'percent': 0, 'status': 'Error reading battery'}

    def get_top_procs(self, sort_by):
        out = run_cmd(['ps', 'ax', '--format', f'comm,{sort_by}', '--sort', f'-{sort_by}'], timeout=2)
        procs = []
        for line in out.splitlines()[1:6]:
            parts = line.strip().rsplit(' ', 1)
            if len(parts) == 2: procs.append({'name': parts[0][:15], 'val': parts[1].strip() + '%'})
        return procs

    def get_pihole_stats(self, pihole_url, pihole_token):
        if not pihole_url: return None
        url = pihole_url if pihole_url.startswith('http') else 'http://' + pihole_url
        url = url.rstrip('/').replace('/admin', '')

        # 1. Try Pi-hole v6 API
        try:
            headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
            if pihole_token: headers['sid'] = pihole_token
            req = urllib.request.Request(url + '/api/stats/summary', headers=headers)
            with urllib.request.urlopen(req, timeout=2) as response:
                data = json.loads(response.read().decode())
                q = data.get('queries', {}).get('total', 0)
                b = data.get('ads', {}).get('blocked', 0)
                p = data.get('ads', {}).get('percentage', 0.0)
                s = data.get('gravity', {}).get('status', 'unknown')
                return {'queries': f"{q:,}", 'blocked': f"{b:,}", 'percent': f"{p:.1f}", 'status': s}
        except: pass

        # 2. Fallback to Pi-hole v5 shim API
        try:
            api_url = url + '/admin/api.php?summaryRaw'
            if pihole_token: api_url += f"&auth={pihole_token}"
            req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=2) as response:
                data = json.loads(response.read().decode())
                return {
                    'queries': f"{data.get('dns_queries_today', 0):,}",
                    'blocked': f"{data.get('ads_blocked_today', 0):,}",
                    'percent': f"{data.get('ads_percentage_today', 0):.1f}",
                    'status': data.get('status', 'enabled')
                }
        except: return None

    def do_GET(self):
        parsed_path = urlparse(self.path)

        if parsed_path.path == '/api/stats':
            qs = parse_qs(parsed_path.query)
            stats = {'timestamp': time.strftime('%H:%M:%S')}

            try:
                with open('/etc/os-release') as f:
                    for line in f:
                        if line.startswith('PRETTY_NAME='): stats['osName'] = line.split('=')[1].strip().strip('"')
            except: stats['osName'] = "Linux"
            stats['kernel'] = run_cmd(['uname', '-r'], cache_ttl=3600)

            try:
                uptime_sec = float(open('/proc/uptime').read().split()[0])
                stats['uptime'] = f"{int(uptime_sec//3600)}h {int((uptime_sec%3600)//60)}m"
                stats['loadavg'] = open('/proc/loadavg').read().split()[0]
                with open('/proc/meminfo') as f: lines = f.readlines()
                mem_tot = next(int(l.split()[1])//1024 for l in lines if 'MemTotal' in l)
                mem_av = next(int(l.split()[1])//1024 for l in lines if 'MemAvailable' in l)
                stats['memory'] = f"{mem_av}MB / {mem_tot}MB"
            except: pass

            out = run_cmd(['sensors'], timeout=1, cache_ttl=5)
            match = re.search(r'(?:Tctl|Package id \d+|Core 0|temp1).*?\+?(\d+\.?\d*)[°C]', out)
            stats['cpuTemp'] = f"{int(float(match.group(1)))}°C" if match else "N/A"
            stats['battery'] = self.get_battery()

            hw_cpu = run_cmd(['bash', '-c', "lscpu | grep 'Model name' | head -n 1 | cut -d ':' -f 2 | xargs"], cache_ttl=3600)
            stats['hwCpu'] = hw_cpu if hw_cpu else "Unknown CPU"

            raw_gpu = run_cmd(['bash', '-c', "lspci | grep -i vga | cut -d ':' -f 3"], cache_ttl=3600)
            stats['hwGpu'] = raw_gpu.replace('\n', '<br>') if raw_gpu else "Unknown GPU"

            out = run_cmd(['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader'], cache_ttl=5)
            stats['gpuTemp'] = f"{out}°C" if out else "N/A"

            disks = []
            for line in run_cmd(['df', '-h'], cache_ttl=10).splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 5 and parts[0].startswith('/dev/'):
                    mount = parts[5] if len(parts) > 5 else ''
                    if mount.startswith(('/var/lib/snapd', '/boot')): continue
                    pct = parts[4].replace('%', '')
                    bc = 'danger' if int(pct) >= 90 else 'warning' if int(pct) >= 75 else 'accent'
                    disks.append({'mount': mount, 'percent': pct, 'barClass': bc})
            stats['disks'] = disks

            # Dynamic Services
            svc_query = qs.get('services', [''])[0]
            service_list = svc_query.split(',') if svc_query else os.environ.get('NOBA_WEB_SERVICES', '').split(',')
            services_status = []
            for svc in service_list:
                if not svc.strip(): continue
                status, is_user = self.get_service_status(svc.strip())
                services_status.append({'name': svc.strip(), 'status': status, 'is_user': is_user, 'memory': ''})
            stats['services'] = services_status

            # Dynamic Radar
            radar_query = qs.get('radar', [''])[0]
            ip_list = radar_query.split(',') if radar_query else DEFAULT_PING
            radar = []
            for ip in ip_list:
                if not ip.strip(): continue
                st = "Up" if run_cmd(['ping', '-c', '1', '-W', '1', ip.strip()], timeout=2) else "Down"
                radar.append({'ip': ip.strip(), 'status': st})
            stats['radar'] = radar

            stats['topCpu'] = self.get_top_procs('%cpu')
            stats['topMem'] = self.get_top_procs('%mem')

            # Pihole Integration
            pihole_url = qs.get('pihole', [''])[0]
            pihole_token = qs.get('piholetok', [''])[0]
            stats['pihole'] = self.get_pihole_stats(pihole_url, pihole_token) if pihole_url else None

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(stats).encode())

        elif parsed_path.path == '/api/log-viewer':
            qs = parse_qs(parsed_path.query)
            log_type = qs.get('type', ['syserr'])[0]
            text = "Log not found."
            if log_type == 'syserr': text = run_cmd(['journalctl', '-p', '3', '-n', '15', '--no-pager'], timeout=2)
            elif log_type == 'action':
                try:
                    with open(ACTION_LOG, 'r') as f: text = strip_ansi(f.read())
                except: text = "No recent actions run."
            elif log_type == 'backup':
                try:
                    with open(os.path.join(LOG_DIR, 'backup-to-nas.log'), 'r') as f:
                        lines = f.readlines()
                        text = strip_ansi("".join(lines[-20:]))
                except: text = "No backup log found."

            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(text.encode() if text else b"No content.")

        elif parsed_path.path == '/api/action-log':
            try:
                with open(ACTION_LOG, 'r') as f: text = strip_ansi(f.read())
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(text.encode())
            except:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Loading console stream...")

        elif parsed_path.path in ['/', '/index.html']:
            super().do_GET()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/api/run':
            try:
                content_len = int(self.headers.get('Content-Length', 0))
                data = json.loads(self.rfile.read(content_len))
                script = data.get('script', '')

                smap = {'backup': 'backup-to-nas.sh', 'verify': 'backup-verifier.sh', 'organize': 'organize-downloads.sh', 'diskcheck': 'disk-sentinel.sh', 'check_updates': 'noba-update.sh'}

                with open(ACTION_LOG, "w") as f: f.write(f">> Initiating {script} protocol...\n\n")

                if script == 'speedtest':
                    with open(ACTION_LOG, "a") as f:
                        p = subprocess.Popen(['speedtest-cli', '--simple'], stdout=f, stderr=subprocess.STDOUT)
                        p.wait(timeout=120)
                        succ = p.returncode == 0
                else:
                    sfile = os.path.join(SCRIPT_DIR, smap.get(script, ''))
                    if not os.path.exists(sfile):
                        with open(ACTION_LOG, "a") as f: f.write(f"\n[ERROR] Script missing: {sfile}")
                        succ = False
                    else:
                        with open(ACTION_LOG, "a") as f:
                            p = subprocess.Popen([sfile, '--verbose'], stdout=f, stderr=subprocess.STDOUT, cwd=SCRIPT_DIR)
                            p.wait(timeout=120)
                            succ = p.returncode == 0

                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': succ}).encode())
            except:
                self._send_json({'success': False})

        elif self.path == '/api/service-control':
            try:
                content_len = int(self.headers.get('Content-Length', 0))
                data = json.loads(self.rfile.read(content_len))
                svc = data.get('service')
                action = data.get('action')
                is_user = data.get('is_user', False)

                cmd = ['systemctl', '--user', action, svc] if is_user else ['sudo', '-n', 'systemctl', action, svc]
                subprocess.run(cmd, timeout=5)
                self._send_json({'success': True})
            except: self._send_json({'success': False})
        else:
            self.send_response(404)
            self.end_headers()

    def _send_json(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

if __name__ == '__main__':
    with open(PID_FILE, 'w') as f: f.write(str(os.getpid()))
    with socketserver.ThreadingTCPServer((HOST, PORT), Handler) as httpd:
        logging.info(f"Serving at http://{HOST}:{PORT}")
        httpd.serve_forever()
EOF

# -------------------------------------------------------------------
# Start the server
# -------------------------------------------------------------------
kill_server

export PORT HOST PID_FILE="$SERVER_PID_FILE" NOBA_SCRIPT_DIR="$SCRIPT_DIR"
cd "$HTML_DIR"
: > "$LOG_FILE"

nohup python3 server.py >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > "$SERVER_PID_FILE"

sleep 2
if kill -0 "$SERVER_PID" 2>/dev/null; then
    log_success "Web dashboard started on http://$HOST:$PORT"
else
    log_error "Server failed to start."
    exit 1
fi
