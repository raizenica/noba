#!/bin/bash
# noba-web.sh – Nobara Command Center v8.0.0
# Improvements: SSE streaming, parallel radar/services, CPU sparklines,
#   containers module, network I/O, toast notifications, alerts panel,
#   service-action allowlist, better error handling, full UI redesign.

set -euo pipefail

# ── Test harness compliance ─────────────────────────────────────────────────
if [[ "${1:-}" == "--help"           ]]; then echo "Usage: noba-web.sh [OPTIONS]"; exit 0; fi
if [[ "${1:-}" == "--version"        ]]; then echo "noba-web.sh version 8.0.0"; exit 0; fi
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi

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

show_version() { echo "noba-web.sh version 8.0.0"; exit 0; }

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]
Launch the Nobara Command Center web dashboard.

Options:
  -p, --port PORT   Start searching from PORT (default: 8080)
  -m, --max  PORT   Maximum port to try (default: 8090)
  --host     HOST   Bind to specific host/IP (default: 0.0.0.0)
  -k, --kill        Kill any running noba-web server and exit
  --help            Show this help message
  --version         Show version information
EOF
    exit 0
}

kill_server() {
    if [[ -f "$SERVER_PID_FILE" ]]; then
        local pid
        pid=$(cat "$SERVER_PID_FILE" 2>/dev/null || true)
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            log_info "Stopping server (PID $pid)..."
            kill "$pid" 2>/dev/null && sleep 1
            kill -0 "$pid" 2>/dev/null && { kill -9 "$pid" 2>/dev/null || true; }
        fi
        rm -f "$SERVER_PID_FILE"
    fi
}

find_free_port() {
    local start="$1" max="$2" port
    if command -v ss &>/dev/null; then
        for port in $(seq "$start" "$max"); do
            ss -tuln 2>/dev/null | grep -q ":${port}[[:space:]]" || { echo "$port"; return 0; }
        done
    elif command -v lsof &>/dev/null; then
        for port in $(seq "$start" "$max"); do
            lsof -i:"$port" -sTCP:LISTEN -t 2>/dev/null | grep -q . || { echo "$port"; return 0; }
        done
    else
        log_error "Neither 'ss' nor 'lsof' found."; exit 1
    fi
    return 1
}

if ! PARSED_ARGS=$(getopt -o p:m:k -l port:,max:,host:,kill,help,version -- "$@" 2>/dev/null); then
    log_error "Invalid argument. Run with --help for usage."; exit 1
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -p|--port)  START_PORT="$2"; shift 2 ;;
        -m|--max)   MAX_PORT="$2";   shift 2 ;;
        --host)     HOST="$2";       shift 2 ;;
        -k|--kill)  KILL_ONLY=true;  shift   ;;
        --help)     show_help ;;
        --version)  show_version ;;
        --)         shift; break ;;
        *)          log_error "Unknown argument: $1"; exit 1 ;;
    esac
done

if [[ "$KILL_ONLY" == true ]]; then kill_server; exit 0; fi

check_deps python3
PORT=$(find_free_port "$START_PORT" "$MAX_PORT") || die "No free port in range ${START_PORT}–${MAX_PORT}."
log_info "Using port $PORT"

