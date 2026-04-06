# dockwatch

Docker container update watcher with a CLI and NiceGUI dashboard.

`dockwatch` is a notify-first alternative to auto-updaters: it inspects running container image tags, checks registries for newer tags, and lets you decide what to update.

## Why this exists

- Watchtower-style convenience without forced auto-restarts
- Simple commands for home-lab users
- Optional browser dashboard and notifications

## Quick Start

### CLI (local Python)

```bash
python -m pip install -e .
dockwatch list
dockwatch check
dockwatch check --outdated-only
dockwatch check --json
```

### Docker Compose

```bash
docker compose up -d
```

Dashboard: `http://localhost:8080`

## CLI Commands

- `dockwatch list` — list running containers and current image tags
- `dockwatch check [--container NAME] [--outdated-only] [--json] [--notify]`
- `dockwatch pin <container>` — mark as pinned
- `dockwatch ignore <container>` — exclude from checks
- `dockwatch config list` — show pinned/ignored/notifier config
- `dockwatch serve [--host 0.0.0.0] [--port 8080]` — start web dashboard

## Config File

Path: `~/.config/dockwatch/config.toml`

```toml
pinned = ["plex"]
ignored = ["db"]
notify_only = []

[notifications]
webhook_url = ""
discord_webhook = ""
```

## Supported Registries

| Registry | Status |
| --- | --- |
| Docker Hub | Supported |
| GitHub Container Registry (`ghcr.io`) | Supported |

## CI

GitHub Actions workflow runs:
- `ruff` lint
- `mypy` type checking
- `pytest` unit tests