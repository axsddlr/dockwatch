#!/usr/bin/env bash
set -euo pipefail

echo "==> Pulling latest changes..."
git pull

echo "==> Tearing down (including volumes)..."
docker compose --profile dev down -v --remove-orphans

echo "==> Force clean rebuild of dev API image..."
docker compose --profile dev build --no-cache dockwatch-dev-api

echo "==> Starting dev API and hot-reload frontend..."
docker compose --profile dev up -d --remove-orphans dockwatch-dev-api dockwatch-dev-frontend

echo "==> Done."
echo "    Frontend: http://localhost:${DOCKWATCH_DEV_FRONTEND_PORT:-5173}"
echo "    API:      http://localhost:${DOCKWATCH_DEV_API_PORT:-18080}"
echo ""
echo "Troubleshooting:"
echo "  - Frontend logs: docker compose --profile dev logs -f dockwatch-dev-frontend"
echo "  - API logs:      docker compose --profile dev logs -f dockwatch-dev-api"
echo "  - Health check:  curl http://localhost:${DOCKWATCH_DEV_API_PORT:-18080}/health"