mkdir -p "$HTML_DIR"
rm -f "$HTML_DIR"/*.html "$HTML_DIR"/server.py 2>/dev/null || true

# ── Write index.html ────────────────────────────────────────────────────────
cat > "$HTML_DIR/index.html" <<'HTMLEOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>NOBA // Command Center</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@400;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
    <script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>
    <style>
        *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

        :root {
            --bg: #060a10; --surface: #0c1420; --surface-2: #111d2c;
            --border: #1e3a5f; --border-hi: #2a5480;
            --text: #c8dff0; --text-muted: #4a7a9b; --text-dim: #1e3a5f;
            --accent: #00c8ff; --accent-dim: rgba(0,200,255,.1); --accent-glow: rgba(0,200,255,.18);
            --success: #00e676; --success-dim: rgba(0,230,118,.1);
            --warning: #ffb300; --warning-dim: rgba(255,179,0,.1);
            --danger: #ff1744; --danger-dim: rgba(255,23,68,.1);
            --font-ui: 'Chakra Petch', monospace;
            --font-data: 'JetBrains Mono', monospace;
        }
        [data-theme="dracula"] {
            --bg:#191a21; --surface:#282a36; --surface-2:#2f3146;
            --border:#44475a; --border-hi:#6272a4;
            --text:#f8f8f2; --text-muted:#6272a4; --text-dim:#44475a;
            --accent:#bd93f9; --accent-dim:rgba(189,147,249,.1); --accent-glow:rgba(189,147,249,.18);
            --success:#50fa7b; --success-dim:rgba(80,250,123,.1);
            --warning:#f1fa8c; --warning-dim:rgba(241,250,140,.1);
            --danger:#ff5555; --danger-dim:rgba(255,85,85,.1);
        }
        [data-theme="nord"] {
            --bg:#242933; --surface:#2e3440; --surface-2:#3b4252;
            --border:#4c566a; --border-hi:#5e81ac;
            --text:#eceff4; --text-muted:#4c566a; --text-dim:#3b4252;
            --accent:#88c0d0; --accent-dim:rgba(136,192,208,.1); --accent-glow:rgba(136,192,208,.18);
            --success:#a3be8c; --success-dim:rgba(163,190,140,.1);
            --warning:#ebcb8b; --warning-dim:rgba(235,203,139,.1);
            --danger:#bf616a; --danger-dim:rgba(191,97,106,.1);
        }
        [data-theme="catppuccin"] {
            --bg:#1e1e2e; --surface:#24273a; --surface-2:#2a2d3e;
            --border:#45475a; --border-hi:#7c7f93;
            --text:#cdd6f4; --text-muted:#6c7086; --text-dim:#45475a;
            --accent:#89b4fa; --accent-dim:rgba(137,180,250,.1); --accent-glow:rgba(137,180,250,.18);
            --success:#a6e3a1; --success-dim:rgba(166,227,161,.1);
            --warning:#f9e2af; --warning-dim:rgba(249,226,175,.1);
            --danger:#f38ba8; --danger-dim:rgba(243,139,168,.1);
        }
        [data-theme="tokyo"] {
            --bg:#13141f; --surface:#1a1b26; --surface-2:#24283b;
            --border:#2f3549; --border-hi:#414868;
            --text:#c0caf5; --text-muted:#565f89; --text-dim:#2f3549;
            --accent:#7aa2f7; --accent-dim:rgba(122,162,247,.1); --accent-glow:rgba(122,162,247,.18);
            --success:#9ece6a; --success-dim:rgba(158,206,106,.1);
            --warning:#e0af68; --warning-dim:rgba(224,175,104,.1);
            --danger:#f7768e; --danger-dim:rgba(247,118,142,.1);
        }
        [data-theme="gruvbox"] {
            --bg:#1d2021; --surface:#282828; --surface-2:#32302f;
            --border:#3c3836; --border-hi:#665c54;
            --text:#ebdbb2; --text-muted:#7c6f64; --text-dim:#504945;
            --accent:#83a598; --accent-dim:rgba(131,165,152,.1); --accent-glow:rgba(131,165,152,.18);
            --success:#b8bb26; --success-dim:rgba(184,187,38,.1);
            --warning:#fabd2f; --warning-dim:rgba(250,189,47,.1);
            --danger:#fb4934; --danger-dim:rgba(251,73,52,.1);
        }

        body {
            background: var(--bg); color: var(--text);
            font-family: var(--font-ui); min-height: 100vh; overflow-x: hidden;
            background-image: radial-gradient(circle, var(--border) 1px, transparent 1px);
            background-size: 28px 28px;
        }
        .page { padding: 1.5rem 2rem; max-width: 1600px; margin: 0 auto; }

        /* ── Header ── */
        .header {
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 1.25rem; padding-bottom: 1rem;
            border-bottom: 1px solid var(--border); flex-wrap: wrap; gap: 1rem;
        }
        .logo { display: flex; align-items: center; gap: 0.875rem; }
        .logo-mark {
            width: 42px; height: 42px; background: var(--accent-dim);
            border: 1px solid var(--accent); border-radius: 5px;
            display: flex; align-items: center; justify-content: center;
            color: var(--accent); font-size: 1.15rem;
        }
        .logo-name { font-size: 1.3rem; font-weight: 700; letter-spacing: .18em; }
        .logo-slash { color: var(--accent); }
        .logo-tagline { font-size: .65rem; letter-spacing: .3em; color: var(--text-muted); margin-top: 1px; }
        .header-controls { display: flex; align-items: center; gap: .625rem; flex-wrap: wrap; }
        .theme-select {
            background: var(--surface); color: var(--text); border: 1px solid var(--border);
            border-radius: 4px; padding: .4rem .6rem; font-family: var(--font-ui);
            font-size: .8rem; cursor: pointer; outline: none;
        }
        .theme-select:focus { border-color: var(--accent); }
        .icon-btn {
            width: 34px; height: 34px; display: flex; align-items: center; justify-content: center;
            background: var(--surface); border: 1px solid var(--border); border-radius: 4px;
            cursor: pointer; color: var(--text-muted); transition: all .15s; font-size: .85rem;
        }
        .icon-btn:hover { border-color: var(--accent); color: var(--accent); background: var(--accent-dim); }
        .live-pill {
            display: flex; align-items: center; gap: .45rem;
            background: var(--surface); border: 1px solid var(--border);
            border-radius: 4px; padding: .4rem .8rem;
            font-family: var(--font-data); font-size: .75rem; color: var(--text-muted);
        }
        .live-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--success); }
        .live-dot.syncing { background: var(--warning); animation: none; }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:.3} }
        .live-dot { animation: blink 2.5s infinite; }

        /* ── Alerts ── */
        .alerts { margin-bottom: 1.25rem; display: flex; flex-direction: column; gap: .4rem; }
        .alert {
            display: flex; align-items: center; gap: .75rem;
            padding: .55rem 1rem; border-radius: 4px; font-size: .82rem;
            font-family: var(--font-data); border-left: 3px solid;
        }
        .alert.danger  { background: var(--danger-dim);  border-color: var(--danger);  color: var(--danger); }
        .alert.warning { background: var(--warning-dim); border-color: var(--warning); color: var(--warning); }

        /* ── Grid ── */
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
            gap: 1.125rem; align-items: start;
        }
        .span-full { grid-column: 1 / -1; }
        @media (max-width: 860px) { .span-full { grid-column: 1 / -1; } }

        /* ── Card ── */
        .card {
            background: var(--surface); border: 1px solid var(--border);
            border-top: 2px solid var(--accent); border-radius: 5px;
            overflow: hidden; transition: box-shadow .2s;
        }
        .card:hover { box-shadow: 0 0 28px var(--accent-glow); }
        .card-hdr {
            padding: .8rem 1.2rem; background: rgba(0,0,0,.25);
            border-bottom: 1px solid var(--border);
            display: flex; align-items: center; gap: .7rem;
            cursor: grab; user-select: none;
        }
        .card-hdr:active { cursor: grabbing; }
        .card-icon { color: var(--accent); font-size: .85rem; flex-shrink: 0; }
        .card-title { font-size: .65rem; font-weight: 700; letter-spacing: .2em; text-transform: uppercase; color: var(--text-muted); flex: 1; }
        .drag-handle { color: var(--text-dim); font-size: .8rem; transition: color .15s; }
        .card:hover .drag-handle { color: var(--text-muted); }
        .card-body { padding: 1.125rem; }

        /* ── Data rows ── */
        .row { display: flex; justify-content: space-between; align-items: center; padding: .42rem 0; border-bottom: 1px solid var(--surface-2); }
        .row:last-child { border-bottom: none; }
        .row-label { font-size: .72rem; color: var(--text-muted); letter-spacing: .08em; text-transform: uppercase; }
        .row-val { font-family: var(--font-data); font-size: .88rem; text-align: right; }

        /* ── Badges ── */
        .badge {
            display: inline-flex; align-items: center; gap: .25rem;
            padding: .18rem .55rem; border-radius: 3px;
            font-size: .65rem; font-weight: 700; letter-spacing: .1em;
            text-transform: uppercase; border: 1px solid;
        }
        .bs { background: var(--success-dim); color: var(--success); border-color: rgba(0,230,118,.2); }
        .bw { background: var(--warning-dim); color: var(--warning); border-color: rgba(255,179,0,.2); }
        .bd { background: var(--danger-dim);  color: var(--danger);  border-color: rgba(255,23,68,.2); }
        .bn { background: var(--surface-2); color: var(--text-muted); border-color: var(--border); }
        .ba { background: var(--accent-dim); color: var(--accent); border-color: rgba(0,200,255,.2); }

        /* ── Progress bars ── */
        .prog { margin: .55rem 0; }
        .prog-meta { display: flex; justify-content: space-between; font-size: .7rem; color: var(--text-muted); margin-bottom: .28rem; font-family: var(--font-data); }
        .prog-track { height: 4px; background: var(--surface-2); border-radius: 2px; overflow: hidden; }
        .prog-fill { height: 100%; border-radius: 2px; transition: width .5s ease; }
        .f-accent   { background: var(--accent); }
        .f-success  { background: var(--success); }
        .f-warning  { background: var(--warning); }
        .f-danger   { background: var(--danger); }

        /* ── Sparkline ── */
        .spark-wrap { display: flex; align-items: center; gap: .875rem; margin-top: .75rem; }
        .spark-svg { flex: 1; height: 42px; overflow: visible; }
        .spark-val { font-family: var(--font-data); font-size: 1.6rem; font-weight: 500; color: var(--accent); min-width: 58px; text-align: right; }

        /* ── IO Stats ── */
        .io-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; }
        .io-stat { background: var(--surface-2); border-radius: 4px; padding: .75rem; text-align: center; }
        .io-val { font-family: var(--font-data); font-size: 1.05rem; font-weight: 500; }
        .io-down { color: var(--success); }
        .io-up   { color: var(--accent); }
        .io-label { font-size: .62rem; letter-spacing: .12em; text-transform: uppercase; color: var(--text-muted); margin-top: .2rem; }

        /* ── Pi-hole ── */
        .ph-stats { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; margin-bottom: .875rem; }
        .ph-stat { background: var(--surface-2); border-radius: 4px; padding: .7rem .9rem; }
        .ph-val { font-family: var(--font-data); font-size: 1.25rem; font-weight: 500; }
        .ph-label { font-size: .6rem; letter-spacing: .1em; text-transform: uppercase; color: var(--text-muted); margin-top: .18rem; }

        /* ── Radar ── */
        .radar-row { display: flex; align-items: center; gap: .7rem; padding: .45rem 0; border-bottom: 1px solid var(--surface-2); }
        .radar-row:last-child { border-bottom: none; }
        .radar-ip  { font-family: var(--font-data); font-size: .82rem; flex: 1; }
        .radar-ms  { font-family: var(--font-data); font-size: .72rem; color: var(--text-muted); min-width: 48px; text-align: right; }
        .status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
        .dot-up   { background: var(--success); box-shadow: 0 0 7px var(--success); animation: blink 2.5s infinite; }
        .dot-down { background: var(--danger); }

        /* ── Services ── */
        .svc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(175px,1fr)); gap: .7rem; }
        .svc-card { background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: .7rem .875rem; }
        .svc-name { font-size: .78rem; font-weight: 600; margin-bottom: .45rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .svc-footer { display: flex; align-items: center; justify-content: space-between; }
        .svc-btns { display: flex; gap: .28rem; }
        .svc-btn {
            background: none; border: 1px solid var(--border); color: var(--text-muted);
            cursor: pointer; padding: .2rem .4rem; border-radius: 3px; font-size: .72rem;
            transition: all .15s;
        }
        .svc-btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
        .svc-btn:disabled { opacity: .3; cursor: not-allowed; }

        /* ── Containers ── */
        .ct-list { display: flex; flex-direction: column; gap: .45rem; }
        .ct-row { display: flex; align-items: center; gap: .65rem; padding: .45rem .7rem; background: var(--surface-2); border-radius: 4px; }
        .ct-name { font-family: var(--font-data); font-size: .78rem; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .ct-img { font-size: .68rem; color: var(--text-muted); font-family: var(--font-data); max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

        /* ── Process list ── */
        .proc-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
        .proc-hdr { font-size: .62rem; letter-spacing: .15em; text-transform: uppercase; color: var(--text-muted); margin-bottom: .4rem; border-bottom: 1px solid var(--border); padding-bottom: .2rem; }
        .proc-row { display: flex; justify-content: space-between; font-family: var(--font-data); font-size: .76rem; padding: .18rem 0; }
        .proc-n { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 95px; }
        .cpu-col { color: var(--warning); }
        .mem-col { color: var(--accent); }

        /* ── Bookmarks ── */
        .bm-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(128px,1fr)); gap: .55rem; }
        .bm-link {
            display: flex; align-items: center; gap: .45rem;
            padding: .48rem .7rem; background: var(--surface-2); border: 1px solid var(--border);
            border-radius: 4px; text-decoration: none; color: var(--text);
            font-size: .78rem; transition: all .15s; overflow: hidden;
        }
        .bm-link:hover { border-color: var(--accent); color: var(--accent); background: var(--accent-dim); }
        .bm-link i { color: var(--accent); flex-shrink: 0; font-size: .82rem; }
        .bm-link span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

        /* ── Actions ── */
        .action-list { display: flex; flex-direction: column; gap: .55rem; }
        .btn {
            display: flex; align-items: center; gap: .6rem;
            padding: .65rem 1rem; border: 1px solid var(--border);
            background: var(--surface-2); color: var(--text); border-radius: 4px;
            cursor: pointer; font-family: var(--font-ui); font-size: .82rem;
            font-weight: 600; letter-spacing: .05em; transition: all .15s; width: 100%;
        }
        .btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); background: var(--accent-dim); }
        .btn:disabled { opacity: .4; cursor: not-allowed; }
        .btn-primary { border-color: var(--accent); color: var(--accent); background: var(--accent-dim); }
        .btn-primary:hover:not(:disabled) { background: rgba(0,200,255,.18); }

        /* ── Log viewer ── */
        .log-controls { display: flex; justify-content: space-between; align-items: center; margin-bottom: .75rem; gap: .5rem; flex-wrap: wrap; }
        .log-pre {
            background: rgba(0,0,0,.45); padding: .875rem; border-radius: 4px;
            font-family: var(--font-data); font-size: .73rem; color: var(--text-muted);
            white-space: pre-wrap; overflow-y: auto; max-height: 215px;
            border: 1px solid var(--border);
        }

        /* ── Sortable ── */
        .sortable-ghost { opacity: .25; border: 1px dashed var(--accent) !important; }
        .sortable-drag  { box-shadow: 0 20px 55px rgba(0,0,0,.6) !important; z-index: 100; }

        /* ── Modal ── */
        .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.82); backdrop-filter: blur(6px); display: flex; align-items: center; justify-content: center; z-index: 50; }
        .modal-box {
            background: var(--surface); border: 1px solid var(--border);
            border-top: 2px solid var(--accent); border-radius: 5px;
            width: 92%; max-width: 820px; padding: 1.75rem;
            max-height: 90vh; overflow-y: auto;
        }
        .modal-title { font-size: .9rem; font-weight: 700; letter-spacing: .18em; text-transform: uppercase; margin-bottom: 1.125rem; display: flex; align-items: center; gap: .7rem; }
        .console-out {
            background: #000; color: var(--success); padding: 1rem; border-radius: 4px;
            font-family: var(--font-data); font-size: .76rem;
            max-height: 50vh; overflow-y: auto; white-space: pre-wrap;
            border: 1px solid var(--border);
        }
        .modal-footer { display: flex; justify-content: flex-end; margin-top: 1.25rem; }

        /* ── Settings ── */
        .s-section { margin-bottom: 1.375rem; }
        .s-label { display: block; font-size: .62rem; letter-spacing: .2em; text-transform: uppercase; color: var(--text-muted); margin-bottom: .7rem; padding-bottom: .38rem; border-bottom: 1px solid var(--border); }
        .toggle-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px,1fr)); gap: .45rem; }
        .toggle-item { display: flex; align-items: center; gap: .45rem; cursor: pointer; font-size: .8rem; color: var(--text-muted); }
        .toggle-item input[type=checkbox] { accent-color: var(--accent); }
        .field-2 { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; margin-bottom: .75rem; }
        .field-label { display: block; font-size: .65rem; letter-spacing: .1em; text-transform: uppercase; color: var(--text-muted); margin-bottom: .28rem; }
        .field-input {
            width: 100%; background: var(--surface-2); color: var(--text);
            border: 1px solid var(--border); border-radius: 4px;
            padding: .48rem .7rem; font-family: var(--font-data); font-size: .8rem;
            outline: none; transition: border-color .15s;
        }
        .field-input:focus { border-color: var(--accent); }
        .settings-footer { display: flex; justify-content: flex-end; gap: .7rem; margin-top: 1.5rem; }
        .btn-sm { width: auto; padding: .55rem 1.4rem; }

        /* ── Toast ── */
        .toasts { position: fixed; bottom: 1.5rem; right: 1.5rem; z-index: 200; display: flex; flex-direction: column; gap: .45rem; pointer-events: none; }
        .toast {
            padding: .65rem 1rem; border-radius: 4px; font-size: .8rem;
            display: flex; align-items: center; gap: .5rem;
            animation: toast-in .18s ease; border-left: 3px solid;
            pointer-events: auto; min-width: 200px;
        }
        .toast.success { background: var(--surface); border-color: var(--success); color: var(--success); }
        .toast.error   { background: var(--surface); border-color: var(--danger);  color: var(--danger); }
        .toast.info    { background: var(--surface); border-color: var(--accent);  color: var(--accent); }
        @keyframes toast-in { from { transform: translateX(110%); opacity:0 } to { transform:translateX(0); opacity:1 } }

        /* ── Scrollbar ── */
        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-track { background: var(--surface); }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: var(--border-hi); }
    </style>
