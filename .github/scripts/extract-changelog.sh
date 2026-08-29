#!/usr/bin/env bash
# Extracts the CHANGELOG.md section for one version (e.g. "0.8.0") and
# prints it to stdout. Used by the release workflow as the GitHub Release
# body, so a tag push reuses the hand-written changelog instead of an
# auto-generated commit list.
set -euo pipefail

version="$1"
changelog="${2:-CHANGELOG.md}"

awk -v ver="## [$version]" '
  index($0, ver) == 1 { found=1; print; next }
  found && /^## \[/ { exit }
  found { print }
' "$changelog"
