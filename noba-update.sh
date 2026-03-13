#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"
# noba-update.sh – Pull latest scripts from git

cd "$HOME/.local/bin" || exit 1
git pull origin main
chmod +x ./*.sh
echo "Updated. Run config-check.sh to verify dependencies."
