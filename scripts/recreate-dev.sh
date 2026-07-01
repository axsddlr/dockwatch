#!/usr/bin/env bash
set -euo pipefail

echo "==> Pulling latest changes..."
git pull

echo "==> Stopping existing dev container..."
docker compose --profile dev down

echo "==> Rebuilding and recreating dev container..."
docker compose --profile dev up -d --build dockwatch-dev

echo "==> Done. Dashboard at http://localhost:8080"

echo ""
echo "Troubleshooting:"
echo "  - Check logs:     docker compose --profile dev logs dockwatch-dev"
echo "  - Health check:   curl http://localhost:8080/health"
echo "  - Fresh start:    docker compose --profile dev down -v && docker compose --profile dev up -d --build dockwatch-dev"
