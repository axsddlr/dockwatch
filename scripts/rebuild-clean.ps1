$ErrorActionPreference = "Stop"

Write-Host "==> Pulling latest changes..."
git pull
if ($LASTEXITCODE -ne 0) { throw "git pull failed" }

Write-Host "==> Tearing down (including volumes)..."
docker compose --profile dev down -v

Write-Host "==> Force clean rebuild..."
docker compose --profile dev build --no-cache dockwatch-dev
if ($LASTEXITCODE -ne 0) { throw "build failed" }

Write-Host "==> Starting dev container..."
docker compose --profile dev up -d dockwatch-dev
if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }

Write-Host "==> Done. Dashboard at http://localhost:8080"