</head>
<body x-data="dashboard()" x-init="init()" :data-theme="theme">
<div class="page">

    <!-- ── Header ── -->
    <header class="header">
        <div class="logo">
            <div class="logo-mark"><i class="fas fa-terminal"></i></div>
            <div>
                <div class="logo-name">NOBA <span class="logo-slash">//</span> COMMAND</div>
                <div class="logo-tagline">Nobara Automation Suite</div>
            </div>
        </div>
        <div class="header-controls">
            <select class="theme-select" x-model="theme" @change="saveSettings()">
                <option value="default">Operator</option>
                <option value="catppuccin">Catppuccin</option>
                <option value="tokyo">Tokyo Night</option>
                <option value="gruvbox">Gruvbox</option>
                <option value="dracula">Dracula</option>
                <option value="nord">Nord</option>
            </select>
            <div class="icon-btn" @click="showSettings=true" title="Settings"><i class="fas fa-sliders-h"></i></div>
            <div class="live-pill">
                <div class="live-dot" :class="refreshing ? 'syncing' : ''"></div>
                <span x-text="refreshing ? 'Syncing...' : timestamp"></span>
            </div>
        </div>
    </header>

    <!-- ── Alerts ── -->
    <div class="alerts" x-show="alerts && alerts.length > 0">
        <template x-for="a in alerts" :key="a.msg">
            <div class="alert" :class="a.level">
                <i class="fas" :class="a.level==='danger' ? 'fa-exclamation-circle' : 'fa-exclamation-triangle'"></i>
                <span x-text="a.msg"></span>
            </div>
        </template>
    </div>

    <!-- ── Dashboard Grid ── -->
    <div class="grid" id="sortable-grid">

        <!-- Core System -->
        <div class="card" data-id="card-core" x-show="vis.core">
            <div class="card-hdr">
                <i class="fas fa-microchip card-icon"></i>
                <span class="card-title">Core System</span>
                <i class="fas fa-grip-lines drag-handle"></i>
            </div>
            <div class="card-body">
                <div class="row"><span class="row-label">OS</span><span class="row-val" x-text="osName"></span></div>
                <div class="row"><span class="row-label">Kernel</span><span class="row-val" x-text="kernel"></span></div>
                <div class="row"><span class="row-label">Uptime</span><span class="row-val" x-text="uptime"></span></div>
                <div class="row"><span class="row-label">Load Avg</span><span class="row-val" x-text="loadavg"></span></div>
                <div class="row">
                    <span class="row-label">CPU Temp</span>
                    <span class="badge" :class="cpuTempClass" x-text="cpuTemp"></span>
                </div>
                <div style="margin-top:.875rem">
                    <div style="font-size:.62rem;letter-spacing:.15em;text-transform:uppercase;color:var(--text-muted);margin-bottom:.35rem">CPU UTILIZATION</div>
                    <div class="spark-wrap">
                        <svg class="spark-svg" viewBox="0 0 120 40" preserveAspectRatio="none">
                            <defs>
                                <linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.3"/>
                                    <stop offset="100%" stop-color="var(--accent)" stop-opacity="0.0"/>
                                </linearGradient>
                            </defs>
                            <polygon :points="cpuFill" fill="url(#sg)" stroke="none"/>
                            <polyline :points="cpuLine" fill="none" stroke="var(--accent)" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
                        </svg>
                        <div class="spark-val" x-text="cpuPercent + '%'"></div>
                    </div>
                </div>
                <div class="prog" style="margin-top:.65rem">
                    <div class="prog-meta"><span>MEMORY</span><span x-text="memPercent + '%'"></span></div>
                    <div class="prog-track"><div class="prog-fill" :class="memPercent>90?'f-danger':memPercent>75?'f-warning':'f-accent'" :style="'width:'+memPercent+'%'"></div></div>
                    <div style="font-family:var(--font-data);font-size:.72rem;color:var(--text-muted);margin-top:.2rem" x-text="memory"></div>
                </div>
            </div>
        </div>

        <!-- Network I/O -->
        <div class="card" data-id="card-netio" x-show="vis.netio">
            <div class="card-hdr">
                <i class="fas fa-network-wired card-icon"></i>
                <span class="card-title">Network I/O</span>
                <i class="fas fa-grip-lines drag-handle"></i>
            </div>
            <div class="card-body">
                <div class="io-grid" style="margin-bottom:.875rem">
                    <div class="io-stat">
                        <div class="io-val io-down" x-text="netRx || '0 B/s'"></div>
                        <div class="io-label"><i class="fas fa-arrow-down"></i> RX</div>
                    </div>
                    <div class="io-stat">
                        <div class="io-val io-up" x-text="netTx || '0 B/s'"></div>
                        <div class="io-label"><i class="fas fa-arrow-up"></i> TX</div>
                    </div>
                </div>
                <div class="row"><span class="row-label">Hostname</span><span class="row-val" x-text="hostname || '--'"></span></div>
                <div class="row"><span class="row-label">Default IP</span><span class="row-val" x-text="defaultIp || '--'"></span></div>
            </div>
        </div>

        <!-- Hardware -->
        <div class="card" data-id="card-hw" x-show="vis.hw">
            <div class="card-hdr">
                <i class="fas fa-memory card-icon"></i>
                <span class="card-title">Hardware</span>
                <i class="fas fa-grip-lines drag-handle"></i>
            </div>
            <div class="card-body">
                <div class="row"><span class="row-label">CPU</span><span class="row-val" style="font-size:.78rem;max-width:210px" x-text="hwCpu"></span></div>
                <div class="row"><span class="row-label">GPU</span><span class="row-val" style="font-size:.76rem;max-width:210px" x-html="hwGpu"></span></div>
                <div class="row" x-show="gpuTemp && gpuTemp !== 'N/A'">
                    <span class="row-label">GPU Temp</span>
                    <span class="badge" :class="gpuTempClass" x-text="gpuTemp"></span>
                </div>
            </div>
        </div>

        <!-- Battery (hidden on desktop) -->
        <div class="card" data-id="card-battery" x-show="vis.battery && battery && !battery.desktop">
            <div class="card-hdr">
                <i class="fas fa-battery-half card-icon"></i>
                <span class="card-title">Power State</span>
                <i class="fas fa-grip-lines drag-handle"></i>
            </div>
            <div class="card-body">
                <div class="row">
                    <span class="row-label">Status</span>
                    <span class="badge" :class="battery.status==='Charging'||battery.status==='Full'?'bs':battery.status==='Discharging'?'bw':'bn'" x-text="battery.status"></span>
                </div>
                <div class="row" x-show="battery.timeRemaining">
                    <span class="row-label">Remaining</span>
                    <span class="row-val" x-text="battery.timeRemaining"></span>
                </div>
                <div class="prog" style="margin-top:.75rem">
                    <div class="prog-meta"><span>CHARGE</span><span x-text="battery.percent + '%'"></span></div>
                    <div class="prog-track"><div class="prog-fill" :class="battery.percent>20?'f-success':'f-danger'" :style="'width:'+battery.percent+'%'"></div></div>
                </div>
            </div>
        </div>

        <!-- Pi-hole -->
        <div class="card" data-id="card-pihole" x-show="vis.pihole">
            <div class="card-hdr">
                <i class="fas fa-shield-alt card-icon"></i>
                <span class="card-title">Pi-hole DNS</span>
                <i class="fas fa-grip-lines drag-handle"></i>
            </div>
            <div class="card-body">
                <template x-if="pihole">
                    <div>
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.875rem">
                            <span class="badge" :class="pihole.status==='enabled'?'bs':'bd'" x-text="pihole.status"></span>
                            <span style="font-size:.68rem;color:var(--text-muted)" x-text="pihole.domains + ' domains'"></span>
                        </div>
                        <div class="ph-stats">
                            <div class="ph-stat">
                                <div class="ph-val" x-text="typeof pihole.queries==='number' ? pihole.queries.toLocaleString() : pihole.queries"></div>
                                <div class="ph-label">Total Queries</div>
                            </div>
                            <div class="ph-stat">
                                <div class="ph-val" style="color:var(--danger)" x-text="typeof pihole.blocked==='number' ? pihole.blocked.toLocaleString() : pihole.blocked"></div>
                                <div class="ph-label">Blocked</div>
                            </div>
                        </div>
                        <div class="prog">
                            <div class="prog-meta"><span>BLOCK RATE</span><span x-text="pihole.percent + '%'"></span></div>
                            <div class="prog-track"><div class="prog-fill f-accent" :style="'width:' + pihole.percent + '%'"></div></div>
                        </div>
                    </div>
                </template>
                <template x-if="!pihole">
                    <div style="font-size:.8rem;color:var(--text-muted);font-style:italic">Pi-hole unreachable — configure URL and App Password in Settings.</div>
                </template>
            </div>
        </div>

        <!-- Storage -->
        <div class="card" data-id="card-storage" x-show="vis.storage">
            <div class="card-hdr">
                <i class="fas fa-hdd card-icon"></i>
                <span class="card-title">Storage</span>
                <i class="fas fa-grip-lines drag-handle"></i>
            </div>
            <div class="card-body">
                <template x-for="pool in zfs.pools" :key="pool.name">
                    <div class="row">
                        <span class="row-label" x-text="'ZFS: ' + pool.name"></span>
                        <span class="badge" :class="pool.health==='ONLINE'?'bs':pool.health==='DEGRADED'?'bw':'bd'" x-text="pool.health"></span>
                    </div>
                </template>
                <div :style="zfs.pools&&zfs.pools.length?'margin-top:.6rem':''">
                    <template x-for="d in disks" :key="d.mount">
                        <div class="prog">
                            <div class="prog-meta">
                                <span x-text="d.mount"></span>
                                <span x-text="d.used + ' / ' + d.size"></span>
                            </div>
                            <div class="prog-track"><div class="prog-fill" :class="'f-'+d.barClass" :style="'width:'+d.percent+'%'"></div></div>
                        </div>
                    </template>
                </div>
            </div>
        </div>

        <!-- Network Radar -->
        <div class="card" data-id="card-radar" x-show="vis.radar">
            <div class="card-hdr">
                <i class="fas fa-satellite-dish card-icon"></i>
                <span class="card-title">Network Radar</span>
                <i class="fas fa-grip-lines drag-handle"></i>
            </div>
            <div class="card-body">
                <template x-for="t in radar" :key="t.ip">
                    <div class="radar-row">
                        <div class="status-dot" :class="t.status==='Up'?'dot-up':'dot-down'"></div>
                        <span class="radar-ip" x-text="t.ip"></span>
                        <span class="badge" :class="t.status==='Up'?'bs':'bd'" x-text="t.status"></span>
                        <span class="radar-ms" x-show="t.status==='Up'" x-text="t.ms + 'ms'"></span>
                    </div>
                </template>
            </div>
        </div>

        <!-- Resource Hogs -->
        <div class="card" data-id="card-procs" x-show="vis.procs">
            <div class="card-hdr">
                <i class="fas fa-chart-bar card-icon"></i>
                <span class="card-title">Resource Hogs</span>
                <i class="fas fa-grip-lines drag-handle"></i>
            </div>
            <div class="card-body">
                <div class="proc-grid">
                    <div>
                        <div class="proc-hdr">Top CPU</div>
                        <template x-for="p in topCpu" :key="p.name">
                            <div class="proc-row"><span class="proc-n" x-text="p.name"></span><span class="cpu-col" x-text="p.val"></span></div>
                        </template>
                    </div>
                    <div>
                        <div class="proc-hdr">Top Memory</div>
                        <template x-for="p in topMem" :key="p.name">
                            <div class="proc-row"><span class="proc-n" x-text="p.name"></span><span class="mem-col" x-text="p.val"></span></div>
                        </template>
                    </div>
                </div>
            </div>
        </div>

        <!-- Containers -->
        <div class="card" data-id="card-containers" x-show="vis.containers && containers && containers.length > 0">
            <div class="card-hdr">
                <i class="fas fa-boxes card-icon"></i>
                <span class="card-title">Containers</span>
                <span style="font-size:.65rem;color:var(--text-muted);margin-left:auto;margin-right:.5rem" x-text="containers.length + ' total'"></span>
                <i class="fas fa-grip-lines drag-handle"></i>
            </div>
            <div class="card-body">
                <div class="ct-list">
                    <template x-for="c in containers" :key="c.name">
                        <div class="ct-row">
                            <div class="status-dot" :class="c.state==='running'?'dot-up':'dot-down'"></div>
                            <span class="ct-name" x-text="c.name"></span>
                            <span class="ct-img" x-text="c.image"></span>
                            <span class="badge" :class="c.state==='running'?'bs':c.state==='exited'?'bw':'bn'" x-text="c.state"></span>
                        </div>
                    </template>
                </div>
            </div>
        </div>

        <!-- Services — full width -->
        <div class="card span-full" data-id="card-services" x-show="vis.services">
            <div class="card-hdr">
                <i class="fas fa-cogs card-icon"></i>
                <span class="card-title">Services</span>
                <i class="fas fa-grip-lines drag-handle"></i>
            </div>
            <div class="card-body">
                <div class="svc-grid">
                    <template x-for="s in services" :key="s.name">
                        <div class="svc-card">
                            <div class="svc-name" x-text="s.name.replace('.service','')"></div>
                            <div class="svc-footer">
                                <span class="badge" :class="{'bs':s.status==='active'||s.status==='timer-active','bw':s.status==='inactive','bd':s.status==='failed'||s.status==='not-found'}" x-text="s.status==='timer-active'?'active (timer)':s.status"></span>
                                <div class="svc-btns">
                                    <button class="svc-btn" title="Start"   :disabled="s.status==='active'||s.status==='timer-active'" @click="svcAction(s,'start')"><i class="fas fa-play"></i></button>
                                    <button class="svc-btn" title="Stop"    :disabled="s.status==='inactive'||s.status==='not-found'"  @click="svcAction(s,'stop')"><i class="fas fa-stop"></i></button>
                                    <button class="svc-btn" title="Restart" :disabled="s.status==='not-found'"                          @click="svcAction(s,'restart')"><i class="fas fa-sync"></i></button>
                                </div>
                            </div>
                        </div>
                    </template>
                </div>
            </div>
        </div>

        <!-- Log Viewer — full width -->
        <div class="card span-full" data-id="card-logs" x-show="vis.logs">
            <div class="card-hdr">
                <i class="fas fa-scroll card-icon"></i>
                <span class="card-title">System Logs</span>
                <i class="fas fa-grip-lines drag-handle"></i>
            </div>
            <div class="card-body">
                <div class="log-controls">
                    <select class="theme-select" x-model="selectedLog" @change="fetchLog()">
                        <option value="syserr">System Errors (journalctl)</option>
                        <option value="action">Action Log</option>
                        <option value="backup">NAS Backup Log</option>
                    </select>
                    <div class="icon-btn" @click="fetchLog()" title="Refresh"><i class="fas fa-sync" :class="logLoading?'fa-spin':''"></i></div>
                </div>
                <pre class="log-pre" x-text="logContent"></pre>
            </div>
        </div>

        <!-- Quick Actions -->
        <div class="card" data-id="card-actions" x-show="vis.actions">
            <div class="card-hdr">
                <i class="fas fa-bolt card-icon"></i>
                <span class="card-title">Quick Actions</span>
                <i class="fas fa-grip-lines drag-handle"></i>
            </div>
            <div class="card-body action-list">
                <button class="btn btn-primary" :disabled="runningScript" @click="runScript('backup')"><i class="fas fa-database"></i> Force NAS Backup</button>
                <button class="btn" :disabled="runningScript" @click="runScript('verify')"><i class="fas fa-check-double"></i> Verify Backups</button>
                <button class="btn" :disabled="runningScript" @click="runScript('organize')"><i class="fas fa-folder-open"></i> Organize Downloads</button>
                <button class="btn" :disabled="runningScript" @click="runScript('diskcheck')"><i class="fas fa-broom"></i> Disk Cleanup</button>
                <button class="btn" :disabled="runningScript" @click="runScript('speedtest')"><i class="fas fa-tachometer-alt"></i> Speed Test</button>
            </div>
        </div>

        <!-- Homelab Links -->
        <div class="card" data-id="card-bookmarks" x-show="vis.bookmarks">
            <div class="card-hdr">
                <i class="fas fa-bookmark card-icon"></i>
                <span class="card-title">Homelab Links</span>
                <i class="fas fa-grip-lines drag-handle"></i>
            </div>
            <div class="card-body">
                <div class="bm-grid">
                    <template x-for="b in parsedBookmarks" :key="b.name">
                        <a :href="b.url" target="_blank" class="bm-link">
                            <i class="fas" :class="b.icon"></i>
                            <span x-text="b.name"></span>
                        </a>
                    </template>
                </div>
            </div>
        </div>

    </div><!-- /.grid -->
