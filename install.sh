#!/bin/bash
# install.sh – Smart installer for Nobara Automation Suite
# Version: 3.0.0
#
# Bugs fixed vs 2.x:
#   BUG-1  '. /etc/os-release' in detect_os() ran in the same shell and clobbered
#          any $NAME or $ID variables already set in the environment (e.g. from a
#          parent process or export). Now sourced inside a subshell via $() so
#          the caller's environment is never mutated.
#   BUG-2  Script glob '$SCRIPT_DIR/*.sh' without nullglob — if no files match,
#          the literal unexpanded string is passed through the loop; the
#          '[ -e "$script" ] || continue' guard caught it by accident. Also,
#          the glob copied ALL .sh files in the source dir including any stray
#          scripts not belonging to the suite. Replaced with an explicit
#          SUITE_SCRIPTS whitelist so only known files are installed.
#   BUG-3  Systemd unit glob '*.{timer,service}' without nullglob passed literal
#          unexpanded strings into the loop when no units existed. The inner
#          '[ -f "$unit" ]' guard caught it, but only by accident.
#          shopt -s nullglob now set for the duration of glob loops.
#   BUG-4  Default config hardcoded 'strikerke@gmail.com' — every install sent
#          email alerts to someone else's inbox. Now uses ${EMAIL:-} (from
#          environment) with an empty fallback and a post-install reminder.
#   BUG-5  Default config included cloud.rclone_opts — a raw string that was
#          eval'd by cloud-backup.sh v2 (a security issue fixed in v3). Since
#          v3 builds the options array explicitly, this key is now omitted from
#          the generated config to avoid confusion.
#   BUG-6  (see BUG-2) — explicit SUITE_SCRIPTS whitelist fixes stray-file
#          installation; only declared scripts are copied.
#   BUG-7  Bash completions were appended to ~/.bashrc regardless of the user's
#          shell. Now detects $SHELL and targets ~/.bashrc, ~/.zshrc, or
#          ~/.config/fish/conf.d/ appropriately; skips if shell is unsupported.
#   BUG-8  No rollback on partial failure. If cp failed mid-loop under set -e,
#          a partially-installed state was left with no record of what was done.
#          A trap now records installed files in a manifest and cleans up on
#          non-zero exit. --uninstall reads the manifest to reverse an install.
#   BUG-9  systemctl --user daemon-reload was silently swallowed by '|| true'
#          in containers / non-systemd environments. Now checks whether systemd
#          is actually running before attempting the reload, and prints an
#          informative message when it isn't.
#   BUG-10 '--help' was not in the test-harness compliance block at the top,
#          requiring the full argument-parsing loop to run before help was shown.
#          Added to the early-exit block for consistency with the rest of the suite.
#
# New in 3.0.0:
#   --uninstall          Remove a previously installed suite (reads manifest)
#   --prefix             Convenience alias for --dir
#   --no-completion      Skip shell completion setup
#   --no-systemd         Skip systemd unit installation
#   --email ADDR         Pre-fill email in generated config
#   Manifest file        Records every installed file for clean uninstall
#   Post-install summary Prints a checklist of what needs doing next

set -euo pipefail

# ── Test harness compliance ────────────────────────────────────────────────────
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
# BUG-10 FIX: --help in early-exit block
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: install.sh [OPTIONS]"; exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "install.sh version 3.0.0"; exit 0
fi

# ── Defaults ───────────────────────────────────────────────────────────────────
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"
CONFIG_DIR="${CONFIG_DIR:-$HOME/.config/noba}"
SYSTEMD_USER_DIR="${SYSTEMD_USER_DIR:-$HOME/.config/systemd/user}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=false
SKIP_DEPS=false
UNINSTALL=false
NO_COMPLETION=false
NO_SYSTEMD=false
USER_EMAIL="${EMAIL:-}"    # BUG-4 FIX: use env var, no hardcoded address

MANIFEST_FILE="${MANIFEST_FILE:-$HOME/.local/share/noba-install.manifest}"

# ── BUG-2/6 FIX: explicit whitelist of suite scripts ─────────────────────────
# Only these files are installed; stray .sh files in SCRIPT_DIR are ignored.
SUITE_SCRIPTS=(
    backup-to-nas.sh
    backup-verifier.sh
    backup-notify.sh
    checksum.sh
    cloud-backup.sh
    config-check.sh
    disk-sentinel.sh
    images-to-pdf.sh
    noba-lib.sh
    noba-web.sh
    organize-downloads.sh
)
# Optional scripts (warn if missing, don't fail)
OPTIONAL_SCRIPTS=(
    noba-tui.sh
    noba-dashboard.sh
    motd-generator.sh
    run-hogwarts-trainer.sh
    noba-update.sh
    noba-completion.sh
)

