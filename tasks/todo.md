# dockpkgWatch — Phased Build Plan

> Docker container update watcher with CLI + NiceGUI web dashboard.
> Notify-first, user-controlled updates. Replacement for archived Watchtower.
> Stack: Python 3.11+, Typer, docker-py, httpx, Rich, NiceGUI.

---

## Phase 1 — Project Scaffold & Core Models

> Goal: Installable Python package with correct structure. No logic yet.

- [x] Create `pyproject.toml` with all dependencies (`typer`, `docker`, `httpx`, `rich`, `nicegui`, `packaging`)
- [x] Create `src/dockwatch/__init__.py` (package root, expose version)
- [x] Create `src/dockwatch/models.py`
  - [x] `ContainerInfo` dataclass: `name`, `container_id`, `image_ref`, `registry`, `namespace`, `image_name`, `current_tag`
  - [x] `UpdateResult` dataclass: `container_info`, `latest_tag`, `is_outdated`, `check_error`
  - [x] `RegistryType` enum: `DOCKERHUB`, `GHCR`, `UNKNOWN`
- [x] Verify `uv pip install -e .` succeeds with no errors
- [x] Verify `python -c "import dockwatch"` works

---

## Phase 2 — Docker Client

> Goal: Read running containers from Docker socket and parse image references.

- [x] Create `src/dockwatch/docker_client.py`
  - [x] `get_running_containers() -> list[ContainerInfo]` — connect via `docker.from_env()`, call `client.containers.list()`
  - [x] `parse_image_ref(image_str: str) -> ContainerInfo` — parse `container.attrs['Config']['Image']`
    - [x] Handle Docker Hub official images (`nginx`, `library/nginx`)
    - [x] Handle Docker Hub user images (`linuxserver/plex`)
    - [x] Handle GHCR images (`ghcr.io/owner/image:tag`)
    - [x] Handle digest-pinned images (`image@sha256:...`) → mark tag as `DIGEST_PINNED`
    - [x] Handle missing/implicit `latest` tag
  - [x] Raise `DockerConnectionError` with helpful message if socket unavailable
- [x] Manual smoke test: run `python -c "from dockwatch.docker_client import get_running_containers; print(get_running_containers())"`

---

## Phase 3 — Registry Checker

> Goal: Async check of Docker Hub and GHCR for latest available tags.

- [x] Create `src/dockwatch/registry.py`
  - [x] `check_container(info: ContainerInfo) -> UpdateResult` — async, routes to correct registry checker
  - [x] `check_dockerhub(info: ContainerInfo) -> UpdateResult`
    - [x] Official images: `GET https://hub.docker.com/v2/repositories/library/{image}/tags?page_size=20&ordering=last_updated`
    - [x] User images: `GET https://hub.docker.com/v2/repositories/{namespace}/{image}/tags?page_size=20&ordering=last_updated`
    - [x] Parse response: find latest semantic version tag (use `packaging.version.Version` for comparison)
    - [x] Skip `latest`, `edge`, `dev`, `nightly` floating tags when finding "latest version"
    - [x] Fall back to most-recently-updated tag if no semver tags found
  - [x] `check_ghcr(info: ContainerInfo) -> UpdateResult`
    - [x] Anonymous token: `GET https://ghcr.io/token?scope=repository:{namespace}/{image}:pull`
    - [x] Tags list: `GET https://ghcr.io/v2/{namespace}/{image}/tags/list` with Bearer token
  - [x] `check_all(containers: list[ContainerInfo]) -> list[UpdateResult]` — `asyncio.gather()` all checks concurrently
  - [x] Error handling: registry unreachable or 404 → return `UpdateResult` with `check_error` set, not exception
  - [x] Skip check and mark UNKNOWN for `DIGEST_PINNED` and `latest`-only containers
- [x] Unit test: mock httpx responses for dockerhub and ghcr endpoints

---

## Phase 4 — CLI Commands

> Goal: Working `dockwatch` CLI with `list` and `check` commands.