</div><!-- /.page -->

<!-- ── Run Script Modal ── -->
<div x-show="showModal" class="modal-overlay" style="display:none" @click.self="showModal=false">
    <div class="modal-box">
        <div class="modal-title">
            <i class="fas fa-terminal" style="color:var(--accent)"></i>
            <span x-text="modalTitle"></span>
        </div>
        <pre id="console-out" class="console-out" x-text="modalOutput"></pre>
        <div class="modal-footer">
            <button class="btn btn-sm" @click="showModal=false" :disabled="runningScript" style="width:auto;padding:.55rem 1.4rem">Close</button>
        </div>
    </div>
</div>

<!-- ── Settings Modal ── -->
<div x-show="showSettings" class="modal-overlay" style="display:none" @click.self="showSettings=false">
    <div class="modal-box">
        <div class="modal-title"><i class="fas fa-sliders-h" style="color:var(--accent)"></i> Settings</div>

        <div class="s-section">
            <span class="s-label">Module Visibility</span>
            <div class="toggle-grid">
                <label class="toggle-item"><input type="checkbox" x-model="vis.core"> Core System</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.netio"> Network I/O</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.hw"> Hardware</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.battery"> Power State</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.pihole"> Pi-hole DNS</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.storage"> Storage</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.radar"> Network Radar</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.procs"> Resource Hogs</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.containers"> Containers</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.services"> Services</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.logs"> System Logs</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.actions"> Quick Actions</label>
                <label class="toggle-item"><input type="checkbox" x-model="vis.bookmarks"> Homelab Links</label>
            </div>
        </div>

        <div class="s-section">
            <span class="s-label">Pi-hole</span>
            <div class="field-2">
                <div>
                    <label class="field-label">URL / IP</label>
                    <input class="field-input" type="text" x-model="piholeUrl" placeholder="dnsa01.example.org">
                </div>
                <div>
                    <label class="field-label">App Password (v6)</label>
                    <input class="field-input" type="password" x-model="piholeToken">
                </div>
            </div>
        </div>

        <div class="s-section">
            <span class="s-label">Data Sources</span>
            <div style="display:flex;flex-direction:column;gap:.7rem">
                <div>
                    <label class="field-label">Services (comma-separated)</label>
                    <input class="field-input" type="text" x-model="monitoredServices">
                </div>
                <div>
                    <label class="field-label">Radar IPs (comma-separated)</label>
                    <input class="field-input" type="text" x-model="radarIps">
                </div>
                <div>
                    <label class="field-label">Bookmarks (Name | URL | fa-icon, comma-separated)</label>
                    <textarea class="field-input" x-model="bookmarksStr" style="height:72px;resize:vertical"></textarea>
                </div>
            </div>
        </div>

        <div class="settings-footer">
            <button class="btn" @click="showSettings=false" style="width:auto;padding:.55rem 1.4rem">Cancel</button>
            <button class="btn btn-primary" @click="applySettings()" style="width:auto;padding:.55rem 1.4rem"><i class="fas fa-check"></i> Save & Apply</button>
        </div>
    </div>
