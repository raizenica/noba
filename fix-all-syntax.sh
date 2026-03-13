#!/bin/bash
# fix-all-syntax.sh – Repair empty then clauses and shebang position

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

show_version() {
    echo "fix-all-syntax.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Automatically fix common syntax issues in all .sh scripts:
  - Move shebang to line 1
  - Insert 'true' after empty 'then' clauses

Options:
  --help        Show this help message
  --version     Show version information
EOF
    exit 0
}

if [ $# -gt 0 ]; then
    case "$1" in
        --help)    show_help ;;
        --version) show_version ;;
        *)         log_error "Unknown option: $1"; show_help ;;
    esac
fi

for f in *.sh; do
    # Skip the fix script itself
    [[ "$f" == "fix-all-syntax.sh" ]] && continue

    log_info "Fixing $f"

    # 1. Move shebang to line 1 (if needed)
    if ! head -1 "$f" | grep -q '^#!'; then
        # Find the line number of the first shebang
        shebang_line=$(grep -n '^#!' "$f" | head -1 | cut -d: -f1)
        if [ -n "$shebang_line" ]; then
            # Extract shebang and rest of file
            {
                sed -n "${shebang_line}p" "$f"
                sed -n "$((shebang_line+1)),\$p" "$f"
            } > "$f.tmp" && mv "$f.tmp" "$f"
        fi
    fi

    # 2. Fix empty then clauses by adding a no-op 'true' before each 'fi'
    awk '
        /^[[:space:]]*if / { in_if=1; then_line=0; empty_then=0 }
        in_if && /^[[:space:]]*then[[:space:]]*$/ { then_line=NR; empty_then=1 }
        in_if && then_line && /^[[:space:]]*$/ { next }
        in_if && then_line && /^[[:space:]]*#/ { next }
        in_if && then_line && /^[[:space:]]*fi/ && empty_then {
            cmd = "sed -i \"" then_line + 1 "i\\    true\" \"" FILENAME "\""
            system(cmd)
            in_if=0; empty_then=0
        }
        in_if && then_line && !/^[[:space:]]*$/ && !/^[[:space:]]*#/ { empty_then=0 }
        /^[[:space:]]*fi/ { in_if=0; empty_then=0 }
    ' "$f"
done

log_success "All fixes applied. Run 'shellcheck *.sh' to verify."
