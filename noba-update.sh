#!/bin/bash
# noba-update.sh – Pull latest scripts from git repository

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
REPO_DIR="${REPO_DIR:-$HOME/.local/bin}"
REMOTE="origin"
BRANCH="main"

# -------------------------------------------------------------------
# Load user configuration (if any)
# -------------------------------------------------------------------
load_config
if [ "$CONFIG_LOADED" = true ]; then
    REPO_DIR="$(get_config ".update.repo_dir" "$REPO_DIR")"
    REMOTE="$(get_config ".update.remote" "$REMOTE")"
    BRANCH="$(get_config ".update.branch" "$BRANCH")"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "noba-update.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Pull the latest version of all noba scripts from the git repository.

Options:
  --repo DIR        Repository directory (default: $REPO_DIR)
  --remote NAME     Git remote name (default: $REMOTE)
  --branch NAME     Git branch name (default: $BRANCH)
  --help            Show this help message
  --version         Show version information
EOF
    exit 0
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
PARSED_ARGS=$(getopt -o '' -l repo:,remote:,branch:,help,version -- "$@")
if ! some_command; then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        --repo)     REPO_DIR="$2"; shift 2 ;;
        --remote)   REMOTE="$2"; shift 2 ;;
        --branch)   BRANCH="$2"; shift 2 ;;
        --help)     show_help ;;
        --version)  show_version ;;
        --)         shift; break ;;
        *)          break ;;
    esac
done

# -------------------------------------------------------------------
# Main update logic
# -------------------------------------------------------------------
log_info "Updating noba scripts from git..."
log_debug "Repository: $REPO_DIR, remote: $REMOTE, branch: $BRANCH"

if [ ! -d "$REPO_DIR" ]; then
    log_error "Repository directory $REPO_DIR does not exist."
    exit 1
fi

cd "$REPO_DIR" || { log_error "Cannot cd to $REPO_DIR"; exit 1; }

# Check if it's a git repository
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    log_error "$REPO_DIR is not a git repository."
    exit 1
fi

# Fetch and pull
log_info "Fetching from $REMOTE/$BRANCH..."
if ! git fetch "$REMOTE" "$BRANCH"; then
    log_error "Git fetch failed."
    exit 1
fi

log_info "Pulling changes..."
if ! git pull "$REMOTE" "$BRANCH"; then
    log_error "Git pull failed."
    exit 1
fi

# Make all scripts executable
log_info "Making scripts executable..."
find "$REPO_DIR" -maxdepth 1 -name "*.sh" -exec chmod +x {} \;

log_info "Update completed successfully."

# Optional: run config-check to verify dependencies
if [ -x "$REPO_DIR/config-check.sh" ]; then
    log_info "Running config-check.sh to verify dependencies..."
    "$REPO_DIR/config-check.sh"
else
    log_warn "config-check.sh not found – skipping dependency check."
fi
