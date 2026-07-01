$ErrorActionPreference = "Stop"

Write-Host "==> Pulling latest changes..."
git pull
if ($LASTEXITCODE -ne 0) { throw "git pull failed" }

Write-Host "==> Rebuilding and recreating dev container..."
docker compose --profile dev up -d --build dockwatch-dev
if ($LASTEXITCODE -ne 0) { throw "docker compose failed" }

Write-Host "==> Done. Dashboard at http://localhost:8080"
