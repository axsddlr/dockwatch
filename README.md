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
  - ntfy
- Persists last-seen manifest state in SQLite to classify first discovery vs later updates
- Supports daemon mode with scheduled checks, jitter, and overlap protection
- Supports Docker label overrides for enable/pin/ignore/notify behavior
- Supports label-based tag regex overrides via `dockwatch.include_tags` and `dockwatch.exclude_tags`
- Adds registry links to notification payloads when a registry page can be derived
- Provides web dashboard actions:
  - refresh all
  - check per-row
  - pin/unpin per-row

## Current Status

Implemented:
- Docker Hub + GHCR check pipeline
- CLI commands: `list`, `check`, `version`, `serve`, `pin`, `ignore`, `config list`
- CLI command: `daemon`
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

### Run scheduled daemon mode

```bash
dockwatch daemon --notify
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
- `dockwatch daemon [--notify/--no-notify]`
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
include_tags = []
exclude_tags = []
notify_on = ["update"]
first_check_notify = false
schedule_interval_seconds = 300
schedule_jitter_seconds = 30
run_on_startup = true
max_concurrent_checks = 5

[notifications]
webhook_url = ""
discord_webhook = ""
ntfy_url = ""
```

Notes:
- `pinned`: included in results as `PINNED`
- `ignored`: skipped during checks
- `notify_only`: optional container-name allowlist for notifications
- `include_tags`: optional regex allowlist applied before latest-tag selection
- `exclude_tags`: optional regex denylist applied after include filtering
- `notify_on`: event filter for `new` and `update`
- `first_check_notify`: controls whether first discovery (`new`) is allowed to notify
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
- ntfy (`POST` message)

Use `dockwatch check --notify` to send after a check run.

Docker label overrides:
- `dockwatch.enable`
- `dockwatch.pin`
- `dockwatch.ignore`
- `dockwatch.notify`
- `dockwatch.include_tags`
- `dockwatch.exclude_tags`

## Docker / Compose Notes

- Container expects Docker socket access.
- On Linux, bind mount: `/var/run/docker.sock:/var/run/docker.sock`
- On Windows, Docker Desktop/npipe access must be available to the environment.

If Docker is unavailable, CLI and dashboard show actionable error messaging.

## Development

### Run tests

```bash
python -m unittest discover -s tests -v
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
