$ErrorActionPreference = "Stop"

Write-Host "==> Installing dependencies..."
uv pip install -e .
if ($LASTEXITCODE -ne 0) { throw "install failed" }

Write-Host ""
Write-Host "==> Starting dockwatch dev server..."
Write-Host "    Dashboard at http://localhost:8080"
Write-Host ""
dockwatch serve --host 0.0.0.0 --port 8080
