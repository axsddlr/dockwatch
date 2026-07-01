#!/usr/bin/env bash
set -euo pipefail

echo "==> Installing dependencies..."
uv pip install -e .

echo ""
echo "==> Starting dockwatch dev server..."
echo "    Dashboard at http://localhost:8082"
echo ""
dockwatch serve --host 0.0.0.0 --port 8082