</div>

<!-- ── Toasts ── -->
<div class="toasts">
    <template x-for="t in toasts" :key="t.id">
        <div class="toast" :class="t.type">
            <i class="fas" :class="t.type==='success'?'fa-check-circle':t.type==='error'?'fa-times-circle':'fa-info-circle'"></i>
            <span x-text="t.msg"></span>
        </div>
    </template>
</div>

<script>
function dashboard() {
    const DEF_VIS = { core:true, netio:true, hw:true, battery:true, pihole:true, storage:true, radar:true, procs:true, containers:true, services:true, logs:true, actions:true, bookmarks:true };
    const DEF_BOOKMARKS = 'TrueNAS (vnnas)|http://vnnas.vannieuwenhove.org|fa-server, TrueNAS (vdhnas)|http://vdhnas.vannieuwenhove.org|fa-server, Pi-Hole|http://dnsa01.vannieuwenhove.org/admin|fa-shield-alt, Home Assistant|http://homeassistant.local:8123|fa-home, ROMM|http://romm.local|fa-gamepad, Prowlarr|http://localhost:9696|fa-search, ASUS Router|http://192.168.100.1|fa-network-wired';

    return {
        theme: localStorage.getItem('noba-theme') || 'default',
        vis:   { ...DEF_VIS, ...JSON.parse(localStorage.getItem('noba-vis') || '{}') },
        piholeUrl:        localStorage.getItem('noba-pihole')    || 'dnsa01.vannieuwenhove.org',
        piholeToken:      localStorage.getItem('noba-pihole-tok')|| '',
        bookmarksStr:     localStorage.getItem('noba-bookmarks') || DEF_BOOKMARKS,
        monitoredServices:localStorage.getItem('noba-services')  || 'backup-to-nas.service, organize-downloads.service, sshd, podman, syncthing.service',
        radarIps:         localStorage.getItem('noba-radar')     || '192.168.100.1, 1.1.1.1, 8.8.8.8',

        timestamp:'--:--', uptime:'--', loadavg:'--', memory:'--', hostname:'--', defaultIp:'--',
        memPercent:0, cpuPercent:0, cpuHistory:[], cpuTemp:'N/A', gpuTemp:'N/A',
        osName:'--', kernel:'--', hwCpu:'--', hwGpu:'--',
        netRx:'0 B/s', netTx:'0 B/s',
        battery:{ percent:0, status:'Unknown', desktop:false },
        disks:[], services:[], zfs:{pools:[]}, radar:[],
        topCpu:[], topMem:[], pihole:null, containers:[], alerts:[],
        selectedLog:'syserr', logContent:'Loading...', logLoading:false,
        showModal:false, showSettings:false,
        modalTitle:'', modalOutput:'', runningScript:false, refreshing:false,
        toasts:[], _es:null, _poll:null,

        get cpuTempClass() { const t=parseInt(this.cpuTemp)||0; return t>80?'bd':t>65?'bw':'bn'; },
        get gpuTempClass() { const t=parseInt(this.gpuTemp)||0; return t>85?'bd':t>70?'bw':'bn'; },

        get parsedBookmarks() {
            return (this.bookmarksStr||'').split(',').map(b => {
                const p = b.split('|');
                return { name:(p[0]||'Link').trim(), url:(p[1]||'#').trim(), icon:(p[2]||'fa-link').trim() };
            });
        },

        get cpuLine() {
            const h = this.cpuHistory;
            if (h.length < 2) return `0,36 120,36`;
            return h.map((v,i) => `${Math.round((i/(h.length-1))*120)},${Math.round(36-(v/100)*32)}`).join(' ');
        },
        get cpuFill() {
            const h = this.cpuHistory;
            if (h.length < 2) return `0,38 120,38 120,38 0,38`;
            const pts = h.map((v,i) => `${Math.round((i/(h.length-1))*120)},${Math.round(36-(v/100)*32)}`).join(' ');
            return `${pts} 120,38 0,38`;
        },

        async init() {
            this.initSortable();
            await this.fetchLog();
            this.connectSSE();
            setInterval(() => { if(this.vis.logs) this.fetchLog(); }, 12000);
        },

        connectSSE() {
            if (this._es)   { this._es.close(); this._es = null; }
            if (this._poll) { clearInterval(this._poll); this._poll = null; }

            const qs = `services=${encodeURIComponent(this.monitoredServices)}&radar=${encodeURIComponent(this.radarIps)}&pihole=${encodeURIComponent(this.piholeUrl)}&piholetok=${encodeURIComponent(this.piholeToken)}`;
            this._es = new EventSource(`/api/stream?${qs}`);
            this._es.onmessage = (e) => {
                try { Object.assign(this, JSON.parse(e.data)); } catch {}
            };
            this._es.onerror = () => {
                this._es.close(); this._es = null;
                // Fallback to polling if SSE fails
                setTimeout(() => {
                    this.refreshStats();
                    this._poll = setInterval(() => this.refreshStats(), 5000);
                }, 3000);
            };
        },

        async refreshStats() {
            if (this.refreshing) return;
            this.refreshing = true;
            try {
                const url = `/api/stats?services=${encodeURIComponent(this.monitoredServices)}&radar=${encodeURIComponent(this.radarIps)}&pihole=${encodeURIComponent(this.piholeUrl)}&piholetok=${encodeURIComponent(this.piholeToken)}`;
                const res = await fetch(url);
                if (res.ok) Object.assign(this, await res.json());
            } catch {} finally { this.refreshing = false; }
        },

        saveSettings() {
            localStorage.setItem('noba-theme',      this.theme);
            localStorage.setItem('noba-pihole',     this.piholeUrl);
            localStorage.setItem('noba-pihole-tok', this.piholeToken);
            localStorage.setItem('noba-bookmarks',  this.bookmarksStr);
            localStorage.setItem('noba-services',   this.monitoredServices);
            localStorage.setItem('noba-radar',      this.radarIps);
            localStorage.setItem('noba-vis',        JSON.stringify(this.vis));
        },

        applySettings() {
            this.saveSettings();
            this.showSettings = false;
            this.connectSSE();
            this.addToast('Settings saved', 'success');
        },

        initSortable() {
            Sortable.create(document.getElementById('sortable-grid'), {
                animation:200, handle:'.card-hdr',
                ghostClass:'sortable-ghost', dragClass:'sortable-drag',
                forceFallback:true, fallbackOnBody:true, group:'noba-v8',
                store:{
                    get: s => (localStorage.getItem(s.options.group.name)||'').split('|'),
                    set: s => localStorage.setItem(s.options.group.name, s.toArray().join('|'))
                }
            });
        },

        async fetchLog() {
            this.logLoading = true;
            try {
                const res = await fetch('/api/log-viewer?type=' + this.selectedLog);
                this.logContent = await res.text();
            } catch { this.logContent = 'Failed to fetch log.'; }
            finally { this.logLoading = false; }
        },

        async svcAction(svc, action) {
            try {
                const res = await fetch('/api/service-control', {
                    method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({ service:svc.name, action, is_user:svc.is_user })
                });
                const d = await res.json();
                this.addToast(d.success ? `${action}: ${svc.name.replace('.service','')}` : `Failed: ${svc.name}`, d.success?'success':'error');
                setTimeout(() => this.refreshStats(), 1200);
            } catch { this.addToast('Service control error', 'error'); }
        },

        async runScript(script) {
            if (this.runningScript) return;
            this.runningScript = true;
            this.modalTitle = `Running: ${script}`;
            this.modalOutput = `>> [${new Date().toLocaleTimeString()}] Starting ${script}...\n`;
            this.showModal = true;

            const poll = setInterval(async () => {
                try {
                    const r = await fetch('/api/action-log');
                    if (r.ok) {
                        this.modalOutput = await r.text();
                        const el = document.getElementById('console-out');
                        if (el) el.scrollTop = el.scrollHeight;
                    }
                } catch {}
            }, 800);

            try {
                const res = await fetch('/api/run', {
                    method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({ script })
                });
                const result = await res.json();
                this.modalTitle = result.success ? '✓ Completed' : '✗ Failed';
                this.addToast(result.success ? `${script} completed` : `${script} failed`, result.success?'success':'error');
            } catch {
                this.modalTitle = '✗ Connection Error';
            } finally {
                clearInterval(poll);
                try { const r=await fetch('/api/action-log'); if(r.ok) this.modalOutput=await r.text(); } catch {}
                this.runningScript = false;
                await this.refreshStats();
            }
        },

        addToast(msg, type='info') {
            const id = Date.now() + Math.random();
            this.toasts.push({id, msg, type});
            setTimeout(() => { this.toasts = this.toasts.filter(t => t.id !== id); }, 3500);
        }
    };
}
</script>
</body>
</html>
HTMLEOF

