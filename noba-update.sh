#!/bin/bash
# noba-update.sh – Pull latest scripts from git and optionally update system
# Version: 2.2.1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
REPO_DIR="$SCRIPT_DIR"
REMOTE="origin"
BRANCH="main"
UPDATE_SYSTEM=false
AUTO_YES=false
DRY_RUN=false

# -------------------------------------------------------------------
# Load user configuration
# -------------------------------------------------------------------
if command -v get_config &>/dev/null; then
    REMOTE="$(get_config ".update.remote" "$REMOTE")"
    BRANCH="$(get_config ".update.branch" "$BRANCH")"
    UPDATE_SYSTEM="$(get_config ".update.system.enabled" "$UPDATE_SYSTEM")"
    AUTO_YES="$(get_config ".update.system.auto_confirm" "$AUTO_YES")"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "noba-update.sh version 2.2.1"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Pull the latest version of all noba scripts from git and update the system.

Options:
  --repo DIR       Repository directory (default: $REPO_DIR)
  --remote NAME    Git remote name (default: $REMOTE)
  --branch NAME    Git branch name (default: $BRANCH)
  --system         Also run system updates (dnf and flatpak)
  --auto-yes       Auto-confirm package updates (non-interactive)
  --dry-run        Show what would be done without pulling
  --help           Show this help message
  --version        Show version information
EOF
    exit 0
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o '' -l repo:,remote:,branch:,system,auto-yes,dry-run,help,version -- "$@"); then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        --repo)      REPO_DIR="$2"; shift 2 ;;
        --remote)    REMOTE="$2"; shift 2 ;;
        --branch)    BRANCH="$2"; shift 2 ;;
        --system)    UPDATE_SYSTEM=true; shift ;;
        --auto-yes)  AUTO_YES=true; shift ;;
        --dry-run)   DRY_RUN=true; shift ;;
        --help)      show_help ;;
        --version)   show_version ;;
        --)          shift; break ;;
        *)           log_error "Internal error parsing arguments."; exit 1 ;;
    esac
done

# -------------------------------------------------------------------
# Main logic
# -------------------------------------------------------------------
check_deps git

log_info "Starting Nobara suite update..."

if [ ! -d "$REPO_DIR" ]; then
    die "Repository directory $REPO_DIR does not exist."
fi

cd "$REPO_DIR" || die "Cannot access $REPO_DIR"

if ! git rev-parse --git-dir > /dev/null 2>&1; then
    log_warn "$REPO_DIR is not a git repository. Skipping git operations."
else
    # Uncommitted changes check
    if ! git diff --quiet; then
        log_warn "You have uncommitted changes in the repository."
        if [ "$AUTO_YES" = false ] && [ "$DRY_RUN" = false ]; then
            if ! confirm "Pull changes and risk overwriting local edits?" "n"; then
                die "Update aborted by user."
            fi
        fi
    fi

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would pull $REMOTE/$BRANCH"
    else
        log_info "Fetching and pulling from $REMOTE/$BRANCH..."
        git fetch "$REMOTE" "$BRANCH" || true
        if ! git pull --ff-only "$REMOTE" "$BRANCH"; then
            log_warn "Pull failed (Conflicts exist). Manual merge required."
        fi
    fi
fi

# System Updates
if [ "$UPDATE_SYSTEM" = true ]; then
    if command -v dnf &>/dev/null; then
        log_info "Running DNF system update..."
        if [ "$DRY_RUN" = true ]; then
            log_info "DRY RUN: sudo dnf update"
        else
            if [ "$AUTO_YES" = true ]; then
                # -n forces non-interactive so it doesn't hang the web dashboard waiting for a password
                sudo -n dnf update -y || log_warn "DNF update requires a sudo password or failed."
            else
                sudo dnf update || log_warn "DNF update failed."
            fi
        fi
    fi

    if command -v flatpak &>/dev/null; then
        log_info "Running Flatpak update..."
        if [ "$DRY_RUN" = true ]; then
            log_info "DRY RUN: flatpak update"
        else
            if [ "$AUTO_YES" = true ]; then
                flatpak update -y || log_warn "Flatpak update failed."
            else
                flatpak update || log_warn "Flatpak update failed."
            fi
        fi
    fi
fi

if [ "$DRY_RUN" = false ]; then
    log_info "Ensuring script permissions..."
    find "$REPO_DIR" -maxdepth 1 -name "*.sh" -exec chmod +x {} \;
    log_success "Update complete."
fi
