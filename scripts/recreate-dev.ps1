$ErrorActionPreference = "Stop"

Write-Host "==> Pulling latest changes..."
git pull
if ($LASTEXITCODE -ne 0) { throw "git pull failed" }

Write-Host "==> Stopping existing dev container..."
docker compose --profile dev down
if ($LASTEXITCODE -ne 0) { Write-Warning "down failed (may not be running)" }

Write-Host "==> Rebuilding and recreating dev container..."
docker compose --profile dev up -d --build dockwatch-dev
if ($LASTEXITCODE -ne 0) { throw "docker compose failed" }

Write-Host "==> Done. Dashboard at http://localhost:8080"
Write-Host ""
Write-Host "Troubleshooting:"
Write-Host "  - Check logs:     docker compose --profile dev logs dockwatch-dev"
Write-Host "  - Health check:   curl http://localhost:8080/health"
Write-Host "  - Fresh start:    docker compose --profile dev down -v; docker compose --profile dev up -d --build dockwatch-dev"
