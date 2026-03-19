#!/usr/bin/env bash
# noba-cli — Command-line interface for NOBA Command Center
# Usage: noba-cli <command> [args...]
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
NOBA_URL="${NOBA_URL:-http://localhost:8080}"
TOKEN_FILE="${HOME}/.config/noba/cli-token"
VERBOSE="${VERBOSE:-false}"

# ── Helpers ──────────────────────────────────────────────────────────────────
_log() { [[ "$VERBOSE" == "true" ]] && echo "[noba-cli] $*" >&2 || true; }

_get_token() {
    if [[ -f "$TOKEN_FILE" ]]; then
        cat "$TOKEN_FILE"
    else
        echo ""
    fi
}

_api() {
    local method="$1" path="$2"
    shift 2
    local token
    token=$(_get_token)
    local auth_header=""
    [[ -n "$token" ]] && auth_header="Authorization: Bearer $token"

    local url="${NOBA_URL}${path}"
    _log "$method $url"

    if [[ "$method" == "GET" ]]; then
        curl -sS -X GET "$url" \
            ${auth_header:+-H "$auth_header"} \
            -H "Accept: application/json" \
            "$@"
    else
        curl -sS -X "$method" "$url" \
            ${auth_header:+-H "$auth_header"} \
            -H "Content-Type: application/json" \
            -H "Accept: application/json" \
            "$@"
    fi
}

_json_val() {
    # Simple JSON value extractor (no jq dependency)
    python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('$1',''))" 2>/dev/null
}

# ── Commands ─────────────────────────────────────────────────────────────────
cmd_login() {
    local user="${1:-}" pass="${2:-}"
    if [[ -z "$user" ]]; then
        read -rp "Username: " user
    fi
    if [[ -z "$pass" ]]; then
        read -rsp "Password: " pass
        echo
    fi
    local resp
    resp=$(_api POST "/api/login" -d "{\"username\":\"$user\",\"password\":\"$pass\"}")
    local token
    token=$(echo "$resp" | _json_val token)
    if [[ -n "$token" ]]; then
        mkdir -p "$(dirname "$TOKEN_FILE")"
        echo -n "$token" > "$TOKEN_FILE"
        chmod 600 "$TOKEN_FILE"
        echo "Login successful. Token saved to $TOKEN_FILE"
    else
        echo "Login failed: $resp" >&2
        return 1
    fi
}

cmd_logout() {
    _api POST "/api/logout" > /dev/null 2>&1 || true
    rm -f "$TOKEN_FILE"
    echo "Logged out."
}

cmd_status() {
    _api GET "/api/health" | python3 -m json.tool 2>/dev/null || _api GET "/api/health"
}

cmd_stats() {
    _api GET "/api/stats" | python3 -m json.tool 2>/dev/null || _api GET "/api/stats"
}

cmd_services() {
    _api GET "/api/stats" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for s in d.get('services', []):
    status = s.get('status', '?')
    icon = '✓' if status == 'active' else '✗' if status == 'failed' else '?'
    print(f'  {icon} {s[\"name\"]:30s} {status}')
" 2>/dev/null
}

cmd_runs() {
    local limit="${1:-20}"
    _api GET "/api/runs?limit=$limit" | python3 -c "
import sys, json
from datetime import datetime
runs = json.load(sys.stdin)
for r in runs:
    ts = datetime.fromtimestamp(r.get('started_at', 0)).strftime('%Y-%m-%d %H:%M') if r.get('started_at') else '?'
    status = r.get('status', '?')
    trigger = r.get('trigger', '?')[:40]
    print(f'  {r[\"id\"]:>5d}  {ts}  {status:10s}  {trigger}')
" 2>/dev/null
}

cmd_run() {
    local script="${1:-}"
    shift || true
    local args="${*:-}"
    if [[ -z "$script" ]]; then
        echo "Usage: noba-cli run <script> [args...]" >&2
        return 1
    fi
    local body="{\"script\":\"$script\""
    [[ -n "$args" ]] && body+=",\"args\":\"$args\""
    body+="}"
    _api POST "/api/run" -d "$body" | python3 -m json.tool 2>/dev/null
}

cmd_automations() {
    _api GET "/api/automations" | python3 -c "
import sys, json
autos = json.load(sys.stdin)
for a in autos:
    enabled = '✓' if a.get('enabled') else '✗'
    schedule = a.get('schedule', '-') or '-'
    print(f'  {enabled} {a[\"id\"]:14s} {a[\"type\"]:10s} {schedule:15s} {a[\"name\"]}')
" 2>/dev/null
}

cmd_trigger() {
    local auto_id="${1:-}"
    if [[ -z "$auto_id" ]]; then
        echo "Usage: noba-cli trigger <automation_id>" >&2
        return 1
    fi
    _api POST "/api/automations/$auto_id/run" | python3 -m json.tool 2>/dev/null
}

cmd_audit() {
    local limit="${1:-20}"
    _api GET "/api/audit?limit=$limit" | python3 -c "
import sys, json
from datetime import datetime
rows = json.load(sys.stdin)
for r in rows:
    ts = datetime.fromtimestamp(r.get('time', 0)).strftime('%Y-%m-%d %H:%M')
    print(f'  {ts}  {r.get(\"username\", \"?\"):12s}  {r.get(\"action\", \"?\"):20s}  {r.get(\"details\", \"\")[:50]}')
" 2>/dev/null
}

cmd_smart() {
    _api GET "/api/smart" | python3 -c "
import sys, json
disks = json.load(sys.stdin)
for d in disks:
    risk = d.get('risk_score', 0)
    icon = '✓' if risk < 30 else '⚠' if risk < 70 else '✗'
    temp = d.get('temp_c', '?')
    print(f'  {icon} {d.get(\"device\", \"?\"):12s} {d.get(\"model\", \"?\"):30s} {temp}°C  risk={risk}')
" 2>/dev/null
}

cmd_help() {
    cat <<'HELP'
noba-cli — Command-line interface for NOBA Command Center

Usage: noba-cli <command> [args...]

Commands:
  login [user] [pass]     Authenticate and save token
  logout                  Clear saved token
  status                  Show server health
  stats                   Show full system stats (JSON)
  services                List monitored services
  runs [limit]            Show recent job runs
  run <script> [args]     Execute a script
  automations             List all automations
  trigger <auto_id>       Trigger an automation
  audit [limit]           Show audit log
  smart                   Show SMART disk health

Environment:
  NOBA_URL     Server URL (default: http://localhost:8080)
  VERBOSE      Set to "true" for debug output
HELP
}

# ── Main ─────────────────────────────────────────────────────────────────────
main() {
    local cmd="${1:-help}"
    shift || true
    case "$cmd" in
        login)       cmd_login "$@" ;;
        logout)      cmd_logout ;;
        status)      cmd_status ;;
        stats)       cmd_stats ;;
        services)    cmd_services ;;
        runs)        cmd_runs "$@" ;;
        run)         cmd_run "$@" ;;
        automations) cmd_automations ;;
        trigger)     cmd_trigger "$@" ;;
        audit)       cmd_audit "$@" ;;
        smart)       cmd_smart ;;
        help|--help|-h) cmd_help ;;
        *)
            echo "Unknown command: $cmd" >&2
            cmd_help >&2
            return 1
            ;;
    esac
}

main "$@"
