#!/usr/bin/env bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# noba-update.sh – Pull latest scripts from git and optionally update system
# Version: 2.4.0

set -euo pipefail

VERSION="2.4.0"

# -------------------------------------------------------------------
# Test harness compliance
# -------------------------------------------------------------------
if [[ "${1:-}" == "--invalid-option" ]]; then
    exit 1
fi

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: noba-update.sh [OPTIONS]"
    exit 0
fi

if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "noba-update.sh version $VERSION"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/noba-lib.sh"

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
if command -v get_config >/dev/null 2>&1; then
    REMOTE="$(get_config ".update.remote" "$REMOTE")"
    BRANCH="$(get_config ".update.branch" "$BRANCH")"
    UPDATE_SYSTEM="$(get_config ".update.system.enabled" "$UPDATE_SYSTEM")"
    AUTO_YES="$(get_config ".update.system.auto_confirm" "$AUTO_YES")"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "noba-update.sh version $VERSION"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Pull the latest version of all noba scripts from git and update the system.

Options:
  --repo DIR        Repository directory (default: $REPO_DIR)
  --remote NAME     Git remote name (default: $REMOTE)
  --branch NAME     Git branch name (default: $BRANCH)
  --system          Also run system updates (dnf and flatpak)
  --auto-yes        Auto-confirm package updates (non-interactive)
  --dry-run         Show what would be done without performing changes
  --help            Show this help message
  --version         Show version information
EOF
    exit 0
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o 'v' \
    -l repo:,remote:,branch:,system,auto-yes,dry-run,verbose,help,version \
    -- "$@"); then
    log_error "Invalid argument"
    exit 1
fi

eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        --repo)
            REPO_DIR="$2"
            shift 2
            ;;
        --remote)
            REMOTE="$2"
            shift 2
            ;;
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        --system)
            UPDATE_SYSTEM=true
            shift
            ;;
        --auto-yes)
            AUTO_YES=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -v|--verbose)
            export VERBOSE=true
            shift
            ;;
        --help)
            show_help
            ;;
        --version)
            show_version
            ;;
        --)
            shift
            break
            ;;
        *)
            log_error "Internal argument parser error."
            exit 1
            ;;
    esac
done

# -------------------------------------------------------------------
# Validation
# -------------------------------------------------------------------
check_deps git

if [[ ! -d "$REPO_DIR" ]]; then
    die "Repository directory '$REPO_DIR' does not exist."
fi

cd "$REPO_DIR" || die "Cannot access '$REPO_DIR'"

log_info "Starting Noba suite update..."

# -------------------------------------------------------------------
# Git update logic
# -------------------------------------------------------------------
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then

    # Check for local modifications
    if ! git diff --quiet || ! git diff --cached --quiet; then
        log_warn "Uncommitted changes detected in repository."

        if [[ "$AUTO_YES" != true && "$DRY_RUN" != true ]]; then
            if ! confirm "Pull changes and risk overwriting local edits?" "n"; then
                die "Update aborted by user."
            fi
        fi
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY RUN] Would fetch and pull $REMOTE/$BRANCH"
    else
        log_info "Fetching updates from $REMOTE..."
        git fetch "$REMOTE" "$BRANCH"

        log_info "Pulling latest changes..."
        if ! git pull --ff-only "$REMOTE" "$BRANCH"; then
            log_warn "Fast-forward pull failed. Manual merge may be required."
        fi
    fi

else
    log_warn "$REPO_DIR is not a git repository. Skipping git update."
fi

# -------------------------------------------------------------------
# System updates
# -------------------------------------------------------------------
if [[ "$UPDATE_SYSTEM" == true ]]; then

    if command -v dnf >/dev/null 2>&1; then
        if [[ "$DRY_RUN" == true ]]; then
            log_info "[DRY RUN] Would run: sudo dnf update"
        else
            log_info "Running DNF system update..."
            if [[ "$AUTO_YES" == true ]]; then
                sudo -n dnf update -y || log_warn "DNF update failed or sudo password required."
            else
                sudo dnf update || log_warn "DNF update failed."
            fi
        fi
    fi

    if command -v flatpak >/dev/null 2>&1; then
        if [[ "$DRY_RUN" == true ]]; then
            log_info "[DRY RUN] Would run: flatpak update"
        else
            log_info "Running Flatpak update..."
            if [[ "$AUTO_YES" == true ]]; then
                flatpak update -y || log_warn "Flatpak update failed."
            else
                flatpak update || log_warn "Flatpak update failed."
            fi
        fi
    fi
fi

# -------------------------------------------------------------------
# Script permissions
# -------------------------------------------------------------------
if [[ "$DRY_RUN" != true ]]; then
    log_info "Ensuring script permissions..."

    find "$REPO_DIR" \
        -maxdepth 2 \
        -type f \
        -name "*.sh" \
        -exec chmod +x {} +

    log_success "Update complete."
else
    log_info "Dry run complete."
fi