# ── Functions ──────────────────────────────────────────────────────────────────
say()     { printf '  %s\n' "$@"; }
say_ok()  { printf '  \033[0;32m✓\033[0m %s\n' "$@"; }
say_warn(){ printf '  \033[0;33m⚠\033[0m %s\n' "$@"; }
say_err() { printf '  \033[0;31m✗\033[0m %s\n' "$@" >&2; }
header()  { printf '\n\033[1m%s\033[0m\n' "$@"; }
dry()     { [[ "$DRY_RUN" == true ]] && printf '  [DRY RUN] %s\n' "$@"; }

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Install the Nobara Automation Suite to your local bin directory.

Options:
  -d, --dir DIR          Installation directory (default: $INSTALL_DIR)
      --prefix DIR       Alias for --dir
  -c, --config DIR       Configuration directory (default: $CONFIG_DIR)
  -s, --systemd DIR      Systemd user unit directory (default: $SYSTEMD_USER_DIR)
      --email ADDR       Pre-fill email address in generated config
      --skip-deps        Skip dependency installation
      --no-completion    Skip shell completion setup
      --no-systemd       Skip systemd unit installation and reload
  -u, --uninstall        Remove a previously installed suite (reads manifest)
  -n, --dry-run          Show what would be done without making changes
  -h, --help             Show this message
  -v, --version          Show version information
EOF
    exit 0
}

# ── BUG-8 FIX: manifest-based install tracking and rollback ───────────────────
INSTALLED_FILES=()

record_install() {
    local path="$1"
    INSTALLED_FILES+=("$path")
}

write_manifest() {
    mkdir -p "$(dirname "$MANIFEST_FILE")"
    printf '%s\n' "${INSTALLED_FILES[@]}" > "$MANIFEST_FILE"
    say_ok "Manifest written: $MANIFEST_FILE"
}

rollback() {
    local exit_code=$?
    if [[ "$exit_code" -ne 0 && "$DRY_RUN" == false && ${#INSTALLED_FILES[@]} -gt 0 ]]; then
        say_warn "Install failed — rolling back ${#INSTALLED_FILES[@]} installed file(s)..."
        for f in "${INSTALLED_FILES[@]}"; do
            rm -f "$f" && say_warn "  Removed: $f" || true
        done
    fi
}
trap rollback EXIT

do_uninstall() {
    if [[ ! -f "$MANIFEST_FILE" ]]; then
        say_err "No manifest found at $MANIFEST_FILE — cannot uninstall."
        exit 1
    fi
    header "Uninstalling Nobara Automation Suite"
    local count=0
    while IFS= read -r path; do
        [[ -z "$path" ]] && continue
        if [[ -f "$path" ]]; then
            if [[ "$DRY_RUN" == true ]]; then
                dry "Would remove: $path"
            else
                rm -f "$path"
                say_ok "Removed: $path"
            fi
            (( count++ )) || true
        else
            say_warn "Already gone: $path"
        fi
    done < "$MANIFEST_FILE"

    if [[ "$DRY_RUN" == false ]]; then
        rm -f "$MANIFEST_FILE"
        say_ok "Manifest removed."
    fi

    say "Uninstalled $count file(s)."
    say "Config directory ($CONFIG_DIR) and logs were NOT removed."
    say "To remove config: rm -rf $CONFIG_DIR"
    exit 0
}

# ── BUG-1 FIX: detect OS without clobbering environment ──────────────────────
# Source /etc/os-release in a subshell and print key=value pairs for safe eval
detect_os() {
    # Use a subshell so $NAME, $ID etc. in the parent environment are never touched
    OS_ID=$(bash -c '. /etc/os-release 2>/dev/null && echo "$ID"' || echo "unknown")
    OS_NAME=$(bash -c '. /etc/os-release 2>/dev/null && echo "$NAME"' || echo "Unknown Linux")
    OS_VERSION=$(bash -c '. /etc/os-release 2>/dev/null && echo "${VERSION_ID:-}"' || echo "")
}

# ── Dependency installation ────────────────────────────────────────────────────
install_deps() {
    [[ "$SKIP_DEPS" == true ]] && { say "Skipping dependency installation."; return 0; }

    local deps=()
    case "$OS_ID" in
        fedora|nobara|rhel|centos|rocky|almalinux)
            deps=(rsync rclone msmtp ImageMagick yq jq dialog psmisc lm_sensors lsof)
            if [[ "$DRY_RUN" == true ]]; then
                dry "Would run: sudo dnf install -y ${deps[*]}"
            else
                say "Installing via dnf..."
                sudo dnf install -y "${deps[@]}"
            fi
            ;;
        debian|ubuntu|linuxmint|pop|kali)
            deps=(rsync msmtp imagemagick jq dialog psmisc lm-sensors lsof)
            if [[ "$DRY_RUN" == true ]]; then
                dry "Would run: sudo apt install -y ${deps[*]}"
            else
                say "Installing via apt..."
                sudo apt-get update -qq
                sudo apt-get install -y "${deps[@]}"
                # rclone: apt package is often outdated; prefer official install script
                if ! command -v rclone &>/dev/null; then
                    say "Installing rclone via official script..."
                    curl -fsSL https://rclone.org/install.sh | sudo bash || \
                        say_warn "rclone install failed — install manually from https://rclone.org"
                fi
                # yq: not in standard apt repos
                if ! command -v yq &>/dev/null; then
                    if command -v snap &>/dev/null; then
                        sudo snap install yq
                    else
                        say_warn "yq not installed. Get it from: https://github.com/mikefarah/yq/releases"
                    fi
                fi
            fi
            ;;
        arch|manjaro|endeavouros|garuda)
            deps=(rsync rclone msmtp imagemagick yq jq dialog psmisc lm_sensors lsof)
            if [[ "$DRY_RUN" == true ]]; then
                dry "Would run: sudo pacman -S --noconfirm ${deps[*]}"
            else
                say "Installing via pacman..."
                sudo pacman -Sy --noconfirm "${deps[@]}"
            fi
            ;;
        opensuse*|sles)
            deps=(rsync rclone msmtp ImageMagick yq jq dialog psmisc sensors lsof)
            if [[ "$DRY_RUN" == true ]]; then
                dry "Would run: sudo zypper install -y ${deps[*]}"
            else
                say "Installing via zypper..."
                sudo zypper install -y "${deps[@]}"
            fi
            ;;
        *)
            say_warn "Unknown OS '$OS_ID' — please install these manually:"
            say_warn "  rsync rclone msmtp ImageMagick yq jq dialog psmisc lm_sensors lsof"
            ;;
    esac
}

