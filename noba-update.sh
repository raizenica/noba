#!/bin/bash
# noba-update.sh – Pull latest scripts from git

cd "$HOME/.local/bin" || exit 1
git pull origin main
chmod +x ./*.sh
echo "Updated. Run config-check.sh to verify dependencies."