- [x] Create `src/dockwatch/display.py`
  - [x] `render_containers_table(containers: list[ContainerInfo])` — Rich Table: Name / Image / Tag / Registry
  - [x] `render_update_table(results: list[UpdateResult])` — Rich Table: Name / Current / Latest / Status
    - [x] Status colors: red=OUTDATED, green=UP-TO-DATE, yellow=UNKNOWN
  - [x] `render_summary(results: list[UpdateResult])` — "X outdated, Y up-to-date, Z unknown"
- [x] Create `src/dockwatch/main.py` — Typer app
  - [x] `dockwatch list` — show all running containers (calls `get_running_containers`, renders table)
  - [x] `dockwatch check [--container NAME]` — check all or single container; renders update table + summary
  - [x] `dockwatch version` — print version
  - [x] Global `--help` with description and usage examples
- [x] Wire CLI entry point in `pyproject.toml`: `dockwatch = "dockwatch.main:app"`
- [x] End-to-end test:
  - [x] `dockwatch --help` shows commands
  - [x] `dockwatch list` shows running containers in table
  - [x] `dockwatch check` shows update status for all containers
  - [x] `dockwatch check --container nginx` checks single container

---

## Phase 5 — NiceGUI Web Dashboard

> Goal: Browser-based dashboard at `http://localhost:8080` showing container update status.

- [x] Create `src/dockwatch/web/` package
  - [x] `src/dockwatch/web/__init__.py`
  - [x] `src/dockwatch/web/app.py` — NiceGUI app entry point
  - [x] `src/dockwatch/web/pages/dashboard.py` — main dashboard page
  - [x] `src/dockwatch/web/components/container_table.py` — reusable container status table component
- [x] Dashboard page features
  - [x] Header: app name, version, last-checked timestamp
  - [x] Container status table: Name / Image / Current Tag / Latest Tag / Status / Actions
  - [x] Status badges: color-coded (red/green/yellow)
  - [x] "Refresh" button — re-runs `check_all()` and updates table live
  - [x] Per-row "Check" button — checks individual container
  - [x] Auto-refresh toggle with configurable interval (default: off)
- [x] Add `dockwatch serve [--port 8080] [--host 0.0.0.0]` CLI command to launch web server
- [x] Verify NiceGUI and Typer CLI coexist in same package without conflicts
- [x] End-to-end test:
  - [x] `dockwatch serve` opens browser, dashboard loads
  - [x] Table shows correct container data
  - [x] Refresh button updates data without page reload
  - [x] Works on `localhost` and LAN IP

---

## Phase 6 — Config File (Pin / Ignore)

> Goal: Per-container rules stored in `~/.config/dockwatch/config.toml`.

- [x] Create `src/dockwatch/config.py`
  - [x] `load_config() -> DockwatchConfig` — reads from `~/.config/dockwatch/config.toml`, creates default if missing
  - [x] `DockwatchConfig` dataclass: `pinned: list[str]`, `ignored: list[str]`, `notify_only: list[str]`
  - [x] `save_config(config: DockwatchConfig)` — writes back to TOML
- [x] `dockwatch pin <container>` CLI command — adds to `pinned` list
- [x] `dockwatch ignore <container>` CLI command — adds to `ignored` list
- [x] `dockwatch config list` — show current pinned/ignored containers
- [x] Integrate config into `check_all()`: skip ignored containers, mark pinned as PINNED status
- [x] Show PINNED status in both CLI table and NiceGUI dashboard (distinct color/badge)
- [x] Pin / Unpin button in NiceGUI dashboard per container row

---

## Phase 7 — Notifications

> Goal: Push alerts when outdated containers are found (opt-in).

- [ ] Create `src/dockwatch/notifiers/` package
  - [ ] `src/dockwatch/notifiers/__init__.py`
  - [ ] `src/dockwatch/notifiers/base.py` — `BaseNotifier` abstract class with `send(results)` method
  - [ ] `src/dockwatch/notifiers/webhook.py` — generic HTTP webhook (POST JSON payload)
  - [ ] `src/dockwatch/notifiers/discord.py` — Discord webhook embed format
