#!/bin/bash
# fix-all-syntax.sh – Repair empty then clauses and shebang position

set -u
set -o pipefail

for f in *.sh; do
    # Skip the fix script itself
    [[ "$f" == "fix-all-syntax.sh" ]] && continue

    echo "Fixing $f"

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
    #    This looks for a line containing only 'then', followed eventually by a line containing only 'fi'
    #    with only blank or comment lines in between. It inserts 'true' right after the 'then'.
    awk '
        /^[[:space:]]*if / { in_if=1; then_line=0; empty_then=0 }
        in_if && /^[[:space:]]*then[[:space:]]*$/ { then_line=NR; empty_then=1 }
        in_if && then_line && /^[[:space:]]*$/ { next }  # skip blank lines
        in_if && then_line && /^[[:space:]]*#/ { next }  # skip comment lines
        in_if && then_line && /^[[:space:]]*fi/ && empty_then {
            # Insert "true" right after then_line
            cmd = "sed -i \"" then_line + 1 "i\\    true\" \"" FILENAME "\""
            system(cmd)
            in_if=0; empty_then=0
        }
        in_if && then_line && !/^[[:space:]]*$/ && !/^[[:space:]]*#/ { empty_then=0 }  # non-comment non-blank found
        /^[[:space:]]*fi/ { in_if=0; empty_then=0 }
    ' "$f"
done

echo "All fixes applied. Run 'shellcheck *.sh' to verify."
