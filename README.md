# dockwatch

**A self-hosted Docker update watcher that tells you what's outdated and lets you decide what to do about it.**

Most auto-updaters (Watchtower and friends) pull new images the moment they appear — no review, no confirmation, no history of what changed. dockwatch flips that: it checks your running containers against their registries, tells you (via dashboard or notification) what's outdated, and only updates when you click the button or run the command. You stay in control; dockwatch does the watching.

It ships as a CLI for scripts and cron jobs, and a web dashboard for day-to-day use — same discovery and comparison engine underneath both.

## Table of Contents

- [Why dockwatch](#why-dockwatch)
- [Quick Start](#quick-start)
- [Dashboard Walkthrough](#dashboard-walkthrough)
- [CLI Reference](#cli-reference)
- [Configuration](#configuration)
- [Features](#features)
  - [Update Checking](#update-checking)
  - [Updating Containers](#updating-containers)
  - [Rollback](#rollback)
  - [Update History / Audit Log](#update-history--audit-log)
  - [Digest Drift Alerts](#digest-drift-alerts)
  - [Multi-Arch Images](#multi-arch-images)
  - [Vulnerability Scanning (Trivy)](#vulnerability-scanning-trivy)
  - [Portainer Integration](#portainer-integration)
  - [Authentication & RBAC](#authentication--rbac)
  - [Notifications](#notifications)
- [Docker / Compose Notes](#docker--compose-notes)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [License](#license)

## Why dockwatch

- **You approve every update.** No image is pulled or container recreated unless you click Update or run `dockwatch update`.
- **Digest-aware, not just tag-aware.** A `latest` tag that silently starts pointing at a different image is treated differently than a real version bump — see [Digest Drift Alerts](#digest-drift-alerts).
- **Multi-arch safe.** Outdated/drift detection compares the digest for *your* platform, not a multi-arch manifest list's own digest (which changes whenever any architecture is rebuilt).
- **Auditable.** Every update, rollback, and restart is logged with who did it and when.
- **Works with plain Docker or Portainer.** Local Docker socket, remote Portainer-managed hosts, or both at once.
- **Multi-user from day one.** RBAC with custom roles, not just a single shared login.

## Quick Start

Prerequisites: Docker and Docker Compose. That's it — Trivy (for vulnerability scanning) is bundled in the image.

```bash
git clone <this-repo>
cd dockwatch
cp .env.example .env
```

Edit `.env` — at minimum, set a real password:

```env
DOCKWATCH_USERNAME=admin
DOCKWATCH_PASSWORD=<pick something that isn't the placeholder>
```

Then start it:

```bash
docker compose up -d
```

Dashboard is now at `http://localhost:10801` (or whatever `DOCKWATCH_PORT` you set). Log in with the credentials from `.env` — they're only consumed once, to bootstrap the first admin account.

<details>
<summary>Linux: docker.sock permission (read this if the dashboard shows zero containers)</summary>

The container runs as a non-root user and needs group membership matching whatever group owns `/var/run/docker.sock` on your host. Wrong value fails **silently** — no error, dashboard just looks empty.

```bash
# find your host's docker group GID
getent group docker | cut -d: -f3
```

Put the result in `.env`:

```env
DOCKER_GID=<the GID from above>
```

Docker Desktop (Windows/macOS): the socket inside the VM is owned by root — use `DOCKER_GID=0`.

Recreate the container after changing `.env` — editing the file alone doesn't affect an already-running container:

```bash
docker compose up -d --force-recreate
```
</details>

<details>
<summary>Local Python install (no Docker) — for CLI-only use</summary>

```bash
python -m pip install -e .
dockwatch --help
```

Requires Python 3.11+. The web dashboard (`dockwatch serve`) still needs access to a Docker socket to discover containers.
</details>

## Dashboard Walkthrough

1. **Log in.** First registrant (or the `.env` bootstrap credentials) becomes admin automatically.
2. **Refresh.** Click the refresh button, or it happens automatically at your configured interval — dockwatch discovers running containers and checks each one's registry for a newer tag/digest.
3. **Read the status column.** Each row is `OUTDATED`, `UP-TO-DATE`, `UNKNOWN` (can't determine — usually a floating tag with no digest to compare), or `PINNED`.
4. **Act on a row:**
   - **Update** — pulls the new image and recreates the container (or rewrites the compose file's tag and runs `docker compose up -d` for compose-managed services).
   - **Pin** — exclude a container from being marked outdated, without hiding it.
   - **Scan** — run a Trivy vulnerability scan against the running image.
   - **History** (admin only) — see every update/rollback/restart recorded for that container, with a one-click **Rollback** to the last known-good tag.
5. **Settings page** (requires `manage_settings`) — notification URLs, Portainer connection, Trivy config, and the ignored-containers checklist.
6. **Users page** (requires `manage_users`) — create custom roles, promote/demote users, reset passwords.

## CLI Reference

```
dockwatch list       [--source local|portainer|all] [--environment ID]
dockwatch check      [--container NAME] [--outdated-only] [--major-only]
                      [--json] [--notify] [--source local|portainer|all] [--environment ID]
dockwatch update     <container> [--yes] [--dry-run]
dockwatch scan       [--container NAME] [--json] [--source local|portainer|all] [--environment ID]
dockwatch environments
dockwatch pin        <container>
dockwatch unpin      <container>
dockwatch ignore     <container>
dockwatch unignore   <container>
dockwatch serve      [--host 0.0.0.0] [--port 8080]
dockwatch daemon     [--notify/--no-notify]
dockwatch version
dockwatch config list
dockwatch config set-password
dockwatch notify test
```

Common examples:

```bash
# check everything, show only what's outdated
dockwatch check --outdated-only

# check one container and update it after confirmation
dockwatch check --container nginx
dockwatch update nginx

# see the update plan without executing it
dockwatch update nginx --dry-run

# scan for CVEs
dockwatch scan --container nginx

# JSON output for scripts/cron
dockwatch check --json

# run continuously on a schedule, notify on changes
dockwatch daemon --notify

# include Portainer-managed containers
dockwatch check --source all
```

## Configuration

Config file lives at `~/.config/dockwatch/config.toml` (or the container's `dockwatch_config` volume). The dashboard's Settings page edits the same file.

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

<details>
<summary>Field reference</summary>

- `notify_only` — optional container-name allowlist for notifications
- `include_tags` / `exclude_tags` — regex allow/deny lists applied before latest-tag selection
- `notify_on` — event types that trigger a notification (`new`, `update`); digest drift always notifies regardless of this setting
- `first_check_notify` — whether first-time discovery of a container counts as notifiable
- `schedule_interval_seconds` / `schedule_jitter_seconds` — daemon mode check cadence
- `max_concurrent_checks` — parallel registry check limit
- `portainer.enabled` — turns on the Portainer source in CLI and dashboard
- `portainer.environments` — optional environment ID allowlist; empty means all visible environments
- `trivy.enabled` — must be `true` for scanning to work; opt-in by design (network + CPU cost)
- `trivy.cache_ttl_minutes` — how long a scan result is reused before re-scanning the same image ID

Pinned/ignored containers are stored in SQLite (`container_flags` table), not `config.toml` — manage them via CLI (`dockwatch pin`/`ignore`) or the dashboard checklist.
</details>

Relevant `.env` variables (container deploy only):

| Variable | Purpose |
| --- | --- |
| `DOCKER_GID` | Group ID owning the host's `docker.sock`, so the container's non-root user can read it |
| `DOCKWATCH_PORT` | Host port to publish the dashboard on |
| `DOCKWATCH_USERNAME` / `DOCKWATCH_PASSWORD` | Bootstrap credentials for the first admin account (consumed once) |
| `DOCKWATCH_ALLOW_REGISTRATION` | Allow self-service `/register` after the first account exists |
| `DOCKWATCH_SECURE_COOKIE` | Mark the session cookie `Secure` — only enable behind HTTPS |

## Features

### Update Checking

dockwatch discovers containers (local Docker, Portainer, or both), resolves each image's registry (Docker Hub, GHCR, Codeberg), and compares what's deployed against what's available:

- **Digest comparison** when both local and remote digests are known — the most reliable signal, and the only one that works for floating tags like `latest`.
- **Version comparison** (semver-aware, with linuxserver.io `-lsNN` and distro-suffix `-alpine`/`-slim` handling) when digests aren't available but both tags parse as versions.
- **Tag comparison** as a last resort — if neither digest nor version comparison is possible, dockwatch reports `UNKNOWN` rather than guessing.

### Updating Containers

Clicking **Update** (or `dockwatch update <container>`) does a real update, not just a metadata change:

- **Compose-managed containers** — rewrites the service's `image:` tag in the compose file (if pinned to an exact tag), then runs `docker compose pull <service>` and `docker compose up -d <service>`, scoped to that one service. Sibling services in the same file are untouched.
- **Plain containers** — pulls the new image, then does a full recreate via the Docker SDK (stop → rename to backup → create replacement with the same host/network config → start → remove old). Automatically rolls back to the original container if the replacement fails to start.
- **Floating tags** (`latest`, `edge`, `dev`, `nightly`) — skips tag rewriting, just pulls and recreates, and only proceeds if digest comparison confirmed something actually changed.

### Rollback

Every successful update is remembered. If it turns out to be a bad update, click **Rollback** in the container's history panel (or the dashboard's rollback button) to revert to the last known-good tag — dockwatch reruns the same compose pull/up flow in reverse.

Current scope: **compose-managed containers only**. Plain (non-compose) containers don't have a rollback path yet, since there's no compose file to revert.

### Update History / Audit Log

Every update, rollback, restart, and digest-drift detection is recorded: who did it, when, old tag → new tag, and whether it succeeded. Visible per-container via the History panel (requires `manage_settings`), which also surfaces the Rollback action.

### Digest Drift Alerts

A floating tag like `latest` can silently start pointing at a different image without anyone touching the compose file — the tag string never changes, only the digest behind it. dockwatch treats this as a distinct, always-notified event (`digest_drift`) instead of folding it into an ordinary "update available" notification, so you don't miss a supply-chain-relevant change just because your `notify_on` filter is scoped to something else.

### Multi-Arch Images

Multi-arch images publish a manifest *list* — one entry per platform (amd64, arm64, ...). That list's own digest changes whenever **any** platform is rebuilt, even if the platform you're actually running is untouched. dockwatch resolves your Docker daemon's actual architecture and compares the digest of *that* platform's manifest entry, not the list's own digest — so an arm64 rebuild upstream doesn't falsely flag your amd64 deployment as outdated or drifted. Falls back to the previous list-digest behavior if the daemon is unreachable or your platform isn't present in the list.

### Vulnerability Scanning (Trivy)

Separate from update checks — this inspects the *content* of the image currently running for known CVEs, not whether a newer tag exists.

- Bundled in the Docker image; native/pip installs need [Trivy](https://trivy.dev) installed separately (`brew install trivy` / `apt install trivy`).
- Must be explicitly enabled: `trivy.enabled = true` in config.
- Results are cached by Docker image ID — re-scanning only happens when the image actually changes or the cache TTL expires.
- Dashboard shows clickable severity bars (Critical/High/Medium/Low) that filter the findings list.

```bash
dockwatch scan --container nginx
dockwatch scan --json   # full CVE details: ID, package, installed/fixed version, severity
```

### Portainer Integration

Use Portainer as an additional container source — inspect and check containers on remote Docker hosts without giving dockwatch direct socket access to them.

- **Discovery & checking**: fully supported. Reads environments and containers via the Portainer API (`X-API-Key` header), then runs the normal comparison pipeline against them exactly as it would for local containers.
- **Restart**: supported — proxied through Portainer's Docker API (`POST .../docker/containers/{id}/restart`).
- **Full update (pull + recreate)**: **not yet supported** for Portainer-managed containers — only local Docker containers can be updated in place today. This is the one capability gap between the two sources; tracked as a follow-up.

```bash
dockwatch environments                              # list Portainer environments
dockwatch check --source portainer --environment 2  # check one environment
dockwatch check --source all                        # local + Portainer together
```

### Authentication & RBAC

Multi-user with permission-based access control — five fixed permissions (`view_containers`, `update_containers`, `scan_containers`, `manage_settings`, `manage_users`), combinable into custom roles.

| Built-in role | Permissions |
| --- | --- |
| `admin` | all five |
| `viewer` | `view_containers` only |

Create additional roles with any subset of permissions from the Users page (requires `manage_users`).

**First-run bootstrap** — two options, not mutually exclusive:
1. Set `DOCKWATCH_USERNAME`/`DOCKWATCH_PASSWORD` in `.env` to auto-create the first admin before the dashboard is ever reachable.
2. Leave `.env` credentials unset and register via the web UI — the first registrant always becomes admin, regardless of `DOCKWATCH_ALLOW_REGISTRATION`.

**Do not expose the dashboard to a network you don't control before an admin account exists.** Until the first account is created, `/register` is open to anyone who can reach it — the first visitor becomes admin. Option 1 above closes this window entirely; if you go with option 2, register immediately after starting the container.

After the first account exists, `DOCKWATCH_ALLOW_REGISTRATION=true` allows further self-service sign-ups (assigned `viewer` by default; an admin can reassign their role).

Sessions are signed cookies, 14-day expiry, no server-side session store. Set `DOCKWATCH_SECURE_COOKIE=true` if serving over HTTPS.

**Trust boundary**: `manage_settings` and `update_containers` are effectively admin-equivalent, not safely delegable to a semi-trusted user. Both permissions can reach the host's Docker daemon indirectly — `manage_settings` can point a compose project at an arbitrary path, and `update_containers` can trigger `docker compose up` against it. Only grant these to people you'd trust with direct `docker.sock` access.

### Notifications

Three notifier types, all opt-in:

- Generic webhook (`POST` JSON)
- Discord webhook (embed payload)
- ntfy (`POST` plain text)

Trigger with `dockwatch check --notify`, `dockwatch daemon --notify`, or from the dashboard's "Send Test Notification" button. Digest-drift events always notify regardless of `notify_on` filtering — everything else respects `notify_on`/`notify_only`/`first_check_notify`.

Per-container Docker label overrides (no config file edit needed):

```
dockwatch.enable=false
dockwatch.pin=true
dockwatch.ignore=true
dockwatch.notify=false
dockwatch.include_tags=^2\.
dockwatch.exclude_tags=-rc$
```

## Docker / Compose Notes

- Needs Docker socket access: bind-mount `/var/run/docker.sock` (Linux) or ensure npipe access (Windows Docker Desktop).
- For **compose-managed container updates** to work, the compose project must be registered in Settings (workdir + file paths), and dockwatch's container needs filesystem access to those compose files:
  - **Docker Desktop (Windows/macOS)**: mount `- /:/hostroot` and set `HOST_MOUNT_PREFIX=/hostroot` — dockwatch auto-translates Windows host paths to the Desktop VM's mount convention.
  - **Native Linux**: bind-mount only the specific directories containing your compose stacks (e.g. `/opt/stacks:/opt/stacks`); do **not** mount the whole host root. Leave `HOST_MOUNT_PREFIX` unset.
- The bundled `docker-compose.yml` runs as non-root, includes a healthcheck (`GET /health`), log rotation, resource limits (1 CPU / 512 MB), and `tini` for signal handling.

## Troubleshooting

**Update button missing for a `:latest` container** — floating tags can only be compared by digest. If the registry doesn't return a digest, or the digest matches what's deployed, there's genuinely nothing to update. Pin to a versioned tag (e.g. `image:2.20.0`) for reliable version-based comparison.

**Dashboard shows zero containers** — almost always the `DOCKER_GID` mismatch described in [Quick Start](#quick-start). No error surfaces; discovery just silently returns nothing.

**`Could not connect to Docker`** — confirm the daemon is running and the socket/pipe is reachable from inside the container; re-run the check after the daemon recovers.

**Notifications not sending** — confirm the webhook URL is reachable, use the dashboard's "Send Test Notification," or run `dockwatch check --notify` directly and read the notifier error output.

## Development

```bash
python -m pytest -q       # run tests
ruff check src tests      # lint
mypy src                  # type-check
```

CI (`.github/workflows/ci.yml`) runs all three on every push.

## License

MIT — see [LICENSE](LICENSE).
