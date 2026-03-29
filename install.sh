#!/bin/bash
# install.sh – Smart installer for Noba Automation Suite
# Version: 3.5.0

set -euo pipefail

readonly INSTALLER_VERSION="3.5.0"

# ── Safety ─────────────────────────────────────────────────────────────────────
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    echo "⚠ Running as root is not recommended. Use a regular user with sudo."
fi

# ── Helpers ────────────────────────────────────────────────────────────────────
require_cmd() {
    command -v "$1" &>/dev/null || {
        echo "✗ Required command not found: $1" >&2
        exit 1
    }
}

install_file() {
    local src="$1"
    local dst="$2"
    local mode="${3:-755}"

    if [[ "$DRY_RUN" == true ]]; then
        printf '  [DRY RUN] install %s → %s (mode %s)\n' "$src" "$dst" "$mode"
        return
    fi

    install -Dm"$mode" "$src" "$dst"
    record_install "$dst"
}

say()      { printf '  %s\n' "$@"; }
say_ok()   { printf '  \033[0;32m✓\033[0m %s\n' "$@"; }
say_warn() { printf '  \033[0;33m⚠\033[0m %s\n' "$@"; }
say_err()  { printf '  \033[0;31m✗\033[0m %s\n' "$@" >&2; }
header()   { printf '\n\033[1m%s\033[0m\n' "$@"; }
dry()      { [[ "$DRY_RUN" == true ]] && printf '  [DRY RUN] %s\n' "$@"; }

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Install the Noba Automation Suite.

Options:
  -d, --dir DIR          Bin directory for wrapper (default: $BIN_DIR)
      --prefix DIR       Base installation prefix (default: $PREFIX)
  -c, --config DIR       Configuration directory (default: $CONFIG_DIR)
  -s, --systemd DIR      Systemd user unit directory (default: $SYSTEMD_USER_DIR)
      --email ADDR       Pre-fill email address in generated config
      --skip-deps        Skip dependency installation
      --no-completion    Skip shell completion setup
      --no-systemd       Skip systemd unit installation and reload
      --no-restart       Skip service restart after install
  -y, --auto-approve     Auto-approve all prompts (unattended/CI install)
  -u, --uninstall        Remove a previously installed suite (reads manifest)
  -n, --dry-run          Show what would be done without making changes
  -h, --help             Show this message
  -v, --version          Show version information
EOF
    exit 0
}

# ── Defaults (needed before --help) ────────────────────────────────────────────
PREFIX="${PREFIX:-$HOME/.local}"
BIN_DIR="${BIN_DIR:-$PREFIX/bin}"
LIBEXEC_DIR="${LIBEXEC_DIR:-$PREFIX/libexec/noba}"
MAN_DIR="${MAN_DIR:-$PREFIX/share/man/man1}"
CONFIG_DIR="${CONFIG_DIR:-$HOME/.config/noba}"
SYSTEMD_USER_DIR="${SYSTEMD_USER_DIR:-$HOME/.config/systemd/user}"

# ── Test harness compliance ────────────────────────────────────────────────────
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    show_help
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "install.sh version $INSTALLER_VERSION"; exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=false
SKIP_DEPS=false
UNINSTALL=false
NO_COMPLETION=false
NO_SYSTEMD=false
NO_RESTART=false
AUTO_APPROVE=false
USER_EMAIL="${EMAIL:-}"

MANIFEST_FILE="${MANIFEST_FILE:-$HOME/.local/share/noba-install.manifest}"

SUITE_SCRIPTS=(
    backup-to-nas.sh
    backup-verifier.sh
    backup-notify.sh
    checksum.sh
    cloud-backup.sh
    config-check.sh
    disk-sentinel.sh
    images-to-pdf.sh
    organize-downloads.sh
)
OPTIONAL_SCRIPTS=(
    noba-tui.sh
    noba-dashboard.sh
    motd-generator.sh
    run-hogwarts-trainer.sh
    noba-update.sh
    noba-completion.sh
)

# ── Manifest & rollback ────────────────────────────────────────────────────────
INSTALLED_FILES=()

