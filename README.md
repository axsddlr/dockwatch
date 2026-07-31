# dockwatch

`dockwatch` is a notify-first Docker container update watcher with a CLI for terminal-first workflows and a web dashboard for browser-based monitoring. It is designed as a practical Watchtower-style replacement where **you are informed first** and stay in control of updates.

## What It Does

- Discovers running Docker containers (local Docker, Portainer-managed, or both)
- Parses image references (Docker Hub, GHCR, and Codeberg, including digest-pinned images)
- Checks registries for newer tags
- Marks containers as `OUTDATED`, `UP-TO-DATE`, `UNKNOWN`, or `PINNED`
- Scans running container images for vulnerabilities (CVEs) via Trivy with cached results
- Supports multi-user RBAC with self-service registration, custom roles, and per-route permissions
- Supports opt-in notifications (`--notify`) via generic webhook, Discord webhook, and ntfy
- Persists last-seen manifest state in SQLite to classify first discovery vs later updates
- Supports daemon mode with scheduled checks, jitter, and overlap protection
- Supports Docker label overrides for enable/pin/ignore/notify behavior
- Supports label-based tag regex overrides via `dockwatch.include_tags` and `dockwatch.exclude_tags`
- Adds registry links to notification payloads when a registry page can be derived
- Provides web dashboard actions: refresh all, check/scan/pin/unpin per-row, and Trivy scan with interactive severity filtering

## Current Status

Implemented:
- Docker Hub + GHCR + Codeberg check pipeline
- CLI commands: `list`, `check`, `scan`, `version`, `serve`, `pin`, `unpin`, `ignore`, `unignore`, `config list`, `config set-password`, `environments`
- CLI command: `daemon`
- CLI flags: `--container`, `--notify`, `--json`, `--outdated-only`, `--source`, `--environment`
- FastAPI dashboard with dark mode + responsive layout
- Multi-user RBAC: admin/viewer built-in roles, custom roles, self-service registration, permission-gated UI
- Config persistence, notification settings UI, ignored-containers checklist
- Read-only Portainer integration via API key
- Dockerfile + docker-compose scaffolding, Trivy cache volume, healthcheck
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

### List Portainer-managed containers

```bash
dockwatch list --source portainer
```

### Check for updates

```bash
dockwatch check
```

### Check Portainer-managed containers

```bash
dockwatch check --source portainer
```

### Check both local Docker and Portainer sources

```bash
dockwatch check --source all
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

### Scan for vulnerabilities (Trivy)

```bash
dockwatch scan
dockwatch scan --container nginx
dockwatch scan --json
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

- `dockwatch list [--source local|portainer|all] [--environment ID]`
- `dockwatch check [--container NAME] [--outdated-only] [--json] [--notify] [--source local|portainer|all] [--environment ID]`
- `dockwatch scan [--container NAME] [--json] [--source local|portainer|all] [--environment ID]`
- `dockwatch environments`
- `dockwatch version`
- `dockwatch serve [--host 0.0.0.0] [--port 8080]`
- `dockwatch daemon [--notify/--no-notify]`
- `dockwatch pin <container>`
- `dockwatch unpin <container>`
- `dockwatch ignore <container>`
- `dockwatch unignore <container>`
- `dockwatch config list`
- `dockwatch config set-password` — set or reset dashboard login credentials
- `dockwatch notify test` — send a test notification

## Configuration

Default path:
- `~/.config/dockwatch/config.toml`

Example:

```toml
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

[portainer]
enabled = false
url = ""
api_key = ""
environments = []

[trivy]
enabled = false
binary_path = "trivy"
severity = ["CRITICAL", "HIGH"]
scanners = ["vuln"]
timeout_seconds = 300
skip_db_update = false
cache_ttl_minutes = 60
```

Notes:
- Pinned/ignored containers are persisted in the `container_flags` table of `manifests.db` and managed via CLI (`dockwatch pin`/`unpin`/`ignore`/`unignore`) or the dashboard. They are no longer `config.toml` fields.
  - Pinned containers are included in results as `PINNED`
  - Ignored containers are skipped during checks
  - Legacy `config.toml` pinned/ignored values are migrated to the store on first startup
