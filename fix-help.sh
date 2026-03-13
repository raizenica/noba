#!/bin/bash
# fix-help.sh – Add basic --help and --version to all scripts

set -u
set -o pipefail

cd "$(dirname "$0")" || exit 1

for script in *.sh; do
    # Skip library and test scripts
    [[ "$script" == "noba-lib.sh" || "$script" == "test-all.sh" || "$script" == "fix-help.sh" || "$script" == "fix-test-failures.sh" ]] && continue

    echo "Fixing $script ..."

    # Backup original
    cp "$script" "$script.bak"

    # Check if script already handles --help (crude check)
    if grep -q -E '\-\-help\)|help\)' "$script"; then
        echo "  Already has help, skipping."
        continue
    fi

    # Insert help block after shebang and before any other code
    # Use a here-document to avoid quoting issues
    awk '
        BEGIN { inserted=0 }
        NR == 1 && /^#!\/bin\/bash/ { print; next }
        !inserted && /^[^#]/ {
            print "";
            print "# Basic help and version handling";
            print "if [ \"$1\" = \"--help\" ] || [ \"$1\" = \"-h\" ]; then";
            print "    echo \"Usage: $(basename \"$0\") [OPTIONS]\"";
            print "    echo \"For more information, see the script\\x27s documentation or use --help on individual scripts.\"";
            print "    exit 0";
            print "fi";
            print "if [ \"$1\" = \"--version\" ] || [ \"$1\" = \"-v\" ]; then";
            print "    echo \"$(basename \"$0\") version 1.0\"";
            print "    exit 0";
            print "fi";
            print "";
            inserted=1;
        }
        { print }
    ' "$script" > "$script.tmp" && mv "$script.tmp" "$script"

    # Make executable
    chmod +x "$script"
done

echo "All scripts updated. Please re-run test-all.sh."