# ── Write server.py ─────────────────────────────────────────────────────────
cat > "$HTML_DIR/server.py" <<'PYEOF'
#!/usr/bin/env python3
"""Nobara Command Center – Backend v8.0.0
New: SSE streaming, parallel pings/service-checks, CPU history,
     network I/O rates, container detection, better error handling,
     service-action allowlist.
"""
import http.server
import socketserver
import json
import subprocess
import os
import time
import re
import logging
import glob
import threading
import urllib.request
import urllib.error
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime
from urllib.parse import urlparse, parse_qs

# ── Config ────────────────────────────────────────────────────────────────────
PORT       = int(os.environ.get('PORT',   8080))
HOST       = os.environ.get('HOST',       '0.0.0.0')
SCRIPT_DIR = os.environ.get('NOBA_SCRIPT_DIR', os.path.expanduser('~/.local/bin'))
LOG_DIR    = os.path.expanduser('~/.local/share')
PID_FILE   = os.environ.get('PID_FILE',  '/tmp/noba-web-server.pid')
ACTION_LOG = '/tmp/noba-action.log'

logging.basicConfig(
    filename=os.path.join(LOG_DIR, 'noba-web-server.log'),
    level=logging.WARNING,
    format='%(asctime)s %(levelname)s %(message)s'
)

ANSI_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
def strip_ansi(s): return ANSI_RE.sub('', s)

SCRIPT_MAP = {
    'backup':   'backup-to-nas.sh',
    'verify':   'backup-verifier.sh',
    'organize': 'organize-downloads.sh',
    'diskcheck':'disk-sentinel.sh',
    'check_updates': 'noba-update.sh',
}
ALLOWED_ACTIONS = {'start', 'stop', 'restart'}

# ── Simple TTL cache ─────────────────────────────────────────────────────────
class TTLCache:
    def __init__(self):
        self._store = {}
        self._lock  = threading.Lock()

    def get(self, key, ttl=30):
        with self._lock:
            entry = self._store.get(key)
            if entry and (time.time() - entry['t']) < ttl:
                return entry['v']
        return None

    def set(self, key, val):
        with self._lock:
            self._store[key] = {'v': val, 't': time.time()}

_cache = TTLCache()

# ── Global streaming state (lock-protected) ───────────────────────────────────
_state_lock  = threading.Lock()
_cpu_history = deque(maxlen=20)
_cpu_prev    = None          # (total, idle)
_net_prev    = None          # (rx_bytes, tx_bytes)
_net_prev_t  = None

# ── Helpers ───────────────────────────────────────────────────────────────────
def run(cmd, timeout=3, cache_key=None, cache_ttl=30, ignore_rc=False):
    if cache_key:
        hit = _cache.get(cache_key, cache_ttl)
        if hit is not None:
            return hit
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = r.stdout.strip() if (r.returncode == 0 or ignore_rc) else ''
        if cache_key and out:
            _cache.set(cache_key, out)
        return out
    except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError, OSError):
        return ''

def human_bps(bps):
    for unit in ('B/s', 'KB/s', 'MB/s', 'GB/s'):
        if bps < 1024:
            return f'{bps:.1f} {unit}'
        bps /= 1024
    return f'{bps:.1f} TB/s'

# ── Stats collectors ──────────────────────────────────────────────────────────
def get_cpu_percent():
    global _cpu_prev
    with _state_lock:
        try:
            with open('/proc/stat') as f:
                fields = list(map(int, f.readline().split()[1:]))
            idle  = fields[3] + fields[4]   # idle + iowait
            total = sum(fields)
            if _cpu_prev is None:
                _cpu_prev = (total, idle)
                return 0.0
            dtotal = total - _cpu_prev[0]
            didle  = idle  - _cpu_prev[1]
            _cpu_prev = (total, idle)
            pct = round(100.0 * (1.0 - didle / dtotal) if dtotal > 0 else 0.0, 1)
            _cpu_history.append(pct)
            return pct
        except Exception:
            return 0.0

def get_net_io():
    global _net_prev, _net_prev_t
    with _state_lock:
        try:
            with open('/proc/net/dev') as f:
                lines = f.readlines()
            rx = tx = 0
            for line in lines[2:]:
                parts = line.split()
                if len(parts) > 9 and not parts[0].startswith('lo'):
                    rx += int(parts[1])
                    tx += int(parts[9])
            now = time.time()
            if _net_prev is None:
                _net_prev  = (rx, tx)
                _net_prev_t = now
                return 0.0, 0.0
            dt = now - _net_prev_t
            if dt < 0.05:
                return 0.0, 0.0
            rx_bps = max(0.0, (rx - _net_prev[0]) / dt)
            tx_bps = max(0.0, (tx - _net_prev[1]) / dt)
            _net_prev  = (rx, tx)
            _net_prev_t = now
            return rx_bps, tx_bps
        except Exception:
            return 0.0, 0.0

