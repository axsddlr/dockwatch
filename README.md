# dockwatch

`dockwatch` is a notify-first Docker container update watcher with both:
- a CLI for terminal-first workflows
- a NiceGUI dashboard for browser-based monitoring

It is designed as a practical Watchtower-style replacement where **you are informed first** and stay in control of updates.

## What It Does

- Discovers running Docker containers
- Parses image references (Docker Hub + GHCR, including digest-pinned images)
- Checks registries for newer tags
- Marks containers as `OUTDATED`, `UP-TO-DATE`, `UNKNOWN`, or `PINNED`
- Supports opt-in notifications (`--notify`) via:
  - generic webhook
  - Discord webhook
- Provides web dashboard actions:
  - refresh all
  - check per-row
  - pin/unpin per-row

## Current Status

Implemented:
- Docker Hub + GHCR check pipeline
- CLI commands: `list`, `check`, `version`, `serve`, `pin`, `ignore`, `config list`
- CLI flags: `--container`, `--notify`, `--json`, `--outdated-only`
- NiceGUI dashboard with dark mode + responsive layout
- Config persistence and notification settings UI
- Dockerfile + docker-compose scaffolding
- CI workflow (`ruff`, `mypy`, `pytest`)

In progress / pending:
- Full compose runtime verification requires a running local Docker daemon
- Screenshot assets for README examples

## Installation

### Local Python (editable)

```bash
python -m pip install -e .
```

If installed in your user scripts path, `dockwatch` will be available as a command.

### Docker Compose

```bash
docker compose up -d
```

Dashboard default URL:
- `http://localhost:8080`

## Quick Usage

### List running containers

```bash
dockwatch list
```

### Check for updates

```bash
dockwatch check
```

### Check only one container

```bash
dockwatch check --container nginx
```

### Show only outdated containers

```bash
dockwatch check --outdated-only
```

### JSON output (for scripts)

```bash
dockwatch check --json
```

### Send configured notifications

```bash
dockwatch check --notify
```

### Start dashboard

```bash
dockwatch serve --host 0.0.0.0 --port 8080
```

## CLI Reference

- `dockwatch list`
- `dockwatch check [--container NAME] [--outdated-only] [--json] [--notify]`
- `dockwatch version`
- `dockwatch serve [--host 0.0.0.0] [--port 8080]`
- `dockwatch pin <container>`
- `dockwatch ignore <container>`
- `dockwatch config list`

## Configuration

Default path:
- `~/.config/dockwatch/config.toml`

Example:

```toml
pinned = ["plex"]
ignored = ["db"]
notify_only = []

[notifications]
webhook_url = ""
discord_webhook = ""
```

Notes:
- `pinned`: included in results as `PINNED`
- `ignored`: skipped during checks
- notifier URLs can be managed from CLI config file or dashboard settings card

## Registry Support

| Registry | Status |
| --- | --- |
| Docker Hub | Supported |
| GHCR (`ghcr.io`) | Supported |

## Notifications

Supported notifiers:
- Generic webhook (`POST` JSON)
- Discord webhook (embed payload)

Use `dockwatch check --notify` to send after a check run.

## Docker / Compose Notes

- Container expects Docker socket access.
- On Linux, bind mount: `/var/run/docker.sock:/var/run/docker.sock`
- On Windows, Docker Desktop/npipe access must be available to the environment.

If Docker is unavailable, CLI and dashboard show actionable error messaging.

## Development

### Run tests

```bash
python -m unittest -v tests.test_registry tests.test_config tests.test_notifiers
```

### CI

GitHub Actions workflow (`.github/workflows/ci.yml`) runs:
- `ruff check src tests`
- `mypy src`
- `pytest -q`

## Troubleshooting

### `Could not connect to Docker`

- Ensure Docker daemon/Desktop is running
- Verify permission to Docker socket/pipe
- Re-run `dockwatch check` or refresh dashboard after daemon recovery

### Notifications not sending

- Confirm webhook URL is reachable
- Check dashboard "Send Test Notification" result
- Re-run with `dockwatch check --notify` and inspect notifier errors