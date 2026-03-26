#!/usr/bin/env bash
# Build the NOBA agent zipapp (agent.pyz) from share/noba-agent/
# Usage: bash scripts/build-agent.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
AGENT_DIR="$REPO_ROOT/share/noba-agent"
OUTPUT="$REPO_ROOT/share/noba-agent.pyz"

echo "[build-agent] Building $OUTPUT from $AGENT_DIR ..."

# Verify __main__.py exists
if [[ ! -f "$AGENT_DIR/__main__.py" ]]; then
    echo "[build-agent] ERROR: $AGENT_DIR/__main__.py not found" >&2
    exit 1
fi

python3 -m zipapp "$AGENT_DIR" \
    --output "$OUTPUT" \
    --python "/usr/bin/env python3"

chmod +x "$OUTPUT"
echo "[build-agent] Done: $OUTPUT"
python3 "$OUTPUT" --version