- [ ] Add notifier config to `config.toml`: `[notifications] webhook_url = "..."`, `discord_webhook = "..."`
- [ ] `dockwatch check --notify` flag — sends notifications after checking
- [ ] Notification settings page in NiceGUI dashboard (webhook URL input, test button)
- [ ] Test Discord and generic webhook with live endpoints

---

## Phase 8 — Docker Compose & Distribution

> Goal: Ship as a Docker image and provide a ready-to-use `docker-compose.yml`.

- [ ] Create `Dockerfile`
  - [ ] Multi-stage build: build deps → slim runtime image
  - [ ] Mount Docker socket: `volumes: ["/var/run/docker.sock:/var/run/docker.sock"]`
  - [ ] Expose port 8080 for NiceGUI dashboard
  - [ ] Default `CMD`: `dockwatch serve --host 0.0.0.0 --port 8080`
- [ ] Create `docker-compose.yml` example for users
  - [ ] Service: `dockwatch`, image, socket mount, port mapping, restart policy
  - [ ] Volume for config persistence: `~/.config/dockwatch`
- [ ] Create `.dockerignore`
- [ ] Test: `docker compose up` starts dashboard accessible at `http://localhost:8080`
- [ ] Publish to Docker Hub: `andresaddler/dockwatch` (or chosen namespace)
- [ ] Tag `v0.1.0` release on GitHub

---

## Phase 9 — Polish & Docs

> Goal: Production-ready for home-lab users. Clear docs, good UX.

- [ ] Write `README.md`
  - [ ] What it does / why it exists (Watchtower replacement)
  - [ ] Quick start: Docker Compose one-liner
  - [ ] CLI usage examples with output screenshots
  - [ ] Config file reference
  - [ ] Supported registries table
- [ ] Add `--json` output flag to `dockwatch check` for scripting/piping
- [ ] Add `dockwatch check --outdated-only` flag — show only containers with updates
- [ ] NiceGUI dashboard: dark mode support
- [ ] NiceGUI dashboard: mobile-responsive layout
- [ ] Error page in dashboard when Docker socket is unavailable (with fix instructions)
- [ ] Add GitHub Actions CI: lint (ruff), type check (mypy), unit tests (pytest)

---

## Phase 10 — ntfy Notification Support

> Goal: Push notifications via ntfy.sh (self-hosted or public) for update alerts.

- [ ] Create `src/dockwatch/notifiers/ntfy.py`
  - [ ] `NtfyNotifier(BaseNotifier)` — POST to `https://{server}/{topic}` with update summary
  - [ ] Support both public `ntfy.sh` and self-hosted ntfy instances
  - [ ] Configurable priority levels: map OUTDATED → `high`, UNKNOWN → `default`
  - [ ] Include action buttons in notification: "Open Dashboard" URL, "View on Docker Hub" URL
  - [ ] Support ntfy auth tokens for private topics (`Authorization: Bearer <token>`)
- [ ] Add ntfy config to `config.toml`:
  ```toml
  [notifications.ntfy]
  enabled = true
  server = "https://ntfy.sh"    # or self-hosted URL
  topic = "dockwatch"
  token = ""                     # optional, for private topics
  priority = "high"              # default priority for outdated alerts
  ```
- [ ] `dockwatch check --notify` triggers ntfy alongside other configured notifiers
- [ ] NiceGUI dashboard: ntfy settings panel (server URL, topic, test button)
- [ ] Test with public `ntfy.sh` and verify mobile push notification delivery

---

## Phase 11 — Portainer Integration

> Goal: Connect to Portainer API to manage containers across Portainer-managed environments.

- [ ] Create `src/dockwatch/integrations/` package
  - [ ] `src/dockwatch/integrations/__init__.py`
  - [ ] `src/dockwatch/integrations/portainer.py`
