#!/bin/bash
# fix-help-v2.sh – Add proper --help handling to all scripts

set -u
set -o pipefail

cd "$(dirname "$0")" || exit 1

for script in *.sh; do
    # Skip library and helper scripts
    [[ "$script" == "noba-lib.sh" || "$script" == "test-all.sh" || "$script" == "fix-"* ]] && continue

    echo "Checking $script ..."

    # Backup original
    cp "$script" "$script.bak"

    # Check if script uses getopt
    if grep -q "getopt" "$script"; then
        echo "  Uses getopt – ensuring --help is included"
        # Look for getopt option string
        optstring=$(grep -oP "getopt -o ['\"]?\K[^'\"]+" "$script" | head -1)
        if [[ -n "$optstring" && "$optstring" != *h* ]]; then
            # Add 'h' to short options
            sed -i "s/getopt -o ['\"]$optstring['\"]/getopt -o '${optstring}h'/" "$script"
            # Add long option --help if not present
            if ! grep -q "help" "$script"; then
                # Find the getopt line and add help to longopts
                sed -i '/getopt -o/ s/--long /--long help,/; s/--long /--long help,/' "$script"
            fi
            # Add case entry for --help if missing
            if ! grep -q -E '\-\-help\)' "$script"; then
                awk '/case "\$1" in/ { print; print "        --help) usage ;;"; next }1' "$script" > "$script.tmp"
                mv "$script.tmp" "$script"
            fi
        fi
    else
        echo "  Simple script – adding help block"
        # Add help block after shebang and before any code
        awk 'NR==1 && /^#!/ { print; next } !help_added && /^[^#]/ { print ""; print "# Help handling"; print "if [ \"$1\" = \"--help\" ] || [ \"$1\" = \"-h\" ]; then"; print "    echo \"Usage: $(basename \"$0\") [OPTIONS]\""; print "    echo \"For detailed help, see the script documentation.\""; print "    exit 0"; print "fi"; print "if [ \"$1\" = \"--version\" ] || [ \"$1\" = \"-v\" ]; then"; print "    echo \"$(basename \"$0\") version 1.0\""; print "    exit 0"; print "fi"; print ""; help_added=1 } { print }' "$script" > "$script.tmp"
        mv "$script.tmp" "$script"
    fi

    chmod +x "$script"
done

echo "Fixes applied. Please re-run test-all.sh."