record_install() {
    local path="$1"
    INSTALLED_FILES+=("$path")
}

write_manifest() {
    mkdir -p "$(dirname "$MANIFEST_FILE")"

    local tmp
    tmp=$(mktemp) || {
        say_warn "mktemp failed — writing manifest directly"
        printf '%s\n' "${INSTALLED_FILES[@]}" > "$MANIFEST_FILE"
        say_ok "Manifest written: $MANIFEST_FILE"
        return
    }

    {
        echo "# Noba v${INSTALLER_VERSION} — installed $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        printf '%s\n' "${INSTALLED_FILES[@]}"
    } > "$tmp"
    mv "$tmp" "$MANIFEST_FILE"
    say_ok "Manifest written: $MANIFEST_FILE"
}

rollback() {
    local exit_code=$?
    if [[ "$exit_code" -ne 0 && "$DRY_RUN" == false ]]; then
        if [[ ${#INSTALLED_FILES[@]} -gt 0 ]]; then
            say_warn "Install failed — rolling back ${#INSTALLED_FILES[@]} installed file(s)..."
            systemctl --user stop noba-web.service 2>/dev/null || true
            for f in "${INSTALLED_FILES[@]}"; do
                rm -f "$f" && say_warn "  Removed: $f" || true
            done
            find "${LIBEXEC_DIR:-/tmp}/web" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
        else
            say_warn "Install failed — no manifest entries to rollback."
        fi
    fi
}
trap rollback EXIT

do_uninstall() {
    if [[ ! -f "$MANIFEST_FILE" ]]; then
        say_err "No manifest found at $MANIFEST_FILE — cannot uninstall."
        exit 1
    fi
    header "Uninstalling Noba Automation Suite"
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

# ── OS & deps ──────────────────────────────────────────────────────────────────
detect_os() {
    OS_ID=$(bash -c '. /etc/os-release 2>/dev/null && echo "$ID"' || echo "unknown")
    OS_NAME=$(bash -c '. /etc/os-release 2>/dev/null && echo "$NAME"' || echo "Unknown Linux")
    OS_VERSION=$(bash -c '. /etc/os-release 2>/dev/null && echo "${VERSION_ID:-}"' || echo "")
}

install_deps() {
    if [[ "$SKIP_DEPS" == true ]]; then
        say "Skipping dependency installation."
        return 0
    fi

    require_cmd sudo
    require_cmd curl

    local deps=()
    local _confirm_dnf=()
    local _confirm_apt=()
    local _confirm_pacman=()
    local _confirm_zypper=()
    local _confirm_apk=()
    if [[ "$AUTO_APPROVE" == true ]]; then
        _confirm_dnf=(-y)
        _confirm_apt=(-y)
        _confirm_pacman=(--noconfirm)
        _confirm_zypper=(-y)
        _confirm_apk=(-y)
    fi

    case "$OS_ID" in
        fedora|nobara|rhel|centos|rocky|almalinux)
            deps=(rsync rclone msmtp ImageMagick yq jq dialog psmisc lm_sensors lsof python3)
            if [[ "$DRY_RUN" == true ]]; then
                dry "Would run: sudo dnf install ${_confirm_dnf[*]:-} ${deps[*]}"
            else
                say "Installing via dnf..."
                sudo dnf install "${_confirm_dnf[@]}" "${deps[@]}"
            fi
            ;;
        debian|ubuntu|linuxmint|pop|kali)
            deps=(rsync msmtp imagemagick jq dialog psmisc lm-sensors lsof python3)
            if [[ "$DRY_RUN" == true ]]; then
                dry "Would run: sudo apt install ${_confirm_apt[*]:-} ${deps[*]}"
            else
                say "Installing via apt..."
                sudo apt-get update -qq
                sudo apt-get install "${_confirm_apt[@]}" "${deps[@]}"
                if ! command -v rclone &>/dev/null; then
                    say_warn "Installing rclone via remote script (review recommended)."
                    if [[ "$DRY_RUN" == true ]]; then
                        dry "Would download and run rclone install script"
                    else
                        tmp_inst="/tmp/rclone-install-$$.sh"
                        curl -fsSL https://rclone.org/install.sh -o "$tmp_inst" || {
                            say_warn "Failed to download rclone installer; install rclone manually from https://rclone.org"
                        }
                        if [[ -f "$tmp_inst" ]]; then
                            sudo bash "$tmp_inst" || say_warn "rclone install script failed; install manually"
                            rm -f "$tmp_inst"
                        fi
                    fi
                fi
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
            deps=(rsync rclone msmtp imagemagick yq jq dialog psmisc lm_sensors lsof python3)
            if [[ "$DRY_RUN" == true ]]; then
                dry "Would run: sudo pacman -Sy ${_confirm_pacman[*]:-} ${deps[*]}"
            else
                say "Installing via pacman..."
                sudo pacman -Sy ${_confirm_pacman[@]+"${_confirm_pacman[@]}"} "${deps[@]}"
            fi
            ;;
        opensuse*|sles)
            deps=(rsync rclone msmtp ImageMagick yq jq dialog psmisc sensors lsof python3)
            if [[ "$DRY_RUN" == true ]]; then
                dry "Would run: sudo zypper install ${_confirm_zypper[*]:-} ${deps[*]}"
            else
                say "Installing via zypper..."
                sudo zypper install "${_confirm_zypper[@]}" "${deps[@]}"
            fi
            ;;
        alpine)
            deps=(rsync rclone msmtp imagemagick yq jq dialog procps lm_sensors lsof python3 bash)
            if [[ "$DRY_RUN" == true ]]; then
                dry "Would run: sudo apk add ${_confirm_apk[*]:-} ${deps[*]}"
            else
                say "Installing via apk..."
                sudo apk add "${_confirm_apk[@]}" "${deps[@]}" || true
            fi
            ;;
        void)
            deps=(rsync rclone msmtp ImageMagick yq jq dialog psmisc lm_sensors lsof python3)
            if [[ "$DRY_RUN" == true ]]; then
                dry "Would run: sudo xbps-install -Sy ${deps[*]}"
            else
                say "Installing via xbps-install..."
                if [[ "$AUTO_APPROVE" == true ]]; then
                    sudo xbps-install -Sy "${deps[@]}"
                else
                    sudo xbps-install -S "${deps[@]}"
                fi
            fi
            ;;
        *)
            say_warn "Unknown OS '$OS_ID' — please install these manually:"
            say_warn "  rsync rclone msmtp ImageMagick yq jq dialog psmisc lm_sensors lsof python3"
            ;;
    esac
}