- [ ] `PortainerClient` class
  - [ ] Auth: `POST /api/auth` with username/password → JWT token (or API key header)
  - [ ] List environments: `GET /api/endpoints` → enumerate Portainer-managed Docker hosts
  - [ ] List containers per environment: `GET /api/endpoints/{id}/docker/containers/json`
  - [ ] Pull image: `POST /api/endpoints/{id}/docker/images/create` (trigger update via Portainer)
  - [ ] Recreate container: `POST /api/endpoints/{id}/docker/containers/{id}/recreate` (Portainer-native recreate)
- [ ] Add Portainer config to `config.toml`:
  ```toml
  [portainer]
  enabled = false
  url = "https://portainer.local:9443"
  api_key = ""                   # or username/password pair
  username = ""
  password = ""
  environments = []              # empty = all, or list specific environment IDs
  ```
- [ ] CLI integration
  - [ ] `dockwatch list --source portainer` — list containers from Portainer instead of local socket
  - [ ] `dockwatch check --source portainer` — check Portainer-managed containers
  - [ ] `dockwatch environments` — list available Portainer environments
- [ ] NiceGUI dashboard integration
  - [ ] Portainer settings page: URL, API key input, "Test Connection" button
  - [ ] Source toggle on dashboard: "Local Docker" / "Portainer" / "All"
  - [ ] Environment selector dropdown when Portainer source is active
  - [ ] Per-container "Update via Portainer" button (pull + recreate)
- [ ] Handle Portainer API errors gracefully: auth failure, unreachable, invalid endpoint
- [ ] Test with Portainer CE (free) instance

---

## Phase 12 — GHCR Full Support with Semver Parsing

> Goal: First-class GitHub Container Registry support with proper version detection.

- [ ] Extend `src/dockwatch/registry.py` — full `check_ghcr()` implementation
  - [ ] Anonymous token flow: `GET https://ghcr.io/token?service=ghcr.io&scope=repository:{namespace}/{image}:pull`
  - [ ] Fetch all tags: `GET https://ghcr.io/v2/{namespace}/{image}/tags/list` with Bearer token
  - [ ] Handle pagination (`Link` header) to retrieve full tag list beyond first page
  - [ ] Fetch manifest per tag to get `created` timestamp for recency fallback: `GET https://ghcr.io/v2/{namespace}/{image}/manifests/{tag}`
  - [ ] Auth with PAT for private GHCR images: `Authorization: Bearer <base64(user:token)>`
- [ ] Extend `src/dockwatch/models.py`
  - [ ] Add `ghcr_token: str | None` to config for private GHCR access
  - [ ] Add `RegistryType.GHCR` routing in `check_container()`
- [ ] Semver parsing for GHCR tags (shared utility — see Phase 13)
  - [ ] Normalize common GHCR tag formats: `v1.2.3`, `1.2.3`, `1.2.3-alpine`, `sha-abc1234`
  - [ ] Strip `v` prefix before parsing, preserve pre-release/build metadata labels
  - [ ] Filter out commit-SHA tags (`sha-[0-9a-f]{7,}`) — not version tags
  - [ ] Filter out date-stamp tags (`YYYYMMDD`, `YYYY-MM-DD`) — not semver
- [ ] Add GHCR config to `config.toml`:
  ```toml
  [registries.ghcr]
  token = ""    # GitHub PAT with read:packages scope, for private images
  ```
- [ ] CLI: `dockwatch check` auto-detects `ghcr.io/` prefix and routes to GHCR checker
- [ ] NiceGUI dashboard: GHCR token input in Settings → Registries page
- [ ] Test with public GHCR images (e.g. `ghcr.io/linuxserver/...`) and a private image

---

## Phase 13 — Semantic Version Diff Display

> Goal: Show users exactly what kind of change an update represents (MAJOR/MINOR/PATCH).