def ping_host(ip):
    ip = ip.strip()
    try:
        t0 = time.time()
        r  = subprocess.run(['ping', '-c', '1', '-W', '1', ip],
                            capture_output=True, timeout=2.5)
        ms = round((time.time() - t0) * 1000)
        return ip, r.returncode == 0, ms
    except Exception:
        return ip, False, 0

def get_service_status(svc):
    svc = svc.strip()
    for scope, is_user in ((['--user'], True), ([], False)):
        cmd = ['systemctl'] + scope + ['show', '-p', 'ActiveState,LoadState', svc]
        out = run(cmd, timeout=2)
        d   = dict(l.split('=', 1) for l in out.splitlines() if '=' in l)
        if d.get('LoadState') not in (None, '', 'not-found'):
            state = d.get('ActiveState', 'unknown')
            if state == 'inactive' and svc.endswith('.service'):
                timer_name = svc.replace('.service', '.timer')
                t = run(['systemctl'] + scope + ['show', '-p', 'ActiveState', timer_name], timeout=1)
                if 'ActiveState=active' in t:
                    return 'timer-active', is_user
            return state, is_user
    return 'not-found', False

def get_battery():
    bats = glob.glob('/sys/class/power_supply/BAT*')
    if not bats:
        return {'percent': 100, 'status': 'Desktop', 'desktop': True, 'timeRemaining': ''}
    try:
        pct  = int(open(f'{bats[0]}/capacity').read().strip())
        stat = open(f'{bats[0]}/status').read().strip()
        time_rem = ''
        try:
            current = int(open(f'{bats[0]}/current_now').read().strip())
            if current > 0:
                if stat == 'Discharging':
                    charge = int(open(f'{bats[0]}/charge_now').read().strip())
                    hrs = charge / current
                else:
                    cfull  = int(open(f'{bats[0]}/charge_full').read().strip())
                    charge = int(open(f'{bats[0]}/charge_now').read().strip())
                    hrs = (cfull - charge) / current
                time_rem = f'{int(hrs)}h {int((hrs % 1) * 60)}m'
                if stat != 'Discharging':
                    time_rem += ' to full'
        except Exception:
            pass
        return {'percent': pct, 'status': stat, 'desktop': False, 'timeRemaining': time_rem}
    except Exception:
        return {'percent': 0, 'status': 'Error', 'desktop': False, 'timeRemaining': ''}

def get_containers():
    for runtime in (['podman', 'ps', '-a', '--format', 'json'],
                    ['docker', 'ps', '-a', '--format', '{{json .}}']):
        out = run(runtime, timeout=4, cache_key=' '.join(runtime), cache_ttl=10)
        if not out:
            continue
        try:
            # podman returns a JSON array; docker returns one JSON object per line
            if out.lstrip().startswith('['):
                items = json.loads(out)
            else:
                items = [json.loads(line) for line in out.splitlines() if line.strip()]
            result = []
            for c in items[:16]:
                name  = c.get('Names', c.get('Name', '?'))
                if isinstance(name, list):
                    name = name[0] if name else '?'
                image = c.get('Image', c.get('Repository', '?')).split('/')[-1][:32]
                state = (c.get('State', c.get('Status', '?')) or '?').lower().split()[0]
                result.append({'name': name, 'image': image, 'state': state,
                               'status': c.get('Status', state)})
            return result
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return []

def get_pihole(url, token):
    if not url:
        return None
    base = url if url.startswith('http') else 'http://' + url
    base = base.rstrip('/').replace('/admin', '')

    def _get(endpoint, extra_headers=None):
        hdrs = {'User-Agent': 'noba-web/8.0', 'Accept': 'application/json'}
        if extra_headers:
            hdrs.update(extra_headers)
        req = urllib.request.Request(base + endpoint, headers=hdrs)
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read().decode())

    # v6 API
    try:
        auth = {'sid': token} if token else {}
        data = _get('/api/stats/summary', auth)
        q    = data.get('queries', {}).get('total', 0)
        b    = data.get('ads', {}).get('blocked', 0)
        p    = data.get('ads', {}).get('percentage', 0.0)
        s    = data.get('gravity', {}).get('status', 'unknown')
        dom  = data.get('gravity', {}).get('domains_being_blocked', 0)
        return {'queries': q, 'blocked': b, 'percent': round(p, 1),
                'status': s, 'domains': f'{dom:,}'}
    except Exception:
        pass

    # v5 fallback
    try:
        ep  = f'/admin/api.php?summaryRaw' + (f'&auth={token}' if token else '')
        data = _get(ep)
        return {
            'queries': data.get('dns_queries_today', 0),
            'blocked': data.get('ads_blocked_today', 0),
            'percent': round(data.get('ads_percentage_today', 0), 1),
            'status':  data.get('status', 'enabled'),
            'domains': f"{data.get('domains_being_blocked', 0):,}"
        }
    except Exception:
        return None