- `notify_only`: optional container-name allowlist for notifications
- `include_tags`: optional regex allowlist applied before latest-tag selection
- `exclude_tags`: optional regex denylist applied after include filtering
- `notify_on`: event filter for `new` and `update`
- `first_check_notify`: controls whether first discovery (`new`) is allowed to notify
- notifier URLs can be managed from CLI config file or dashboard settings page
- `portainer.enabled`: turns Portainer discovery on for CLI and dashboard source selection
- `portainer.url`: base Portainer URL such as `https://portainer.local:9443`
- `portainer.api_key`: Portainer API key used with the `X-API-Key` header
- `portainer.environments`: optional environment ID allowlist; empty means all visible environments
- `trivy.enabled`: must be `true` for `dockwatch scan` to work; scanning is opt-in
- `trivy.binary_path`: path to the Trivy binary; defaults to `"trivy"` (resolved via PATH)
- `trivy.severity`: severity levels to report (CRITICAL, HIGH, MEDIUM, LOW, UNKNOWN)
- `trivy.scanners`: scanners to run (vuln, secret, misconfig, license)
- `trivy.timeout_seconds`: maximum scan duration per image (min 10)
- `trivy.skip_db_update`: skip `trivy --skip-db-update` to avoid pulling the vulnerability DB
- `trivy.cache_ttl_minutes`: how long cached scan results are reused before re-scanning

## Vulnerability Scanning (Trivy)