- [ ] Create `src/dockwatch/semver.py`
  - [ ] `parse_version(tag: str) -> Version | None` — wraps `packaging.version.Version`, returns `None` for non-semver tags
  - [ ] `compare_versions(current: str, latest: str) -> VersionDiff`
  - [ ] `VersionDiff` dataclass:
    - `bump_type: Literal["MAJOR", "MINOR", "PATCH", "PRE-RELEASE", "UNKNOWN"]`
    - `current_parsed: Version | None`
    - `latest_parsed: Version | None`
    - `current_raw: str`
    - `latest_raw: str`
  - [ ] Bump type logic:
    - `MAJOR` — major version number changed (`1.x.x` → `2.x.x`)
    - `MINOR` — minor version changed, major same (`1.2.x` → `1.3.x`)
    - `PATCH` — only patch changed (`1.2.3` → `1.2.4`)
    - `PRE-RELEASE` — pre-release suffix changed (`1.2.3-beta` → `1.2.3`)
    - `UNKNOWN` — either tag is non-semver (e.g. `latest`, `edge`, digest)
  - [ ] `format_diff(diff: VersionDiff) -> str` — human-readable: `"1.25.3 → 1.27.2 (MINOR)"`
- [ ] Extend `UpdateResult` dataclass with `version_diff: VersionDiff | None`
- [ ] CLI display (`display.py`)
  - [ ] Add "Bump" column to `dockwatch check` table: `MAJOR` (red), `MINOR` (yellow), `PATCH` (green), `UNKNOWN` (dim)
  - [ ] `dockwatch check --outdated-only` filters to outdated containers only and shows diff
  - [ ] `dockwatch check --major-only` — show only MAJOR version bumps (useful for cautious users)
- [ ] NiceGUI dashboard
  - [ ] Bump type badge in container table (color-coded chip: MAJOR/MINOR/PATCH)
  - [ ] Filter bar: "All / Outdated / MAJOR only / MINOR+" toggle
  - [ ] Tooltip on version cells showing full `current → latest (BUMP TYPE)` string
  - [ ] Sort table by bump type (MAJOR first)
- [ ] Unit tests in `tests/test_semver.py`
  - [ ] Standard semver: `1.0.0` → `2.0.0` = MAJOR
  - [ ] Minor bump: `1.2.3` → `1.3.0` = MINOR
  - [ ] Patch bump: `1.2.3` → `1.2.4` = PATCH
  - [ ] `v`-prefixed tags: `v1.2.3` → `v1.3.0` = MINOR
  - [ ] Suffixed tags: `1.2.3-alpine` → `1.2.4-alpine` = PATCH
  - [ ] Non-semver: `latest` → `latest` = UNKNOWN
  - [ ] Mixed: `1.2.3` → `latest` = UNKNOWN

---

## Backlog / Future Phases

- [ ] Multi-host support (connect to remote Docker daemons via TCP)
- [ ] Scheduled auto-check cron (daemon mode)
- [ ] Rollback support: keep previous image digest, one-click rollback in dashboard
- [ ] Slack notifier
- [ ] Email notifier

---

## Review Log

<!-- Add entries here as phases complete -->
- 2026-04-06: Phase 1 complete (`pyproject.toml`, package scaffold, core models, editable-install/import verification).
- 2026-04-06: Phase 2 complete (`docker_client.py`, image parsing, Docker connection error handling, smoke test run).
- 2026-04-06: Phase 3 complete (`registry.py`, async Docker Hub/GHCR checks, concurrent checks, mocked httpx unit tests).
- 2026-04-06: Phase 4 complete (`display.py`, Typer CLI commands, entry point wiring, command verification; Docker unavailable for live table output in this environment).
- 2026-04-06: Phase 5 complete (`web` package, NiceGUI dashboard, per-row checks, auto-refresh, `serve` command, localhost/LAN binding smoke tests).
- 2026-04-06: Phase 6 complete (`config.py`, pin/ignore/config CLI commands, config-aware check pipeline, PINNED status + dashboard pin/unpin).