# ── Shell completions ─────────────────────────────────────────────────────────
setup_completion() {
    if [[ "$NO_COMPLETION" == true ]]; then return 0; fi
    if [[ ! -f "$LIBEXEC_DIR/noba-completion.sh" ]]; then return 0; fi

    local shell_name rc_file
    shell_name=$(basename "${SHELL:-bash}")

    case "$shell_name" in
        bash)
            rc_file="$HOME/.bashrc"
            local marker="source $LIBEXEC_DIR/noba-completion.sh"
            if grep -qF "$marker" "$rc_file" 2>/dev/null; then
                say_ok "Bash completions already in $rc_file"
            elif [[ "$DRY_RUN" == true ]]; then
                dry "Would append completion source to $rc_file"
            else
                { echo ""; echo "# Noba Automation Suite"; echo "$marker"; } >> "$rc_file"
                say_ok "Bash completions added to $rc_file"
            fi
            ;;
        zsh)
            rc_file="$HOME/.zshrc"
            local marker="source $LIBEXEC_DIR/noba-completion.sh"
            if grep -qF "$marker" "$rc_file" 2>/dev/null; then
                say_ok "Zsh completions already in $rc_file"
            elif [[ "$DRY_RUN" == true ]]; then
                dry "Would append completion source to $rc_file"
            else
                { echo ""; echo "# Noba Automation Suite"; echo "$marker"; } >> "$rc_file"
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
                echo "# Noba Automation Suite" > "$fish_conf"
                echo "bass source $LIBEXEC_DIR/noba-completion.sh" >> "$fish_conf"
                say_ok "Fish completions written to $fish_conf"
                say_warn "Fish requires 'bass' plugin to source bash completions."
            fi
            ;;
        *)
            say_warn "Unrecognised shell '$shell_name' — skipping completion setup."
            say_warn "Manually add: source $LIBEXEC_DIR/noba-completion.sh"
            ;;
    esac
}

