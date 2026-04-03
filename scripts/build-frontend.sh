#!/bin/bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
set -e
cd "$(dirname "$0")/../share/noba-web/frontend"
echo "[build] Installing dependencies..."
npm ci --silent
echo "[build] Building Vue frontend..."
npm run build
echo "[build] Done. Output in share/noba-web/static/dist/"