`dockwatch` can run [Trivy](https://trivy.dev) vulnerability scans against the images currently running in your containers. This is separate from update checks — it inspects the actual image content for known CVEs, not whether a newer tag exists.

### Prerequisites

**Docker Compose users** — trivy is bundled in the dockwatch image, no extra install needed.

**Native (pip) installs** — install Trivy separately:

```bash
# macOS
brew install trivy

# Linux
sudo apt install trivy
```

Enable scanning in config:

```toml
[trivy]
enabled = true
```

### How it works

1. `dockwatch scan` discovers running containers (same discovery pipeline as `check`)
2. For each container, it looks up the Docker image ID to check the scan cache
3. If no cached result exists or the cache TTL has expired, it runs:
   ```
   trivy image --scanners vuln --severity CRITICAL,HIGH --format json --no-progress <image_ref>
   ```
4. Results are parsed into severity counts (Critical / High / Medium / Low) and individual finding details
5. Results are cached in SQLite by Docker image ID — re-scanning only happens when the image changes or the cache expires

### Cache behavior

- Cache key is the Docker image ID (content-addressable, e.g. `abc123def456`)
- `cache_ttl_minutes` controls how long cached results are reused (default 60 min)
- Pull a new image → new image ID → cache miss → automatic re-scan
- Same image ID → cached result returned instantly

### CLI output

Table view (default):

```
Vulnerability Scan Results
┌────────────────┬──────────┬──────┬────────┬─────┬───────┬────────────┐
│ Image          │ Critical │ High │ Medium │ Low │ Total │ Status     │
├────────────────┼──────────┼──────┼────────┼─────┼───────┼────────────┤
│ nginx:latest   │ 0        │ 2    │ 1      │ 0   │ 3     │ VULNERABLE │
│ alpine:latest  │ 0        │ 0    │ 0      │ 0   │ 0     │ CLEAN      │
└────────────────┴──────────┴──────┴────────┴─────┴───────┴────────────┘
```

JSON view (`--json`) includes full finding details (CVE ID, package, installed/fixed versions, severity, title, URL).

### Limitations

- Trivy must be installed separately — `dockwatch` does not bundle it
- Scanning is CPU and network I/O intensive; the first scan downloads the vulnerability DB
- Only local Docker images are scanned (Portainer-managed containers are scanned via their image reference on the registry)
- Results reflect the image that was running at scan time, not the latest remote tag

## Portainer Integration

`dockwatch` can use Portainer as an additional container source. This lets you inspect and check containers that live in Portainer-managed Docker environments without talking to those remote Docker daemons directly.

What it does today:
- lists available Portainer environments
- discovers containers from one or more Portainer environments
- runs the normal registry check pipeline against those discovered containers
- exposes Portainer as a source in both CLI and dashboard
- lets you narrow checks to a specific environment

How it works:
- `dockwatch` calls the Portainer API using an API key and the `X-API-Key` header
- it reads environments from `GET /api/endpoints`
- it reads containers from `GET /api/endpoints/{id}/docker/containers/json?all=true`
- discovered Portainer containers are normalized into the same internal model used for local Docker checks
- once normalized, the existing digest/version/tag comparison logic runs the same way as local checks

Current limits:
- Portainer support is read-only in the current release
- `dockwatch` does not yet trigger Portainer-native pull, recreate, or update actions
- API key auth is supported; username/password login is not implemented
- Portainer-sourced rows may have less local image digest evidence than direct local Docker inspection, so some results rely more on available version/tag metadata

CLI examples:

```bash
# show Portainer environments
dockwatch environments

# list containers from all configured Portainer environments
dockwatch list --source portainer

# check a single Portainer environment
dockwatch check --source portainer --environment 2

# combine local Docker and Portainer results
dockwatch check --source all
```

Dashboard behavior:
- the Settings page includes Portainer URL, API key, environment filtering, and a `Test Portainer Connection` action
- the dashboard includes a source toggle for `Local Docker`, `Portainer`, and `All`
- when Portainer is active and multiple environments are available, an environment selector appears
- Portainer rows are labeled with their environment so they can be distinguished from local Docker rows

## Registry Support

| Registry | Status |
| --- | --- |
| Docker Hub | Supported |
| GHCR (`ghcr.io`) | Supported |
| Codeberg (`codeberg.org`) | Supported |

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

### How Updates Work with Compose

dockwatch handles multi-service compose files safely. Each service shows as a separate row on the dashboard, and updates are per-service — clicking Update on one container does not touch the others.

For compose-managed containers, the update flow is:

1. **Tag rewrite** — if the service pins an exact tag (not `latest`/`edge`/`dev`), dockwatch rewrites only that service's `image:` line to the new remote tag. Rewriting is scoped by indentation depth, so sibling services are never affected.
2. **Pull + up** — `docker compose pull <service>` and `docker compose up -d <service>` run scoped to that single service. The rest of the stack keeps running.
3. **Floating tags** — for `latest`/`edge`/`dev`/`nightly`, dockwatch skips tag rewriting and just does `pull` + `up -d`, gated by digest comparison (if no newer digest exists, the update is blocked).

Requirements for compose updates to work:

- The compose project must be configured in Settings (workdir path, compose file names).
- dockwatch must be able to reach the compose files from inside its container.
- On Docker Desktop (Windows/macOS): mount `- /:/hostroot` and set `HOST_MOUNT_PREFIX=/hostroot`. Dockwatch auto-translates Windows paths to the VM mount convention.
- On native Linux: do **not** mount the entire host root. Instead, bind-mount only the directories containing your compose stacks:
  ```yaml
  volumes:
    - /opt/stacks:/opt/stacks  # your compose files live here
  ```
  Leave `HOST_MOUNT_PREFIX` unset (or set to empty). Paths recorded by compose labels on Linux are native POSIX paths, so no translation is needed — dockwatch uses them directly.

### DOCKER_GID (docker.sock permission)

The container runs as non-root `appuser` and needs group membership matching
whatever group owns `/var/run/docker.sock` on the host, or every Docker API
call fails with `PermissionError: [Errno 13] Permission denied` and
container discovery silently returns zero containers (no error surfaced —
the dashboard just looks empty).

`docker-compose.yml` adds `appuser` to group `${DOCKER_GID:-105}` via
`group_add`. `105` is a reasonable default for many Linux hosts (the `docker`
group's typical GID), but it isn't universal — set `DOCKER_GID` to match your
host:

```bash
# Linux: find the actual docker group GID
getent group docker | cut -d: -f3

# Docker Desktop for Windows / macOS: the socket inside the VM is
# owned by root, not a "docker" group — use gid 0
DOCKER_GID=0
```

Put the value in `.env` (gitignored) next to `docker-compose.yml`:

```
DOCKER_GID=0
```

Then recreate the container so `group_add` picks it up — a config change
alone (editing `.env`) does not affect an already-running container.

### Running

```bash
# Production (dashboard + API on host port 10801)
docker compose up -d dockwatch

# Use an alternate host port if 10801 is already allocated
DOCKWATCH_PORT=18082 docker compose up -d dockwatch
```

### Compose features

- **Non-root user**: container runs as `appuser`, not root.
- **Healthcheck**: `GET /health` endpoint polled every 30s.
- **Resource limits**: 1 CPU / 512 MB.
- **Log rotation**: JSON-file driver, 10 MB per file, 3-file cap.
- **Init process**: `tini` via `init: true` for proper signal handling and zombie reaping.
- Config volume persists at `/home/appuser/.config/dockwatch`.
- Trivy cache volume persists at `/home/appuser/.cache/trivy` (survives container recreates).

If Docker is unavailable, CLI and dashboard show actionable error messaging.

## Authentication & RBAC

dockwatch supports single-user auth and multi-user RBAC with self-service registration.

### Built-in Roles

| Role | Permissions |
| --- | --- |
| admin | Full access: dashboard, settings, users, pin/unpin, update, Trivy scan |
| viewer | Read-only: view dashboard, no mutations |

Custom roles can be created from the Users page with any combination of permissions (`manage_settings`, `manage_users`, `pin_container`, `update_container`, `scan_container`).

### Registration

Self-service registration is gated by an env var:

```env
DOCKWATCH_ALLOW_REGISTRATION=true
```

When enabled, new users register via the `/register` page and are assigned the `viewer` role. An admin can then promote them or assign a custom role. When the users table is empty (fresh install), the first registrant always becomes admin regardless of the env var — so initial setup needs no manual user seeding beyond the first login.

### First-run Bootstrap

On a fresh install the users table is empty. You have two options:

1. Register via the web UI — first registrant becomes admin.
2. Set `DOCKWATCH_USERNAME`/`DOCKWATCH_PASSWORD` in `.env` to auto-create an admin user on first start. These env vars are only consumed once; after that, the user table (not `.env`) is the source of truth.

### Changing Passwords

```bash
docker compose exec dockwatch dockwatch config set-password
```

The command prompts for username and new password interactively. Only users with `manage_users` permission can change passwords via the dashboard Users page.

### Legacy Auth Config

If you've been using dockwatch before RBAC was added, your single-user credentials from `config.toml` are automatically migrated into the users table on startup. The legacy `[auth]` section in `config.toml` is then unused — all credentials are managed through the SQLite users store thereafter.

### Dashboard Login (Credentials)

The dashboard requires login. Until credentials are configured, every API route returns 401 and the dashboard cannot be used.

Sessions last 14 days (signed cookie, no server-side session store) and end early via the dashboard's logout button. The session cookie is not marked `Secure`, since this tool is commonly reached over plain HTTP on a LAN — if you're exposing it over the internet, put a TLS-terminating reverse proxy in front of it.

## Development

### Run tests

```bash
python -m pytest -q
```

### CI

GitHub Actions workflow (`.github/workflows/ci.yml`) runs:
- `ruff check src tests`
- `mypy src`
- `pytest -q`

## Troubleshooting

### Updates not available for `:latest` containers

Containers using `:latest` (or `:edge`, `:dev`, `:nightly`) can only be checked via digest comparison — there's no version number to compare. If the registry doesn't return a digest, or the digest matches what's already running, the Update button won't appear even if a newer image exists upstream.

**Fix**: pin to a versioned tag (e.g., `ghcr.io/advplyr/audiobookshelf:2.20.0` instead of `:latest`). dockwatch can then compare versions numerically and rewrite the tag on update.

### `Could not connect to Docker`

- Ensure Docker daemon/Desktop is running
- Verify permission to Docker socket/pipe
- Re-run `dockwatch check` or refresh dashboard after daemon recovery

### Notifications not sending

- Confirm webhook URL is reachable
- Check dashboard "Send Test Notification" result
- Re-run with `dockwatch check --notify` and inspect notifier errors