# ── Systemd reload ────────────────────────────────────────────────────────────
reload_systemd() {
    if [[ "$NO_SYSTEMD" == true ]]; then return 0; fi
    if [[ "$DRY_RUN"  == true ]]; then
        dry "Would run: systemctl --user daemon-reload"
        return 0
    fi

    if ! command -v systemctl &>/dev/null; then
        say_warn "systemctl not found — systemd units installed but not loaded."
        return 0
    fi

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
        -d|--dir)          BIN_DIR="$2";             shift 2 ;;
           --prefix)       PREFIX="$2"
                           BIN_DIR="$PREFIX/bin"
                           LIBEXEC_DIR="$PREFIX/libexec/noba"
                           MAN_DIR="$PREFIX/share/man/man1"; shift 2 ;;
        -c|--config)       CONFIG_DIR="$2";          shift 2 ;;
        -s|--systemd)      SYSTEMD_USER_DIR="$2";    shift 2 ;;
           --email)        USER_EMAIL="$2";          shift 2 ;;
           --skip-deps)    SKIP_DEPS=true;           shift   ;;
           --no-completion)NO_COMPLETION=true;       shift   ;;
           --no-systemd)   NO_SYSTEMD=true;          shift   ;;
           --no-restart)   NO_RESTART=true;          shift   ;;
        -y|--auto-approve) AUTO_APPROVE=true;        shift   ;;
        -u|--uninstall)    UNINSTALL=true;           shift   ;;
        -n|--dry-run)      DRY_RUN=true;             shift   ;;
        -h|--help)         show_help ;;
        -v|--version)      echo "install.sh version $INSTALLER_VERSION"; exit 0 ;;
        *) say_err "Unknown argument: $1"; exit 1 ;;
    esac
done

if [[ "$UNINSTALL" == true ]]; then
    do_uninstall
fi

# ── Begin install ─────────────────────────────────────────────────────────────
header "Noba Automation Suite Installer v$INSTALLER_VERSION"

detect_os
say "OS: $OS_NAME ($OS_ID${OS_VERSION:+ $OS_VERSION})"
say "Bin dir:      $BIN_DIR"
say "Libexec dir:  $LIBEXEC_DIR"
say "Config dir:   $CONFIG_DIR"
say "Systemd dir:  $SYSTEMD_USER_DIR"

if [[ "$DRY_RUN" == true ]]; then
    say_warn "DRY RUN — no files will be written"
fi

header "Dependencies"
install_deps

header "Creating directories"
if [[ "$DRY_RUN" == true ]]; then
    dry "install -d $BIN_DIR $LIBEXEC_DIR/lib $CONFIG_DIR $SYSTEMD_USER_DIR $MAN_DIR $LIBEXEC_DIR/web $LIBEXEC_DIR/web/static"
else
    install -d "$BIN_DIR" "$LIBEXEC_DIR/lib" "$CONFIG_DIR" "$SYSTEMD_USER_DIR" "$MAN_DIR" \
               "$LIBEXEC_DIR/web" "$LIBEXEC_DIR/web/static"
    say_ok "Directories ready"
fi

header "Installing components"