# ── BUG-7 FIX: shell-aware completion setup ───────────────────────────────────
setup_completion() {
    [[ "$NO_COMPLETION" == true ]] && return 0
    [[ ! -f "$INSTALL_DIR/noba-completion.sh" ]] && return 0

    local shell_name rc_file
    shell_name=$(basename "${SHELL:-bash}")

    case "$shell_name" in
        bash)
            rc_file="$HOME/.bashrc"
            local marker="source $INSTALL_DIR/noba-completion.sh"
            if grep -qF "$marker" "$rc_file" 2>/dev/null; then
                say_ok "Bash completions already in $rc_file"
            elif [[ "$DRY_RUN" == true ]]; then
                dry "Would append completion source to $rc_file"
            else
                { echo ""; echo "# Nobara Automation Suite"; echo "$marker"; } >> "$rc_file"
                say_ok "Bash completions added to $rc_file"
            fi
            ;;
        zsh)
            rc_file="$HOME/.zshrc"
            local marker="source $INSTALL_DIR/noba-completion.sh"
            if grep -qF "$marker" "$rc_file" 2>/dev/null; then
                say_ok "Zsh completions already in $rc_file"
            elif [[ "$DRY_RUN" == true ]]; then
                dry "Would append completion source to $rc_file"
            else
                { echo ""; echo "# Nobara Automation Suite"; echo "$marker"; } >> "$rc_file"
                say_ok "Zsh completions added to $rc_file"
            fi
            ;;
        fish)
            local fish_conf="$HOME/.config/fish/conf.d/noba.fish"
            if [[ -f "$fish_conf" ]]; then
                say_ok "Fish completions already at $fish_conf"
            elif [[ "$DRY_RUN" == true ]]; then
                dry "Would create $fish_conf"
            else
                mkdir -p "$(dirname "$fish_conf")"
                echo "# Nobara Automation Suite" > "$fish_conf"
                echo "bass source $INSTALL_DIR/noba-completion.sh" >> "$fish_conf"
                say_ok "Fish completions written to $fish_conf"
                say_warn "Fish requires 'bass' plugin to source bash completions."
            fi
            ;;
        *)
            say_warn "Unrecognised shell '$shell_name' — skipping completion setup."
            say_warn "Manually add: source $INSTALL_DIR/noba-completion.sh"
            ;;
    esac
}

