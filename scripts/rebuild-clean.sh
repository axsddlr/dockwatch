#!/usr/bin/env bash
set -euo pipefail

echo "==> Pulling latest changes..."
git pull

echo "==> Tearing down (including volumes)..."
docker compose --profile dev down -v

echo "==> Force clean rebuild..."
docker compose --profile dev build --no-cache dockwatch-dev

echo "==> Starting dev container..."
docker compose --profile dev up -d dockwatch-dev

echo "==> Done. Dashboard at http://localhost:8080"
