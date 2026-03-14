#!/bin/bash
# noba-web.sh – Ultimate dashboard with modular UI cards
# Version: 3.3.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
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
HOST="${HOST:-0.0.0.0}"
DEFAULT_SERVICES="backup-to-nas.service organize-downloads.service noba-web.service syncthing.service"

# -------------------------------------------------------------------
# Load user configuration
# -------------------------------------------------------------------
if command -v get_config &>/dev/null; then
    START_PORT="$(get_config ".web.start_port" "$START_PORT")"
    MAX_PORT="$(get_config ".web.max_port" "$MAX_PORT")"
    HOST="$(get_config ".web.host" "$HOST")"
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
    echo "noba-web.sh version 3.3.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Launch an interactive web dashboard for the Nobara Automation Suite.

Options:
  -p, --port PORT  Start searching from PORT (default: $START_PORT)
  -m, --max PORT   Maximum port to try (default: $MAX_PORT)
  --host HOST      Bind to specific host/IP (default: $HOST)
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

    if command -v ss &>/dev/null; then
        for port in $(seq "$start" "$max"); do
            if ! ss -tuln 2>/dev/null | grep -q ":$port[[:space:]]"; then
                echo "$port"
                return 0
            fi
        done
    elif command -v lsof &>/dev/null; then
        for port in $(seq "$start" "$max"); do
            if ! lsof -i:"$port" -sTCP:LISTEN -t 2>/dev/null | grep -q .; then
                echo "$port"
                return 0
            fi
        done
    else
        log_error "Neither 'ss' nor 'lsof' found – cannot check port availability."
        exit 1
    fi
    return 1
}

# -------------------------------------------------------------------
# Parse arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o p:m:k -l port:,max:,host:,kill,help,version -- "$@"); then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -p|--port)    START_PORT="$2"; shift 2 ;;
        -m|--max)     MAX_PORT="$2"; shift 2 ;;
        --host)       HOST="$2"; shift 2 ;;
        -k|--kill)    KILL_ONLY=true; shift ;;
        --help)       show_help ;;
        --version)    show_version ;;
        --)           shift; break ;;
        *)            log_error "Internal error parsing arguments."; exit 1 ;;
    esac
done

if [ "$KILL_ONLY" = true ]; then
    kill_server
    log_info "Server stopped (if any)."
    exit 0
fi

check_deps python3
if ! command -v ss &>/dev/null && ! command -v lsof &>/dev/null; then
    die "Need either 'ss' or 'lsof' to check port availability."
fi

PORT=$(find_free_port "$START_PORT" "$MAX_PORT") || {
    die "No free port found between $START_PORT and $MAX_PORT."
}
log_info "Using port $PORT"