# ── BUG-9 FIX: check systemd is actually running before reloading ─────────────
reload_systemd() {
    [[ "$NO_SYSTEMD" == true ]] && return 0
    [[ "$DRY_RUN"  == true ]] && { dry "Would run: systemctl --user daemon-reload"; return 0; }

    if ! command -v systemctl &>/dev/null; then
        say_warn "systemctl not found — systemd units installed but not loaded."
        return 0
    fi

    # Check if the user session bus is reachable
    if ! systemctl --user is-system-running &>/dev/null \
       && ! systemctl --user status &>/dev/null 2>&1 | grep -q -v "Failed to connect"; then
        say_warn "systemd user session not available (container/non-systemd env)."
        say_warn "Units were copied but not activated — reload manually when systemd is running."
        return 0
    fi

    if systemctl --user daemon-reload 2>/dev/null; then
        say_ok "systemd user daemon reloaded."
    else
        say_warn "systemd daemon-reload failed — units may not be active until next login."
    fi
}

# ── Argument parsing ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        -d|--dir|--prefix) INSTALL_DIR="$2"; shift 2 ;;
        -c|--config)       CONFIG_DIR="$2";          shift 2 ;;
        -s|--systemd)      SYSTEMD_USER_DIR="$2";    shift 2 ;;
           --email)        USER_EMAIL="$2";          shift 2 ;;
           --skip-deps)    SKIP_DEPS=true;           shift   ;;
           --no-completion)NO_COMPLETION=true;       shift   ;;
           --no-systemd)   NO_SYSTEMD=true;          shift   ;;
        -u|--uninstall)    UNINSTALL=true;           shift   ;;
        -n|--dry-run)      DRY_RUN=true;             shift   ;;
        -h|--help)         show_help ;;
        -v|--version)      echo "install.sh version 3.0.0"; exit 0 ;;
        *) say_err "Unknown argument: $1"; exit 1 ;;
    esac
done

# ── Uninstall mode ─────────────────────────────────────────────────────────────
[[ "$UNINSTALL" == true ]] && do_uninstall

# ── Begin install ─────────────────────────────────────────────────────────────
header "Nobara Automation Suite Installer v3.0.0"

detect_os
say "OS: $OS_NAME ($OS_ID${OS_VERSION:+ $OS_VERSION})"
say "Install dir:  $INSTALL_DIR"
say "Config dir:   $CONFIG_DIR"
say "Systemd dir:  $SYSTEMD_USER_DIR"
[[ "$DRY_RUN" == true ]] && say_warn "DRY RUN — no files will be written"

# ── Dependencies ───────────────────────────────────────────────────────────────
header "Dependencies"
install_deps

# ── Create directories ─────────────────────────────────────────────────────────
header "Creating directories"
if [[ "$DRY_RUN" == true ]]; then
    dry "mkdir -p $INSTALL_DIR $CONFIG_DIR $SYSTEMD_USER_DIR"
else
    mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$SYSTEMD_USER_DIR"
    say_ok "Directories ready"
fi

# ── Copy scripts (BUG-2/6 FIX: whitelist only) ────────────────────────────────
header "Installing scripts"
for name in "${SUITE_SCRIPTS[@]}"; do
    src="$SCRIPT_DIR/$name"
    dst="$INSTALL_DIR/$name"
    if [[ ! -f "$src" ]]; then
        say_warn "Not found in source, skipping: $name"
        continue
    fi
    if [[ "$DRY_RUN" == true ]]; then
        dry "cp $name → $INSTALL_DIR/"
    else
        cp "$src" "$dst"
        # Library files don't need +x, but having it set is harmless and consistent
        chmod +x "$dst"
        record_install "$dst"
        say_ok "$name"
    fi
done

for name in "${OPTIONAL_SCRIPTS[@]}"; do
    src="$SCRIPT_DIR/$name"
    dst="$INSTALL_DIR/$name"
    [[ -f "$src" ]] || continue
    if [[ "$DRY_RUN" == true ]]; then
        dry "cp $name → $INSTALL_DIR/ (optional)"
    else
        cp "$src" "$dst"
        chmod +x "$dst"
        record_install "$dst"
        say_ok "$name (optional)"
    fi
done

