#!/usr/bin/env bash
set -euo pipefail

echo "==> Pulling latest changes..."
git pull

echo "==> Rebuilding and recreating dev container..."
docker compose --profile dev up -d --build dockwatch-dev

echo "==> Done. Dashboard at http://localhost:8080"