# Create clean HTML directory
mkdir -p "$HTML_DIR"
rm -f "$HTML_DIR"/*.html "$HTML_DIR"/server.py "$HTML_DIR"/stats.json 2>/dev/null || true

# -------------------------------------------------------------------
# Write index.html (Modular UI Edition)
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
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        :root {
            --bg-dark: #0f172a;
            --bg-card: #1e293b;
            --card-border: #334155;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent: #3b82f6;
            --accent-hover: #2563eb;
            --success: #10b981;
            --success-bg: rgba(16, 185, 129, 0.15);
            --warning: #f59e0b;
            --warning-bg: rgba(245, 158, 11, 0.15);
            --danger: #ef4444;
            --danger-bg: rgba(239, 68, 68, 0.15);
        }
        body {
            background-color: var(--bg-dark);
            color: var(--text-main);
            font-family: 'Inter', system-ui, sans-serif;
            padding: 2rem;
            line-height: 1.5;
        }

        /* Header */
        .header-container { display: flex; justify-content: space-between; align-items: center; margin-bottom: 2rem; }
        h1 { font-size: 2rem; font-weight: 700; display: flex; align-items: center; gap: 0.75rem; }
        h1 i { color: var(--accent); }
        .status-pill { background: var(--card-border); padding: 0.5rem 1rem; border-radius: 2rem; font-size: 0.85rem; display: flex; align-items: center; gap: 0.5rem; }

        /* CSS Grid Layout for Modules */
        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 1.5rem;
            align-items: start;
        }

        /* Modular Card Styling */
        .module-card {
            background: var(--bg-card);
            border: 1px solid var(--card-border);
            border-radius: 1rem;
            overflow: hidden;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .module-card:hover { transform: translateY(-3px); box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.2); }

        .module-header {
            padding: 1.25rem 1.5rem;
            background: rgba(0,0,0,0.2);
            border-bottom: 1px solid var(--card-border);
            font-weight: 600;
            font-size: 1.1rem;
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }
        .module-header i { color: var(--accent); }
        .module-body { padding: 1.5rem; }

        /* Data Rows & Badges */
        .data-row { display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 0; border-bottom: 1px dashed rgba(255,255,255,0.05); }
        .data-row:last-child { border-bottom: none; }
        .data-label { color: var(--text-muted); font-size: 0.95rem; }
        .data-val { font-weight: 500; }

        .badge { padding: 0.25rem 0.75rem; border-radius: 1rem; font-size: 0.8rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
        .badge-success { background: var(--success-bg); color: var(--success); }
        .badge-warning { background: var(--warning-bg); color: var(--warning); }
        .badge-danger { background: var(--danger-bg); color: var(--danger); }
        .badge-neutral { background: var(--card-border); color: var(--text-muted); }

        /* Progress Bars */
        .progress-container { margin: 0.75rem 0; }
        .progress-header { display: flex; justify-content: space-between; font-size: 0.85rem; margin-bottom: 0.3rem; }
        .progress-track { width: 100%; height: 6px; background: var(--card-border); border-radius: 3px; overflow: hidden; }
        .progress-fill { height: 100%; border-radius: 3px; transition: width 0.4s ease; }

        /* Mini-Cards for Services/Docker */
        .mini-card-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; }
        .mini-card { background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.05); padding: 0.75rem; border-radius: 0.5rem; }
        .mini-card-title { font-size: 0.85rem; font-weight: 600; margin-bottom: 0.5rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

        /* Action Buttons */
        .action-grid { display: grid; grid-template-columns: 1fr; gap: 0.75rem; }
        .btn { padding: 0.75rem 1rem; border: none; border-radius: 0.5rem; font-weight: 600; font-size: 0.95rem; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 0.5rem; transition: all 0.2s; background: var(--card-border); color: var(--text-main); }
        .btn:hover:not(:disabled) { background: #475569; }
        .btn-primary { background: var(--accent); color: white; }
        .btn-primary:hover:not(:disabled) { background: var(--accent-hover); }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }

        /* Modal */
        .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.7); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; z-index: 50; }
        .modal-box { background: var(--bg-card); border: 1px solid var(--card-border); border-radius: 1rem; width: 90%; max-width: 800px; padding: 2rem; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5); }
        .modal-box h2 { margin-bottom: 1rem; font-size: 1.5rem; }
        pre.console-output { background: #000; color: #a3be8c; padding: 1rem; border-radius: 0.5rem; overflow-x: auto; max-height: 50vh; font-family: 'Fira Code', monospace; font-size: 0.85rem; }

        @media (max-width: 768px) { .dashboard-grid { grid-template-columns: 1fr; } .mini-card-grid { grid-template-columns: 1fr; } }
    </style>
</head>
<body x-data="dashboard()" x-init="init()">

    <div class="header-container">
        <h1><i class="fas fa-layer-group"></i> Nobara Automation</h1>
        <div class="status-pill">
            <i class="fas fa-sync-alt" :class="refreshing ? 'fa-spin' : ''"></i>
            <span x-text="refreshing ? 'Updating...' : 'Live: ' + timestamp"></span>
        </div>
    </div>

    <div class="dashboard-grid">

        <div class="module-card">
            <div class="module-header"><i class="fas fa-microchip"></i> Core System</div>
            <div class="module-body">
                <div class="data-row"><span class="data-label">Uptime</span><span class="data-val" x-text="uptime"></span></div>
                <div class="data-row"><span class="data-label">Load Average</span><span class="data-val" x-text="loadavg"></span></div>
                <div class="data-row"><span class="data-label">Memory</span><span class="data-val" x-text="memory"></span></div>
                <div class="data-row">
                    <span class="data-label">CPU Temp</span>
                    <span class="badge" :class="cpuTempClass" x-text="cpuTemp"></span>
                </div>
                <div class="data-row" x-show="gpuTemp !== 'N/A'">
                    <span class="data-label">GPU Temp</span>
                    <span class="badge" :class="gpuTempClass" x-text="gpuTemp"></span>
                </div>
            </div>
        </div>

        <div class="module-card">
            <div class="module-header"><i class="fas fa-hdd"></i> Storage Matrix</div>
            <div class="module-body">
                <template x-for="pool in zfs.pools" :key="pool.name">
                    <div class="data-row">
                        <span class="data-label" x-text="'ZFS: ' + pool.name"></span>
                        <span class="badge" :class="{'badge-success': pool.health==='ONLINE','badge-warning': pool.health==='DEGRADED','badge-danger': pool.health==='FAULTED'}" x-text="pool.health"></span>
                    </div>
                </template>

                <div style="margin-top: 1rem;"></div>

                <template x-for="disk in disks" :key="disk.mount">
                    <div class="progress-container">
                        <div class="progress-header">
                            <span x-text="disk.mount"></span>
                            <span x-text="disk.percent+'%'"></span>
                        </div>
                        <div class="progress-track">
                            <div class="progress-fill" :style="`width: ${disk.percent}%; background: var(--${disk.barClass});`"></div>
                        </div>
                    </div>
                </template>
            </div>
        </div>

        <div class="module-card" style="grid-column: 1 / -1;">
            <div class="module-header"><i class="fas fa-cogs"></i> Automation Services</div>
            <div class="module-body mini-card-grid" style="grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));">
                <template x-for="svc in services" :key="svc.name">
                    <div class="mini-card">
                        <div class="mini-card-title" x-text="svc.name.replace('.service','')"></div>
                        <div class="data-row" style="border:none; padding:0;">
                            <span class="badge" :class="{'badge-success': svc.status==='active','badge-warning': svc.status==='inactive','badge-danger': svc.status==='failed'}" x-text="svc.status"></span>
                            <span style="font-size: 0.8rem; color: var(--text-muted);" x-show="svc.memory" x-text="'CPU: ' + (svc.cpu || '0s') + ' | Mem: ' + svc.memory"></span>
                        </div>
                    </div>
                </template>
            </div>
        </div>

        <div class="module-card">
            <div class="module-header"><i class="fab fa-docker"></i> Docker Containers</div>
            <div class="module-body">
                <div class="data-row" style="margin-bottom: 0.5rem;">
                    <span class="data-label">Total Running</span>
                    <span class="data-val" x-text="dockerContainers.length"></span>
                </div>
                <div style="max-height: 200px; overflow-y: auto; padding-right: 0.5rem;">
                    <template x-for="container in dockerContainers">
                        <div style="font-size: 0.85rem; padding: 0.3rem 0; color: var(--text-muted); border-bottom: 1px solid rgba(255,255,255,0.05);" x-text="container"></div>
                    </template>
                </div>
            </div>
        </div>

        <div class="module-card">
            <div class="module-header"><i class="fas fa-bolt"></i> Quick Actions</div>
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
            <h2 x-text="modalTitle"></h2>
            <pre class="console-output" x-text="modalOutput"></pre>
            <div style="display: flex; justify-content: flex-end; margin-top: 1.5rem;">
                <button class="btn" @click="showModal=false" :disabled="runningScript">Close</button>
            </div>
        </div>
    </div>

    <script>
        function dashboard() {
            return {
                timestamp: '--:--', uptime: '--', loadavg: '--', memory: '--', cpuTemp: '--', gpuTemp: '--', gpuLoad: '--',
                disks: [], services: [], dockerContainers: [], zfs: { pools: [] },

                showModal: false, modalTitle: '', modalOutput: '', runningScript: false, refreshing: false,

                get cpuTempClass() { const t = parseInt(this.cpuTemp) || 0; return t > 80 ? 'badge-danger' : t > 60 ? 'badge-warning' : 'badge-neutral'; },
                get gpuTempClass() { const t = parseInt(this.gpuTemp) || 0; return t > 85 ? 'badge-danger' : t > 70 ? 'badge-warning' : 'badge-neutral'; },

                async init() {
                    await this.refreshStats();
                    setInterval(() => this.refreshStats(), 60000);
                },

                async refreshStats() {
                    if(this.refreshing) return;
                    this.refreshing = true;
                    try {
                        const response = await fetch('/api/stats');
                        if (!response.ok) return;
                        const data = await response.json();
                        Object.assign(this, data);
                    } catch (e) {
                        console.error('Stats fetch failed', e);
                    } finally {
                        this.refreshing = false;
                    }
                },

                async runScript(script) {
                    if (this.runningScript) return;
                    this.runningScript = true;
                    this.modalTitle = `Executing: ${script}...`;
                    this.modalOutput = '>> Starting process... Please wait.';
                    this.showModal = true;

                    try {
                        const response = await fetch('/api/run', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ script })
                        });
                        const result = await response.json();
                        this.modalOutput = result.output || '>> Process completed with no output.';
                        this.modalTitle = result.success ? '✅ Process Successful' : '❌ Process Failed';
                    } catch (e) {
                        this.modalOutput = '>> HTTP Error: ' + e.message;
                        this.modalTitle = '❌ Connection Error';
                    }
                    this.runningScript = false;
                    await this.refreshStats();
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
"""
Nobara Dashboard Server
Serves the modular dashboard and executes local scripts securely.
"""

import http.server
import socketserver
import json
import subprocess
import os
import time
import re
import logging
from datetime import datetime, timedelta

# -------------------- Configuration --------------------
PORT = int(os.environ.get('PORT', 8080))
HOST = os.environ.get('HOST', '0.0.0.0')
# Passed dynamically from Bash so Python always knows exactly where the scripts live
SCRIPT_DIR = os.environ.get('NOBA_SCRIPT_DIR', os.path.expanduser("~/.local/bin"))
LOG_DIR = os.path.expanduser("~/.local/share")
CACHE_TTL = 30
PID_FILE = os.environ.get('PID_FILE', '/tmp/noba-web-server.pid')

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
        if b < 1024.0: return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} PiB"

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

