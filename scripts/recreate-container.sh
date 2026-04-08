#!/usr/bin/env bash
set -euo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(CDPATH= cd -- "${script_dir}/.." && pwd)"

cd "$repo_root"

if [[ "${1:-}" == "--pull" ]]; then
  git pull --ff-only
fi

docker compose -f docker-compose.yml up -d --build --force-recreate
