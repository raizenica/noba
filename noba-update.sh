#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"
# noba-update.sh – Pull latest scripts from git

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    true
    # Override defaults with config values (script-specific)
    # Example:
    # VAR=$(get_config ".${script%.sh}.var" "$VAR")
fi

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    true
    # Override defaults with config values (script-specific)
    # Example:
    # VAR=$(get_config ".${script%.sh}.var" "$VAR")
fi

cd "$HOME/.local/bin" || exit 1
git pull origin main
chmod +x ./*.sh
echo "Updated. Run config-check.sh to verify dependencies."