def run_cmd(cmd_list, timeout=2, cache_ttl=None):
    cache_key = " ".join(cmd_list)
    if cache_ttl:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

    try:
        res = subprocess.run(cmd_list, capture_output=True, text=True, timeout=timeout)
        out = res.stdout.strip() if res.returncode == 0 else ""
        if cache_ttl and out:
            _cache.set(cache_key, out)
        return out
    except Exception as e:
        logging.debug(f"Command failed: {cache_key} -> {e}")
        return ""

# -------------------- Threaded Server Class --------------------
class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

# -------------------- Handler class --------------------
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory='.', **kwargs)

    def log_message(self, format, *args):
        pass # Silence basic HTTP logs

    # ---------- System Stats ----------
    def get_zfs_pools(self):
        pools = []
        out = run_cmd(['zpool', 'list', '-H', '-o', 'name,health'], timeout=2, cache_ttl=10)
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2: pools.append({'name': parts[0], 'health': parts[1]})
        return pools

    def get_gpu_info(self):
        out = run_cmd(['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader'], timeout=1, cache_ttl=5)
        if out: return f"{out}°C", run_cmd(['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader'], timeout=1, cache_ttl=5)
        out = run_cmd(['rocm-smi', '--showtemp', '--json'], timeout=1, cache_ttl=5)
        if out:
            try:
                data = json.loads(out)
                for card in data.values():
                    if isinstance(card, dict):
                        for k, v in card.items():
                            if 'temperature' in k.lower(): return f"{float(v):.0f}°C", "N/A"
            except: pass
        return "N/A", "N/A"

    def get_docker_containers(self):
        out = run_cmd(['docker', 'ps', '--format', '{{.Names}} ({{.Status}})'], timeout=3, cache_ttl=10)
        return out.splitlines() if out else []

    def get_service_details(self, service):
        details = {}
        out = run_cmd(['systemctl', '--user', 'show', service], timeout=1, cache_ttl=10)
        for line in out.splitlines():
            if '=' in line:
                key, val = line.split('=', 1)
                if key == 'MemoryCurrent' and val != '0' and val.isdigit():
                    details['memory'] = human_bytes(int(val))
                elif key == 'CPUUsageNSec' and val != '0' and val.isdigit():
                    sec = int(val) / 1_000_000_000
                    details['cpu'] = f"{sec:.1f}s" if sec < 60 else f"{int(sec//60)}m{int(sec%60)}s"
        return details

    # ---------- GET /api/stats ----------
    def do_GET(self):
        if self.path == '/api/stats':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(self.get_stats()).encode())
        else:
            if self.path in ['/', '/index.html']:
                super().do_GET()
            else:
                self.send_error(404, "Not Found")

    # ---------- POST /api/run ----------
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
                    'cloudbackup': 'cloud-backup.sh',
                }

                if script == 'speedtest':
                    proc = subprocess.run(['speedtest-cli', '--simple'], capture_output=True, text=True, timeout=60)
                    output = proc.stdout + proc.stderr
                    success = proc.returncode == 0
                else:
                    script_file = os.path.join(SCRIPT_DIR, script_map.get(script, ''))
                    if not os.path.exists(script_file):
                        output = f"Script {script} not found at {script_file}"
                        success = False
                    else:
                        proc = subprocess.run([script_file, '--verbose'], capture_output=True, text=True, timeout=120, cwd=SCRIPT_DIR)
                        output = strip_ansi(proc.stdout + proc.stderr)
                        success = proc.returncode == 0

                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': success, 'output': output}).encode())
            except subprocess.TimeoutExpired:
                self._send_json({'success': False, 'output': 'Script execution timed out after 120s.'})
            except Exception as e:
                self._send_json({'success': False, 'output': f"Server Error: {str(e)}"})
        else:
            self.send_response(404)
            self.end_headers()

    def _send_json(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    # ---------- Main stats collector ----------
    def get_stats(self):
        stats = {'timestamp': time.strftime('%H:%M:%S')}

        try:
            uptime_sec = float(open('/proc/uptime').read().split()[0])
            stats['uptime'] = f"{int(uptime_sec//3600)}h {int((uptime_sec%3600)//60)}m"
        except: stats['uptime'] = 'N/A'

        try: stats['loadavg'] = open('/proc/loadavg').read().split()[0]
        except: stats['loadavg'] = 'N/A'

        try:
            with open('/proc/meminfo') as f:
                lines = f.readlines()
            mem_tot = next(int(l.split()[1])//1024 for l in lines if 'MemTotal' in l)
            mem_av = next(int(l.split()[1])//1024 for l in lines if 'MemAvailable' in l)
            stats['memory'] = f"{mem_av}MB / {mem_tot}MB"
        except: stats['memory'] = 'N/A'

        gpu_temp, gpu_load = self.get_gpu_info()
        stats['gpuTemp'], stats['gpuLoad'], stats['cpuTemp'] = gpu_temp, gpu_load, gpu_temp

        # Disk usage
        disks = []
        df_out = run_cmd(['df', '-h'], timeout=2, cache_ttl=10)
        for line in df_out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 5 and parts[0].startswith('/dev/'):
                mount = parts[5] if len(parts) > 5 else ''
                if mount.startswith(('/var/lib/snapd', '/boot')): continue
                pct = parts[4].replace('%', '')
                bar_class = 'danger' if int(pct) >= 90 else 'warning' if int(pct) >= 75 else 'accent'
                disks.append({'mount': mount, 'percent': pct, 'barClass': bar_class})
        stats['disks'] = disks

        # Services
        service_list = os.environ.get('NOBA_WEB_SERVICES', '').split(',')
        services_status = []
        for svc in service_list:
            if not svc.strip(): continue
            status = run_cmd(['systemctl', '--user', 'is-active', svc.strip()], timeout=1) or 'unknown'
            svc_info = {'name': svc.strip(), 'status': status}
            svc_info.update(self.get_service_details(svc.strip()))
            services_status.append(svc_info)
        stats['services'] = services_status

        stats['dockerContainers'] = self.get_docker_containers()
        stats['zfs'] = {'pools': self.get_zfs_pools()}

        return stats

# -------------------- Server setup --------------------
def run_server():
    with ThreadedTCPServer((HOST, PORT), Handler) as httpd:
        logging.info(f"Serving dashboard at http://{HOST}:{PORT}")
        print(f"Serving dashboard at http://{HOST}:{PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logging.info("Shutting down...")
            httpd.shutdown()

if __name__ == '__main__':
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
    run_server()
EOF

# -------------------------------------------------------------------
# Start the server
# -------------------------------------------------------------------
kill_server

export PORT
export HOST
export PID_FILE="$SERVER_PID_FILE"
# Crucial: Export the bash script directory so the python server knows where to find the other scripts
export NOBA_SCRIPT_DIR="$SCRIPT_DIR"

cd "$HTML_DIR"
: > "$LOG_FILE"

nohup python3 server.py >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > "$SERVER_PID_FILE"

sleep 2
if kill -0 "$SERVER_PID" 2>/dev/null; then
    log_success "Web dashboard started on http://$HOST:$PORT"
    log_info "Log file: $LOG_FILE"
    log_info "Use '$0 --kill' to stop the server."
else
    log_error "Server failed to start. Last 20 lines of log:"
    tail -20 "$LOG_FILE" >&2
    exit 1
fi