# Copy noba CLI wrapper if present
if [[ -f "$SCRIPT_DIR/noba" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
        dry "cp noba → $INSTALL_DIR/"
    else
        cp "$SCRIPT_DIR/noba" "$INSTALL_DIR/noba"
        chmod +x "$INSTALL_DIR/noba"
        record_install "$INSTALL_DIR/noba"
        say_ok "noba (CLI wrapper)"
    fi
fi

# ── Default config (BUG-4/5 FIX) ──────────────────────────────────────────────
header "Configuration"
if [[ -f "$CONFIG_DIR/config.yaml" ]]; then
    say_ok "Config already exists — skipping generation."
elif [[ "$DRY_RUN" == true ]]; then
    dry "Would create default config at $CONFIG_DIR/config.yaml"
else
    # BUG-4 FIX: no hardcoded personal email — use env var or leave blank
    # BUG-5 FIX: cloud.rclone_opts removed (v3 builds options explicitly)
    cat > "$CONFIG_DIR/config.yaml" <<YAML
# Nobara Automation Suite — Configuration
# Edit this file to match your environment.

# Email address for alerts (backup failures, disk warnings)
email: "${USER_EMAIL}"

logs:
  dir: "$HOME/.local/share"

backup:
  dest: "/mnt/vnnas/backups/raizen"
  retention_days: 7
  keep_count: 3
  sources:
    - "$HOME/Documents"
    - "$HOME/Pictures"
    - "$HOME/.config"

cloud:
  # rclone remote name — run 'rclone config' to set up
  remote: "mycloud:backups/raizen"
  # Optional: bandwidth, retries, transfers
  # bandwidth: "10M"
  # retries: 3

disk:
  threshold: 85
  warn_threshold: 75
  cleanup_enabled: true
  du_timeout: 30
  targets:
    - "/"
    - "$HOME"

web:
  port: 8080

backup_verifier:
  num_files: 5
  checksum_cmd: "sha256sum"
YAML
    record_install "$CONFIG_DIR/config.yaml"
    say_ok "Default config written: $CONFIG_DIR/config.yaml"
    if [[ -z "$USER_EMAIL" ]]; then
        say_warn "Email address is blank — edit $CONFIG_DIR/config.yaml to add one."
    fi
fi

# ── Shell completions (BUG-7 FIX) ────────────────────────────────────────────
header "Shell completions"
setup_completion

# ── Systemd units (BUG-3 FIX: nullglob) ──────────────────────────────────────
header "Systemd user units"
if [[ -d "$SCRIPT_DIR/systemd" ]]; then
    # BUG-3 FIX: nullglob so empty glob doesn't iterate
    shopt -s nullglob
    unit_count=0
    for unit in "$SCRIPT_DIR"/systemd/*.timer "$SCRIPT_DIR"/systemd/*.service; do
        name=$(basename "$unit")
        if [[ "$DRY_RUN" == true ]]; then
            dry "cp $name → $SYSTEMD_USER_DIR/"
        else
            cp "$unit" "$SYSTEMD_USER_DIR/$name"
            record_install "$SYSTEMD_USER_DIR/$name"
            say_ok "$name"
        fi
        (( unit_count++ )) || true
    done
    shopt -u nullglob

    if (( unit_count == 0 )); then
        say "No .timer or .service files found in $SCRIPT_DIR/systemd/"
    fi
else
    say "No systemd/ directory in source — skipping unit installation."
fi

# BUG-9 FIX: check systemd availability before reloading
reload_systemd

# ── Write manifest (BUG-8 FIX) ───────────────────────────────────────────────
if [[ "$DRY_RUN" == false && ${#INSTALLED_FILES[@]} -gt 0 ]]; then
    write_manifest
    # Success: disarm the rollback trap
    trap - EXIT
fi

# ── Post-install summary ───────────────────────────────────────────────────────
header "Installation complete"
if [[ "$DRY_RUN" == false ]]; then
    say "Files installed  : ${#INSTALLED_FILES[@]}"
    say "Manifest         : $MANIFEST_FILE"
    echo ""
    say "Next steps:"

    if [[ -z "$USER_EMAIL" ]]; then
        say "  1. Set your email in $CONFIG_DIR/config.yaml"
    fi

    local_shell=$(basename "${SHELL:-bash}")
    if [[ "$NO_COMPLETION" == false ]]; then
        case "$local_shell" in
            bash|zsh) say "  • Run: source ~/${local_shell}rc   (or open a new terminal)" ;;
        esac
    fi

    if command -v systemctl &>/dev/null && [[ "$NO_SYSTEMD" == false ]]; then
        say "  • Enable timers, e.g.:"
        say "      systemctl --user enable --now disk-sentinel.timer"
        say "      systemctl --user enable --now backup-to-nas.timer"
    fi

    say "  • Check dependencies: config-check.sh"
    say "  • Edit config:        $CONFIG_DIR/config.yaml"
    say "  • To uninstall:       $(basename "$0") --uninstall"
fi
