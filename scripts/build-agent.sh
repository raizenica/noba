#!/usr/bin/env bash
# Build the NOBA agent zipapp (agent.pyz) from share/noba-agent/
# Usage: bash scripts/build-agent.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
AGENT_SRC="$REPO_ROOT/share/noba-agent"
OUTPUT="$REPO_ROOT/share/noba-agent.pyz"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

echo "[build-agent] Building $OUTPUT from $AGENT_SRC ..."

# Verify __main__.py exists
if [[ ! -f "$AGENT_SRC/__main__.py" ]]; then
    echo "[build-agent] ERROR: $AGENT_SRC/__main__.py not found" >&2
    exit 1
fi

# Copy only Python source files to staging dir (excludes installers, service files, __pycache__)
find "$AGENT_SRC" -maxdepth 1 -name "*.py" -exec cp {} "$TMP_DIR/" \;

python3 -m zipapp "$TMP_DIR" \
    -o "$OUTPUT" \
    -p "/usr/bin/env python3"

chmod +x "$OUTPUT"
# Also place a copy alongside install-agent.sh so manual installs work
cp "$OUTPUT" "$AGENT_SRC/agent.pyz"
echo "[build-agent] Done: $OUTPUT ($(du -sh "$OUTPUT" | cut -f1))"
python3 "$OUTPUT" --version