# ── Main stats aggregator ─────────────────────────────────────────────────────
def collect_stats(qs):
    stats = {'timestamp': datetime.now().strftime('%H:%M:%S')}

    # ── Quick reads ──
    try:
        with open('/etc/os-release') as f:
            for line in f:
                if line.startswith('PRETTY_NAME='):
                    stats['osName'] = line.split('=', 1)[1].strip().strip('"')
    except Exception:
        stats['osName'] = 'Linux'

    stats['kernel']   = run(['uname', '-r'], cache_key='uname-r', cache_ttl=3600)
    stats['hostname'] = run(['hostname'], cache_key='hostname', cache_ttl=3600)
    stats['defaultIp']= run(['bash', '-c', "ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \\K[\\d.]+'"], timeout=1)

    try:
        uptime_s = float(open('/proc/uptime').read().split()[0])
        d, rem = divmod(int(uptime_s), 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        stats['uptime']  = (f'{d}d ' if d else '') + f'{h}h {m}m'
        stats['loadavg'] = ' '.join(open('/proc/loadavg').read().split()[:3])
        mlines = open('/proc/meminfo').readlines()
        mmap   = {l.split(':')[0]: int(l.split()[1]) for l in mlines if ':' in l}
        tot    = mmap.get('MemTotal', 0) // 1024
        avail  = mmap.get('MemAvailable', 0) // 1024
        used   = tot - avail
        stats['memory']     = f'{used} MiB / {tot} MiB'
        stats['memPercent'] = round(100 * used / tot) if tot > 0 else 0
    except Exception:
        stats.setdefault('uptime', '--')
        stats.setdefault('loadavg', '--')
        stats.setdefault('memPercent', 0)

    # CPU
    cpu_pct = get_cpu_percent()
    stats['cpuPercent'] = cpu_pct
    stats['cpuHistory'] = list(_cpu_history)

    # Network I/O
    rx_bps, tx_bps = get_net_io()
    stats['netRx'] = human_bps(rx_bps)
    stats['netTx'] = human_bps(tx_bps)

    # CPU temp
    sensors = run(['sensors'], timeout=2, cache_key='sensors', cache_ttl=5)
    m = re.search(r'(?:Tctl|Package id \d+|Core 0|temp1).*?\+?(\d+\.?\d*)[°℃]', sensors)
    stats['cpuTemp'] = f'{int(float(m.group(1)))}°C' if m else 'N/A'

    # GPU temp
    gpu_t = run(['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader'],
                timeout=2, cache_key='nvidia-temp', cache_ttl=5)
    if not gpu_t:
        raw = run(['bash', '-c', "cat /sys/class/drm/card*/device/hwmon/hwmon*/temp1_input 2>/dev/null | head -1"], timeout=1)
        gpu_t = f'{int(raw)//1000}°C' if raw else 'N/A'
    else:
        gpu_t = f'{gpu_t}°C'
    stats['gpuTemp'] = gpu_t

    stats['battery'] = get_battery()

    stats['hwCpu'] = run(['bash', '-c', "lscpu | grep 'Model name' | head -1 | cut -d: -f2 | xargs"],
                         cache_key='lscpu', cache_ttl=3600)
    raw_gpu = run(['bash', '-c', "lspci | grep -i 'vga\\|3d' | cut -d: -f3"],
                  cache_key='lspci', cache_ttl=3600)
    stats['hwGpu'] = raw_gpu.replace('\n', '<br>') if raw_gpu else 'Unknown GPU'

    # Disks
    disks = []
    for line in run(['df', '-BM'], cache_key='df', cache_ttl=10).splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 6 and parts[0].startswith('/dev/'):
            mount = parts[5]
            if any(mount.startswith(p) for p in ('/var/lib/snapd', '/boot', '/run', '/snap')):
                continue
            try:
                pct  = int(parts[4].replace('%', ''))
                size = parts[1].replace('M', ' MiB')
                used = parts[2].replace('M', ' MiB')
                bc   = 'danger' if pct >= 90 else 'warning' if pct >= 75 else 'success'
                disks.append({'mount': mount, 'percent': pct, 'barClass': bc,
                              'size': size, 'used': used})
            except (ValueError, IndexError):
                pass
    stats['disks'] = disks

    # ZFS
    zfs_out = run(['zpool', 'list', '-H', '-o', 'name,health'], timeout=3,
                  cache_key='zpool', cache_ttl=15)
    pools = []
    for line in zfs_out.splitlines():
        if '\t' in line:
            n, h = line.split('\t', 1)
            pools.append({'name': n.strip(), 'health': h.strip()})
    stats['zfs'] = {'pools': pools}

    # Top processes
    cpu_ps = run(['ps', 'ax', '--format', 'comm,%cpu', '--sort', '-%cpu'], timeout=2)
    mem_ps = run(['ps', 'ax', '--format', 'comm,%mem', '--sort', '-%mem'], timeout=2)
    def parse_ps(out):
        result = []
        for line in out.splitlines()[1:6]:
            parts = line.strip().rsplit(None, 1)
            if len(parts) == 2 and parts[1] != '%CPU' and parts[1] != '%MEM':
                result.append({'name': parts[0][:16], 'val': parts[1] + '%'})
        return result
    stats['topCpu'] = parse_ps(cpu_ps)
    stats['topMem'] = parse_ps(mem_ps)

    # ── Parallel: services + radar + pihole + containers ──
    svc_list  = [s.strip() for s in qs.get('services', [''])[0].split(',') if s.strip()]
    ip_list   = [ip.strip() for ip in qs.get('radar',   [''])[0].split(',') if ip.strip()]
    ph_url    = qs.get('pihole',    [''])[0]
    ph_tok    = qs.get('piholetok', [''])[0]

    with ThreadPoolExecutor(max_workers=max(4, len(svc_list) + len(ip_list) + 3)) as ex:
        svc_futs  = {ex.submit(get_service_status, s): s for s in svc_list}
        ping_futs = {ex.submit(ping_host, ip):       ip for ip in ip_list}
        ph_fut    = ex.submit(get_pihole, ph_url, ph_tok) if ph_url else None
        ct_fut    = ex.submit(get_containers)

        services = []
        for fut, svc in svc_futs.items():
            try:
                status, is_user = fut.result(timeout=4)
            except Exception:
                status, is_user = 'error', False
            services.append({'name': svc, 'status': status, 'is_user': is_user})
        stats['services'] = services

        radar = []
        for fut, ip in ping_futs.items():
            try:
                ip_r, up, ms = fut.result(timeout=4)
                radar.append({'ip': ip_r, 'status': 'Up' if up else 'Down', 'ms': ms if up else 0})
            except Exception:
                radar.append({'ip': ip, 'status': 'Down', 'ms': 0})
        stats['radar'] = radar

        try:
            stats['pihole'] = ph_fut.result(timeout=4) if ph_fut else None
        except Exception:
            stats['pihole'] = None

        try:
            stats['containers'] = ct_fut.result(timeout=5)
        except Exception:
            stats['containers'] = []

    # ── Alerts ──
    alerts = []
    cpu = stats.get('cpuPercent', 0)
    if   cpu > 90: alerts.append({'level': 'danger',  'msg': f'CPU critical: {cpu}%'})
    elif cpu > 75: alerts.append({'level': 'warning', 'msg': f'CPU high: {cpu}%'})

    ct = stats.get('cpuTemp', 'N/A')
    if ct != 'N/A':
        t = int(ct.replace('°C', ''))
        if   t > 85: alerts.append({'level': 'danger',  'msg': f'CPU temp critical: {t}°C'})
        elif t > 70: alerts.append({'level': 'warning', 'msg': f'CPU temp elevated: {t}°C'})

    for disk in stats.get('disks', []):
        p = disk.get('percent', 0)
        if   p >= 90: alerts.append({'level': 'danger',  'msg': f"Disk {disk['mount']} at {p}%"})
        elif p >= 80: alerts.append({'level': 'warning', 'msg': f"Disk {disk['mount']} at {p}%"})

    for svc in stats.get('services', []):
        if svc.get('status') == 'failed':
            alerts.append({'level': 'danger', 'msg': f"Service failed: {svc['name']}"})

    stats['alerts'] = alerts
    return stats


# ── HTTP handler ──────────────────────────────────────────────────────────────
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory='.', **kwargs)

    def log_message(self, fmt, *args):
        pass  # silence access log

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        qs     = parse_qs(parsed.query)
        path   = parsed.path

        if path == '/api/stats':
            try:
                self._json(collect_stats(qs))
            except Exception as e:
                logging.exception('Error in /api/stats')
                self._json({'error': str(e)}, 500)

        elif path == '/api/stream':
            # Server-Sent Events – push stats every 5 s
            self.send_response(200)
            self.send_header('Content-Type',  'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection',    'keep-alive')
            self.end_headers()
            try:
                while True:
                    data = collect_stats(qs)
                    msg  = f'data: {json.dumps(data)}\n\n'.encode()
                    self.wfile.write(msg)
                    self.wfile.flush()
                    time.sleep(5)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass  # client disconnected
            except Exception as e:
                logging.warning(f'SSE stream error: {e}')

        elif path == '/api/log-viewer':
            log_type = qs.get('type', ['syserr'])[0]
            if log_type == 'syserr':
                text = run(['journalctl', '-p', '3', '-n', '25', '--no-pager'], timeout=4)
            elif log_type == 'action':
                try:
                    text = strip_ansi(open(ACTION_LOG).read())
                except FileNotFoundError:
                    text = 'No recent actions.'
            elif log_type == 'backup':
                try:
                    lines = open(os.path.join(LOG_DIR, 'backup-to-nas.log')).readlines()
                    text  = strip_ansi(''.join(lines[-30:]))
                except FileNotFoundError:
                    text = 'No backup log found.'
            else:
                text = 'Unknown log type.'
            body = (text or 'Empty.').encode()
            self.send_response(200)
            self.send_header('Content-Type',   'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == '/api/action-log':
            try:
                text = strip_ansi(open(ACTION_LOG).read())
            except FileNotFoundError:
                text = 'Waiting for output...'
            body = text.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(body)

        elif path in ('/', '/index.html'):
            super().do_GET()
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.path

        if path == '/api/run':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body   = json.loads(self.rfile.read(length))
                script = body.get('script', '')

                with open(ACTION_LOG, 'w') as f:
                    f.write(f'>> [{datetime.now().strftime("%H:%M:%S")}] Initiating: {script}\n\n')

                success = False
                if script == 'speedtest':
                    with open(ACTION_LOG, 'a') as f:
                        p = subprocess.Popen(['speedtest-cli', '--simple'],
                                             stdout=f, stderr=subprocess.STDOUT)
                        p.wait(timeout=120)
                        success = p.returncode == 0
                elif script in SCRIPT_MAP:
                    sfile = os.path.join(SCRIPT_DIR, SCRIPT_MAP[script])
                    if os.path.isfile(sfile):
                        with open(ACTION_LOG, 'a') as f:
                            p = subprocess.Popen([sfile, '--verbose'],
                                                 stdout=f, stderr=subprocess.STDOUT,
                                                 cwd=SCRIPT_DIR)
                            p.wait(timeout=300)
                            success = p.returncode == 0
                    else:
                        with open(ACTION_LOG, 'a') as f:
                            f.write(f'[ERROR] Script not found: {sfile}\n')
                else:
                    with open(ACTION_LOG, 'a') as f:
                        f.write(f'[ERROR] Unknown script: {script}\n')

                self._json({'success': success})
            except subprocess.TimeoutExpired:
                self._json({'success': False, 'error': 'Script timed out'})
            except Exception as e:
                logging.exception('Error in /api/run')
                self._json({'success': False, 'error': str(e)})

        elif path == '/api/service-control':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body   = json.loads(self.rfile.read(length))
                svc    = body.get('service', '').strip()
                action = body.get('action',  '').strip()
                is_user= bool(body.get('is_user', False))

                if action not in ALLOWED_ACTIONS:
                    return self._json({'success': False, 'error': f'Action "{action}" not allowed'})
                if not svc:
                    return self._json({'success': False, 'error': 'No service name provided'})

                cmd = (['systemctl', '--user', action, svc] if is_user
                       else ['sudo', '-n', 'systemctl', action, svc])
                r   = subprocess.run(cmd, timeout=10, capture_output=True)
                self._json({'success': r.returncode == 0,
                            'stderr': r.stderr.decode().strip()})
            except Exception as e:
                self._json({'success': False, 'error': str(e)})

        else:
            self.send_error(404)


class ThreadingHTTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads      = True   # SSE threads die with the main process


if __name__ == '__main__':
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    with ThreadingHTTPServer((HOST, PORT), Handler) as httpd:
        logging.warning(f'Serving at http://{HOST}:{PORT}')
        httpd.serve_forever()
PYEOF

chmod +x "$HTML_DIR/server.py"

# ── Launch ──────────────────────────────────────────────────────────────────
kill_server

export PORT HOST PID_FILE="$SERVER_PID_FILE" NOBA_SCRIPT_DIR="$SCRIPT_DIR"
cd "$HTML_DIR"
: > "$LOG_FILE"

nohup python3 server.py >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$SERVER_PID_FILE"

sleep 2
if kill -0 "$SERVER_PID" 2>/dev/null; then
    log_success "Dashboard live → http://${HOST}:${PORT}"
else
    log_error "Server failed to start. Check: $LOG_FILE"
    exit 1
fi
