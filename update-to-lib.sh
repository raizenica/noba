#!/bin/bash
# update-to-lib.sh – Convert all scripts to use noba-lib.sh

set -u
set -o pipefail

cd "$(dirname "$0")" || exit 1

LIB_FILE="noba-lib.sh"
SCRIPTS=(*.sh)

# First, ensure lib exists
if [ ! -f "$LIB_FILE" ]; then
    echo "ERROR: $LIB_FILE not found in current directory." >&2
    exit 1
fi

for script in "${SCRIPTS[@]}"; do
    # Skip the lib itself and this update script
    [[ "$script" == "noba-lib.sh" || "$script" == "update-to-lib.sh" ]] && continue

    echo "Processing $script ..."

    # Create a backup
    cp "$script" "$script.bak"

    # Remove old automation.conf sourcing lines
    sed -i '/source.*automation\.conf/d' "$script"

    # Add sourcing of noba-lib after shebang (if not already present)
    if ! grep -q "source.*noba-lib.sh" "$script"; then
        sed -i "2i SCRIPT_DIR=\"\$(cd \"\$(dirname \"\${BASH_SOURCE[0]}\")\" && pwd)\"\nsource \"\$SCRIPT_DIR/$LIB_FILE\"" "$script"
    fi

    # Insert a generic config loader block after the shebang+source
    # We'll look for the first blank line or the start of functions
    # This is simplistic; manual review may be needed.
    awk -v script="$script" '
        BEGIN { print "Processing " script }
        /^#!\/bin\/bash/ { print; next }
        /^SCRIPT_DIR=.*source.*noba-lib/ { print; next }
        !done && /^$/ {
            print ""
            print "# Load configuration"
            print "load_config"
            print "if [ \"\$CONFIG_LOADED\" = true ]; then"
            print "    # Override defaults with config values (script-specific)"
            print "    # Example:"
            print "    # VAR=\$(get_config \".${script%.sh}.var\" \"\$VAR\")"
            print "fi"
            print ""
            done=1
            next
        }
        { print }
    ' "$script" > "$script.tmp" && mv "$script.tmp" "$script"

    echo "Updated $script (backup saved as $script.bak)"
done

echo "All scripts processed. Please review changes and test."