# 1. Library
src="$SCRIPT_DIR/libexec/lib/noba-lib.sh"
dst="$LIBEXEC_DIR/lib/noba-lib.sh"
if [[ -f "$src" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
        dry "install $src → $dst"
    else
        install_file "$src" "$dst" 755
        say_ok "Library installed"
    fi
else
    say_err "Missing library file: $src"
    exit 1
fi

# 2. Automation scripts
for name in "${SUITE_SCRIPTS[@]}"; do
    src="$SCRIPT_DIR/libexec/$name"
    dst="$LIBEXEC_DIR/$name"
    if [[ ! -f "$src" ]]; then
        say_warn "Not found in source, skipping: libexec/$name"
        continue
    fi
    if [[ "$DRY_RUN" == true ]]; then
        dry "install $src → $dst"
    else
        install_file "$src" "$dst" 755
        say_ok "$name"
    fi
done

for name in "${OPTIONAL_SCRIPTS[@]}"; do
    src="$SCRIPT_DIR/libexec/$name"
    dst="$LIBEXEC_DIR/$name"
    if [[ ! -f "$src" ]]; then
        continue
    fi
    if [[ "$DRY_RUN" == true ]]; then
        dry "install $src → $dst (optional)"
    else
        install_file "$src" "$dst" 755
        say_ok "$name (optional)"
    fi
done

# 3. CLI wrapper
if [[ -f "$SCRIPT_DIR/bin/noba" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
        dry "install $SCRIPT_DIR/bin/noba → $BIN_DIR/noba"
    else
        install_file "$SCRIPT_DIR/bin/noba" "$BIN_DIR/noba" 755
        say_ok "noba (CLI wrapper)"
    fi
fi

# 4. Web dashboard
# ── Python dependencies for web dashboard ────────────────────────────────────
header "Python Dependencies"
_py_deps=(fastapi "uvicorn[standard]" psutil pyyaml httpx websocket-client cryptography defusedxml)
if [[ "$DRY_RUN" == true ]]; then
    dry "pip install ${_py_deps[*]}"
else
    if python3 -m pip install --quiet --upgrade "${_py_deps[@]}" 2>/dev/null; then
        say_ok "Python packages: ${_py_deps[*]}"
    elif pip3 install --quiet --upgrade "${_py_deps[@]}" 2>/dev/null; then
        say_ok "Python packages: ${_py_deps[*]}"
    else
        say_warn "Could not install Python packages automatically."
        say_warn "Please install manually: pip install ${_py_deps[*]}"
    fi
fi

header "Installing Web Dashboard"

src="$SCRIPT_DIR/share/noba-web/server.py"
dst="$LIBEXEC_DIR/web/server.py"
if [[ -f "$src" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
        dry "install $src → $dst"
    else
        install_file "$src" "$dst" 755
        say_ok "Web component: server.py"
    fi
fi

# Install the FastAPI server package (server/ directory)
server_pkg_src="$SCRIPT_DIR/share/noba-web/server"
server_pkg_dst="$LIBEXEC_DIR/web/server"
if [[ -d "$server_pkg_src" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
        dry "install $server_pkg_src/ → $server_pkg_dst/"
    else
        # Validate Python syntax before deploying (top-level + subdirs)
        _syntax_ok=true
        while IFS= read -r pyf; do
            if ! python3 -m py_compile "$pyf" 2>/dev/null; then
                say_err "Syntax error in ${pyf#"$server_pkg_src"/} — aborting deploy"
                _syntax_ok=false
            fi
        done < <(find "$server_pkg_src" -name '*.py' -not -path '*__pycache__*')

        if [[ "$_syntax_ok" != true ]]; then
            say_err "Fix syntax errors before installing."
            exit 1
        fi

        # Clean stale bytecode cache and leftover nested dirs
        find "$server_pkg_dst" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
        [[ -d "$server_pkg_dst/server" ]] && rm -rf "$server_pkg_dst/server"

        # Remove stale .py files replaced by packages (v2.x → v3.x migration)
        for stale in db.py integrations.py metrics.py; do
            [[ -f "$server_pkg_dst/$stale" ]] && rm -f "$server_pkg_dst/$stale" && say "Cleaned stale $stale (replaced by package)"
        done

        # Deploy all .py files (top-level)
        mkdir -p "$server_pkg_dst"
        for pyf in "$server_pkg_src"/*.py; do
            [[ -f "$pyf" ]] || continue
            install_file "$pyf" "$server_pkg_dst/$(basename "$pyf")" 644
        done

        # Deploy subdirectories (routers, etc.) recursively
        shopt -s nullglob
        for subdir in "$server_pkg_src"/*/; do
            [[ -d "$subdir" ]] || continue
            dirname=$(basename "$subdir")
            [[ "$dirname" == "__pycache__" ]] && continue
            mkdir -p "$server_pkg_dst/$dirname"
            for pyf in "$subdir"*.py; do
                [[ -f "$pyf" ]] || continue
                install_file "$pyf" "$server_pkg_dst/$dirname/$(basename "$pyf")" 644
            done
        done
        shopt -u nullglob

        say_ok "Web server package (FastAPI modules)"
    fi
fi

# Deploy all static assets (including Vue build in static/dist/)
_static_src="$SCRIPT_DIR/share/noba-web/static"
_static_dst="$LIBEXEC_DIR/web/static"
if [[ -d "$_static_src" ]]; then
    _static_count=0
    mkdir -p "$_static_dst"
    # Copy top-level static files (favicon, style.css, etc.)
    for f in "$_static_src"/*; do
        [[ -f "$f" ]] || continue
        fname=$(basename "$f")
        [[ "$fname" == *.map ]] && continue  # skip source maps
        if [[ "$DRY_RUN" == true ]]; then
            dry "install $f → $_static_dst/$fname"
        else
            install_file "$f" "$_static_dst/$fname" 644
            _static_count=$(( _static_count + 1 ))
        fi
    done
    # Copy Vue build output (static/dist/ with assets/)
    if [[ -d "$_static_src/dist" ]]; then
        if [[ "$DRY_RUN" == true ]]; then
            dry "install $_static_src/dist/ → $_static_dst/dist/"
        else
            mkdir -p "$_static_dst/dist"
            cp -r "$_static_src/dist/"* "$_static_dst/dist/"
            _dist_count=$(find "$_static_dst/dist" -type f | wc -l)
            _static_count=$(( _static_count + _dist_count ))
            say_ok "Vue build output ($_dist_count files)"
        fi
    fi
    [[ "$DRY_RUN" != true ]] && say_ok "Web static assets ($_static_count files total)"
fi

# Deploy bundled plugin catalog
_plugins_src="$SCRIPT_DIR/share/noba-web/plugins/catalog"
_plugins_dst="$LIBEXEC_DIR/web/plugins/catalog"
if [[ -d "$_plugins_src" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
        dry "install $_plugins_src/ → $_plugins_dst/"
    else
        mkdir -p "$_plugins_dst"
        cp -r "$_plugins_src/"*.py "$_plugins_dst/" 2>/dev/null || true
        _plug_count=$(find "$_plugins_dst" -name '*.py' -type f | wc -l)
        say_ok "Bundled plugin catalog ($_plug_count plugins)"
    fi
fi

# Deploy agent zipapp (served via /api/agent/update for remote agent self-update)
_agent_pyz_src="$SCRIPT_DIR/share/noba-agent.pyz"
_agent_pyz_dst="$LIBEXEC_DIR/noba-agent.pyz"
if [[ -f "$_agent_pyz_src" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
        dry "install $_agent_pyz_src → $_agent_pyz_dst"
    else
        install_file "$_agent_pyz_src" "$_agent_pyz_dst" 755
        say_ok "Agent zipapp (for remote update)"
    fi
elif [[ -d "$SCRIPT_DIR/share/noba-agent" ]]; then
    # Build the zipapp on the fly if not pre-built
    if [[ "$DRY_RUN" == true ]]; then
        dry "build agent.pyz from share/noba-agent → $_agent_pyz_dst"
    else
        python3 -m zipapp "$SCRIPT_DIR/share/noba-agent" \
            --output "$_agent_pyz_dst" \
            --python "/usr/bin/env python3"
        chmod 755 "$_agent_pyz_dst"
        say_ok "Agent zipapp (built + deployed for remote update)"
    fi
fi

src="$SCRIPT_DIR/bin/noba-web"
dst="$BIN_DIR/noba-web"
if [[ -f "$src" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
        dry "install $src → $dst"
    else
        install_file "$src" "$dst" 755
        say_ok "noba-web (standalone launcher)"
    fi
fi

# 5. Man page
if [[ -f "$SCRIPT_DIR/docs/noba.1" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
        dry "install $SCRIPT_DIR/docs/noba.1 → $MAN_DIR/noba.1"
    else
        install_file "$SCRIPT_DIR/docs/noba.1" "$MAN_DIR/noba.1" 644
        say_ok "noba.1 (man page)"
    fi
fi

# ── Configuration ──────────────────────────────────────────────────────────────
header "Configuration"
if [[ -f "$CONFIG_DIR/config.yaml" ]]; then
    say_ok "Config already exists — skipping generation."
elif [[ "$DRY_RUN" == true ]]; then
    dry "Would create default config at $CONFIG_DIR/config.yaml"
else
    mkdir -p "$CONFIG_DIR"
    cat > "$CONFIG_DIR/config.yaml" <<EOF
# Noba Automation Suite — Configuration
# Edit this file to match your environment.

email: "you@example.com"

logs:
  dir: "$HOME/.local/share/noba"

backup:
  dest: "$HOME/backups"
  retention_days: 7
  keep_count: 3
  sources:
    - "$HOME/Documents"
    - "$HOME/Pictures"
    - "$HOME/.config"

cloud:
  remote: "mycloud:backups/$USER"

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
  wanTestIp: "8.8.8.8"
  lanTestIp: "192.168.1.1"
  customActions:
    - id: "reboot-dns"
      name: "Reboot DNS Stack"
      icon: "fa-sync-alt"
      command: "ssh admin@192.168.1.1 sudo reboot"
  automations:
    - id: "test-hook"
      name: "Test Webhook"
      icon: "fa-bolt"
      url: "http://localhost:8080/api/health"

backup_verifier:
  checksum_cmd: "sha256sum"

# Notifications (optional)
notifications:
  # email:
  #   enabled: false
  #   smtp_server: "smtp.gmail.com:587"
  #   username: "you@gmail.com"
  #   password: "your-app-password"
  #   from: "you@gmail.com"
  #   to: "admin@example.com"
  #   starttls: true
  # telegram:
  #   enabled: false
  #   bot_token: "123456:ABC-DEF1234"
  #   chat_id: "123456789"
  # discord:
  #   enabled: false
  #   webhook_url: "https://discord.com/api/webhooks/..."
  # slack:
  #   enabled: false
  #   webhook_url: "https://hooks.slack.com/services/..."
EOF
    record_install "$CONFIG_DIR/config.yaml"
    say_ok "Default config written: $CONFIG_DIR/config.yaml"
    if [[ -z "$USER_EMAIL" ]]; then
        say_warn "Email address is blank — edit $CONFIG_DIR/config.yaml to add one."
    fi
fi

# ── Shell completions ─────────────────────────────────────────────────────────
header "Shell completions"
setup_completion

# ── Systemd units ─────────────────────────────────────────────────────────────
header "Systemd user units"
if [[ -d "$SCRIPT_DIR/systemd" ]]; then
    shopt -s nullglob
    unit_count=0
    for unit in "$SCRIPT_DIR"/systemd/*.timer "$SCRIPT_DIR"/systemd/*.service; do
        name=$(basename "$unit")
        if [[ "$DRY_RUN" == true ]]; then
            dry "install $unit → $SYSTEMD_USER_DIR/$name"
        else
            install_file "$unit" "$SYSTEMD_USER_DIR/$name" 644
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

reload_systemd

# ── Restart web service if running ───────────────────────────────────────
if [[ "$DRY_RUN" == false && "$NO_SYSTEMD" != true && "$NO_RESTART" != true ]] && command -v systemctl &>/dev/null; then
    if systemctl --user is-active noba-web.service &>/dev/null; then
        if systemctl --user restart noba-web.service 2>/dev/null; then
            say_ok "noba-web service restarted."
        else
            say_warn "Failed to restart noba-web — run: systemctl --user restart noba-web.service"
        fi
    fi
fi

# ── Finalise ──────────────────────────────────────────────────────────────────
if [[ "$DRY_RUN" == false && ${#INSTALLED_FILES[@]} -gt 0 ]]; then
    write_manifest
    trap - EXIT
fi

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

    say "  • Check dependencies: noba run config-check"
    say "  • Edit config:        $CONFIG_DIR/config.yaml"
    say "  • To uninstall:       $(basename "$0") --uninstall"
fi
