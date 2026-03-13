# Help handling
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0")"
    echo "This script fixes test failures in other scripts."
    exit 0
fi
# Help handling
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [--help]"
    echo "This script fixes test failures in other scripts."
    exit 0
fi
# Help handling
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0")"
    echo "This script fixes test failures in other scripts."
    exit 0
fi
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [--help]"
    echo "This script fixes test failures in other scripts."
    exit 0
fi
# Help handling
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0")"
    echo "This script fixes test failures in other scripts."
    exit 0
fi
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0")"
    echo "This script fixes test failures in other scripts."
    exit 0
fi
# Help handling
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [--help]"
    echo "This script fixes test failures in other scripts."
    exit 0
fi
# Help handling
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0")"
    echo "This script fixes test failures in other scripts."
    exit 0
fi
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0")"
    echo "This script fixes test failures in other scripts."
    exit 0
fi
# Help handling
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [--help]"
    echo "This script fixes test failures in other scripts."
    exit 0
fi
# Help handling
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0")"
    echo "This script fixes test failures in other scripts."
    exit 0
fi
# Help handling
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0")"
    echo "This script fixes test failures in other scripts."
    exit 0
fi
# Help handling
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [--help]"
    echo "This script fixes test failures in other scripts."
    exit 0
fi
# Help handling
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [--help]"
    echo "This script fixes test failures in other scripts."
    exit 0
fi
#!/bin/bash
# fix-test-failures.sh – Add missing --help/--version and fix dry-run issues

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    # Override defaults with config values (script-specific)
    # Example:
    # VAR=$(get_config ".${script%.sh}.var" "$VAR")
fi

set -u
set -o pipefail

cd "$(dirname "$0")" || exit 1

# Function to add help and version to a script
add_help_and_version() {
    local script="$1"
    local has_lib=false

    # Check if script already sources noba-lib
    if grep -q "source.*noba-lib.sh" "$script"; then
        has_lib=true
    else
        # Add library sourcing if not present (right after shebang)
        sed -i "2i SCRIPT_DIR=\"\$(cd \"\$(dirname \"\${BASH_SOURCE[0]}\")\" && pwd)\"\nsource \"\$SCRIPT_DIR/noba-lib.sh\"" "$script"
    fi

    # Add usage and version functions if missing
    if ! grep -q "show_help()" "$script"; then
        # Insert after library sourcing
        awk -v script="$script" '
            /^source.*noba-lib.sh/ {
                print;
                print "";
                print "show_help() {";
                print "    cat <<EOF";
                print "Usage: $(basename "$0") [OPTIONS]";
                print "";
                print "Options:";
                print "  --help        Show this help message";
                print "  --version     Show version information";
                print "EOF";
                print "    exit 0";
                print "}";
                print "";
                print "show_version() {";
                print "    echo \"$(basename "$0") version 1.0\"";
                print "    exit 0";
                print "}";
                print "";
                next;
            }
            { print }
        ' "$script" > "$script.tmp" && mv "$script.tmp" "$script"
    fi

    # Add argument parsing for --help/--version at the top after functions
    if ! grep -q "\-\-help) *show_help" "$script"; then
        sed -i '/^#.*--help/!b;:a;n;/^[[:space:]]*--help)/!ba;i\
# Parse command-line arguments\
while [[ $# -gt 0 ]]; do\
    case $1 in\
        --help) show_help ;;\
        --version) show_version ;;\
        *) break ;;\
    esac\
    shift\
done\
' "$script"
    fi
}

# Special fix for undo-organizer.sh: make dry-run work even if no log
fix_undo_organizer() {
    local script="undo-organizer.sh"
    if [ -f "$script" ]; then
        # Replace the log check block
        sed -i '/if \[ ! -f "$UNDO_LOG" \] || \[ ! -s "$UNDO_LOG" \]; then/,/fi/c\
if [ ! -f "$UNDO_LOG" ] || [ ! -s "$UNDO_LOG" ]; then\
    if [ "$DRY_RUN" = true ]; then\
        echo "[DRY RUN] No undo log found. Nothing to do."\
        exit 0\
    else\
        echo "No undo log found at $UNDO_LOG"\
        exit 1\
    fi\
fi' "$script"
    fi
}

# List of failing scripts from test output
FAILING_SCRIPTS=(
    "motd-generator.sh"
    "noba-daily-digest.sh"
    "noba-dashboard.sh"
    "noba-setup.sh"
    "system-report.sh"
    "temperature-alert.sh"
)

for script in "${FAILING_SCRIPTS[@]}"; do
    if [ -f "$script" ]; then
        echo "Fixing $script ..."
        add_help_and_version "$script"
    else
        echo "Warning: $script not found"
    fi
done

fix_undo_organizer

echo "Fixes applied. Please re-run test-all.sh."
