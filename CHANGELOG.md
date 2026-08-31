# Changelog

All notable changes to dockwatch are documented here, grouped by release and then by date so it's easy to see what shipped in a given week.

## [0.10.0] - 2026-08-31

### 2026-08-31

#### Added
- **Update delay** — a global "Update delay (days)" setting (and per-container `dockwatch.update_delay_days` label override) suppresses update offers until dockwatch has observed the newer tag for that many days, so freshly published images can bake before you're asked to update. Delayed rows show as up-to-date with an "update delayed (N days remaining)" note.
- **SSRF guard for notification URLs** — webhook, Discord, and ntfy URLs are validated on save: only http(s) schemes are allowed, literal private/loopback/link-local/reserved addresses are rejected, and hostnames that resolve only to such addresses (e.g. cloud metadata endpoints) are rejected too.

## [0.9.2] - 2026-08-29

### 2026-08-29

#### Added
- **Modernized container checklist in Monitoring Scope** — the plain checkbox lists (ignored / auto-update containers) are now clickable rows with a custom check indicator, a per-list "X of Y selected" count, and Select all / Clear all.

#### Fixed
- **Dashboard row actions now reflect immediately** — pin/unpin, update, rollback, delete, restart, and compose-config saves previously required a manual page refresh (rows were driven by the zustand store, but the mutations invalidated a non-existent react-query key). They now re-check and update the store on success.
- **No phantom MAJOR bump on up-to-date containers** — a digest-matched container with a stale or mismatched version label (e.g. linuxserver.io images) could render "Up-to-date" alongside a MAJOR bump. A bump label is now only shown when an upgrade is actually available.

#### Changed
- **Slimmer Docker image** — 502MB → 452MB by keeping the build-time `uv` tool out of the runtime image (multi-stage install).
- **Removed dead code** — unused `resolved_deployed_version` and `format_diff`.
- **Internal refactor** — extracted shared utilities into `src/dockwatch/utils.py` and consolidated the duplicated Docker client factory; behavior unchanged.

#### Docs
- Refreshed the README (badges, published-image quick start, auto-detected Docker socket group) and FAQ (rollback coverage, DOCKER_GID, onboarding tour); restored `docs/CHECK_AND_UPDATE.md`.

## [0.9.1] - 2026-08-29

### 2026-08-29

#### Fixed
- **`DOCKER_GID` is no longer required — the Docker socket's group is auto-detected at startup** — the container previously needed the host's Docker group GID in `.env` (a wrong value failed silently, leaving the dashboard with zero containers). A new container entrypoint reads the mounted socket's group, grants the unprivileged `appuser` access to it, then drops privileges — so deployments work out of the box on native Linux, Docker Desktop, and hosts where only Portainer is reachable and the GID is unknown. `group_add` was removed from `docker-compose.yml`.

## [0.9.0] - 2026-08-29

### 2026-08-29

#### Added
- **Guided onboarding tour** — a react-joyride tour walks new users through the dashboard, settings, and users pages, with a help button in the header to replay it at any time. Progress persists per user via a new `users.onboarding_seen` column and `POST /users/me/onboarding-complete` endpoint; the tour auto-runs once on first login, and the replay button always remains available afterward.
- **Portainer + non-compose rollback** — rollback now works for Portainer-managed stacks and plain non-compose containers, not just compose-managed local containers, reusing the existing Portainer stack-update and plain-recreate machinery.

#### Changed
- **Deployment pulls the published GHCR image** — `docker-compose.yml` now pulls `ghcr.io/axsddlr/dockwatch:latest` instead of building from source, and a GitHub Actions release workflow builds and pushes multi-arch (amd64/arm64) images on version tags.
- **`DOCKWATCH_SECURE_COOKIE` defaults to auto-detect** — the compose default was `false`, which silently disabled the app's HTTPS auto-detection; it now defaults to unset so the cookie `Secure` flag follows the scheme/`X-Forwarded-Proto` detection unless explicitly overridden.

## [0.8.0] - 2026-08-19

### 2026-08-19

#### Added
- **Portainer + non-compose container rollback (design)** — audited the existing rollback path (`build_rollback_plan`) and found it silently blocked Portainer-managed stacks and plain non-compose containers, even though the update path already supports both. Design spec written (`docs/superpowers/specs/2026-08-19-portainer-rollback-design.md`) for extending rollback to reuse the existing Portainer stack-update and plain-recreate machinery; implementation tracked separately.

#### Fixed
- **Trivy scan races, misclassification, and unbounded output** — concurrent scan requests for the same image both missed cache and both spawned a `trivy` process (now deduplicated via an in-flight scan map keyed by image ID); a failed container-discovery lookup silently fell back to scanning the container's *name* as if it were an image reference instead of erroring; UNKNOWN-severity findings were being counted as LOW (now a proper `unknown_count` bucket, threaded through the API and dashboard severity bars); `trivy` could fall back to pulling a remote image when no local image matched (`--image-src docker` now pins it to the local daemon only); and captured scan output had no size cap, so a malformed or runaway scan could balloon memory (now capped at 64MB with the process killed on overflow). Scan failures (timeouts, non-zero exits, unparseable output) are now logged server-side.
- **App header showed a generic placeholder icon instead of the dockwatch logo** — the header referenced a stock lucide `Hexagon` icon rather than the shield-eye brand SVG, so the logo never appeared next to "dockwatch" in the top bar even though `favicon.svg` existed and was linked correctly. The header now renders `/favicon.svg` directly; the icon itself was also simplified back to a clean shield outline with a solid pupil (dropped the iris ring and highlight dot, which read poorly at 16px favicon size).

### 2026-08-18

#### Added
- **Admin password recovery without shell exec into a running session** — a new `dockwatch config recover-admin` CLI command (no args) finds the earliest-created `admin` user, generates a one-time recovery token, and prints it to stdout (visible via `docker logs` when run through `docker exec`); only a hash of the token plus a 15-minute expiry are stored server-side. A new `POST /auth/recover` route (`{"token", "new_password"}`) redeems it — single-use, 15-minute expiry, rate-limited via its own lockout bucket separate from `/auth/login`. On success the user's `session_version` is bumped, invalidating any existing login cookie for that account. A new `/recover` page (token + new-password fields) exposes this in the dashboard; it's deliberately not linked from `/login`, to avoid exposing a lockout-oracle UI element. The existing `dockwatch config set-password` path (requires host/container exec) still works unchanged as the other recovery option.
- **Per-container auto-update toggle** — enabling auto-update for a single container previously required going to Settings and editing a comma-separated container list. New `POST`/`DELETE /containers/{name}/auto-update` endpoints (mirroring the existing pin/unpin routes) flip the `auto_update` flag directly, surfaced as a Zap/ZapOff toggle button on each dashboard row.
- **Container logs viewer** — a new `GET /containers/{name}/logs` endpoint (tail, default 200 lines, backed by `docker_client.get_logs`) powers a per-row LogsPanel (poll + manual refresh) alongside the existing HistoryPanel. Local containers only; Portainer-managed containers return 422, since log retrieval isn't proxied through Portainer's API yet.

#### Fixed
- **Action-bar overflow on dashboard rows** — adding the auto-update toggle and logs button to the existing Check/Pin/Update/Scan/History/Restart/Delete row actions overflowed and overlapped the action bar. Low-frequency actions (logs, history, restart, delete image/container) are now grouped into a new ActionMenu kebab dropdown; Check, Pin, Auto-update, Update, and Scan remain as top-level icons.
- **Crimson accent + button contrast fix (WCAG AA)** — the amber accent (`#dfab5c`) read closer to gold than intended, and its text-black CTA buttons failed WCAG AA contrast (~3.5:1) once the palette shifted. Replaced amber tokens with crimson (`#c4453c`) across CSS custom properties, and swapped text-black to text-white on all crimson-background CTA buttons (Toolbar, SettingsActions, dialogs, auth pages) for ~5.9:1 contrast. Dark theme also got editorial-style token refinement (softer rgba borders, warmer off-black backgrounds, tighter line-height) to match the minimalist-ui design pass.
- **`config set-password` silently reset the wrong credentials on migrated instances** — the command wrote to `config.toml`'s legacy auth section, but login checks the SQLite users table once a site has migrated via `migrate_auth_config_to_users`. Running it against a migrated instance updated dead config and left the real password unchanged, with no error indicating the mismatch. It's now routed through `ManifestStore`, updating the user's `password_hash` in the actual users table via a new `update_user_password()`. Resetting an existing user's password logs a SECURITY warning naming the affected user, since a successful reset only requires container/host exec access and no prior credential.
- **Session cookies now default to `Secure` when HTTPS is detected** — previously the `Secure` flag on the session cookie was a manual opt-in (`DOCKWATCH_SECURE_COOKIE=true`), so a forgotten setting behind a TLS-terminating reverse proxy left the cookie sendable over plain HTTP. Login and registration now auto-detect HTTPS from the request scheme or `X-Forwarded-Proto` (trusted unconditionally unless `DOCKWATCH_TRUSTED_PROXIES` is set, in which case it's only trusted from a listed proxy) and set `Secure` accordingly, logging a warning when a cookie is issued without it. `DOCKWATCH_SECURE_COOKIE=true`/`false` still overrides the auto-detection explicitly.
- **Rate limiting and lockout are no longer blind behind a reverse proxy** — login lockout and route rate limiting keyed on the raw TCP peer IP, so every request behind a shared proxy/load balancer collapsed onto one IP (one bad actor could lock out everyone) or, if `X-Forwarded-For` was trusted blindly, let a client spoof it to evade limits entirely. New `DOCKWATCH_TRUSTED_PROXIES` (comma-separated CIDRs/IPs) lets `X-Forwarded-For` be trusted only when it arrives via a listed proxy; unset, the raw peer IP is used as before.

#### Changed
- **`dockwatch config set-password` now requires `--create` to mint a new user — breaking change for scripted/automated use.** Previously, if `--username` didn't match an existing account, the command silently created a brand-new admin user with no confirmation and no security log — unlike the password-reset branch, which did log a SECURITY warning. A typo'd or stale `--username` (e.g. from templated automation) could mint an unintended standing admin account with no audit trail. The command now **fails closed by default**: it errors with exit 1 when the named user doesn't exist. Pass the new `--create` flag to explicitly opt into creating them as admin; that branch is now logged as a SECURITY event matching the existing reset-branch logging. **Scripts or automation that relied on the old implicit-create behavior will need `--create` added, or they will start failing.**

## [0.7.3] - 2026-08-12

### 2026-08-12

#### Fixed
- **Portainer stacks discovered via the local socket can now be updated** — a Portainer-managed container (compose labels under `/data/compose/`) is correctly tagged `source="portainer"`, but when discovered through the local Docker socket it carried no `environment_id`, so updates/restarts/deletes failed with "no associated Portainer environment". Updates now resolve the environment id authoritatively from the stack's `EndpointId`, and discovery/merge prefer the Portainer identity that carries an `environment_id`.

## [0.7.2] - 2026-08-12

### 2026-08-12

#### Fixed
- **Distro-variant-aware update selection** — latest-tag selection now respects the OS-base variant of the deployed image instead of picking the highest version across all bases. A container pinned to `postgres:16-alpine` was being offered `18.4-trixie` (a "major update" that would swap the musl base for Debian and break the deployment). Selection now prefers the highest tag sharing the same variant (`16-alpine` → latest `*-alpine`, `18-trixie` → latest `*-trixie`), treating an unsuffixed tag as its own family, and falls back to cross-variant selection only when no same-variant tag exists.
- **No more misleading "UNKNOWN" bump on up-to-date containers** — the dashboard rendered a literal `UNKNOWN` bump badge for containers whose deployed and latest versions are identical (a digest match with the same tag, e.g. `1.31.3-trixie-perl`). That value comes from `compare_versions`, which uses `UNKNOWN` to mean "no version bump" (equal versions), not "comparison failed". The bump badge is now suppressed for `UNKNOWN`, and the CLI shows `-` instead.

## [0.7.0] - 2026-08-12

### 2026-08-12

#### Fixed
- **Portainer mutation routes now respect `portainer.enabled`** — restarting or deleting a Portainer-managed container, and Portainer stack updates, previously ignored the integration's enabled/disabled toggle entirely; only container *discovery* checked it. Disabling Portainer in Settings now actually blocks these actions instead of silently allowing them.
- **Stack deploy calls now use a dedicated, longer timeout** — `create_stack`/`update_stack` block on Portainer's synchronous image pull + recreate, which routinely exceeds the short per-call timeout for real (non-trivial) images. Live-verified against a real Portainer instance: the deploy was completing successfully server-side even after the client had already raised a timeout error, producing false failures. Added `portainer.deploy_timeout` (default 120s, configurable) used only for these two calls.
- **Security hardening** — rate-limiting on mutating routes (container update/delete/restart/rollback, settings PUT, Portainer test, user creation) at 10 calls/60s per IP+path; structured logging of auth events (login success/failure, lockout, registration, rejected sessions, permission-denied); daily SQLite backups via the WAL-safe online backup API, retaining the last 7 copies.

#### Docs
- Documented the `portainer.deploy_timeout` config and the retry caveat (a timed-out redeploy call often still completes server-side — check Portainer's stack state before retrying).

### 2026-08-08

#### Added
- **Opt-in per-container auto-update** — a new `auto_update` container flag (SQLite, alongside pinned/ignored), toggled per container from Settings → Monitoring Scope. On each scheduled check, flagged containers that come back outdated are updated automatically through the same plan/execute path as a manual click — same safety checks (pinned/floating-tag/compose guards), same audit log entry, attributed to `scheduler (auto-update)`. Off by default; nothing changes for containers not opted in.

### 2026-08-05

#### Added
- **Portainer stack creation API** — `PortainerClient.create_stack()` deploys compose stacks programmatically via the Portainer API (`POST /api/stacks/create/standalone/string`), complementing the existing find/read/update stack methods. Includes a runnable `deploy_to_portainer.py` example in the README that reads a compose file and adjacent `.env`, then deploys it as a Portainer-managed stack with automatic source tagging.
- **Background scheduled check in web server** — the `serve` command now runs a background asyncio task that periodically checks all containers on the configured schedule, keeps the results cache warm, and broadcasts fresh data to connected dashboards via WebSocket. No need to click Refresh to see current state.

#### Changed
- **Source filter is now client-side only** — switching between Local / Portainer / All filters no longer triggers a full `check_all()` API call. The dashboard filters already-loaded results in memory, eliminating unnecessary Docker Hub registry calls.

#### Fixed
- **Multi-arch digest comparison** — `RepoDigests` always records the manifest-*index* digest for a multi-arch pull, but platform-selection logic was comparing that against a platform-specific manifest entry digest — two digest tiers that essentially never match, permanently misreporting multi-arch images (e.g. linuxserver.io images) as outdated even when content was byte-identical.
- **Compose workdir double-prefixing** — pasting an already-resolved host path (e.g. copied from an error message showing `/hostroot/...`) into Settings caused `resolve_host_path()` to prepend the prefix again on every subsequent use, producing `/hostroot/hostroot/...` and failing the directory-exists check. Paths are now normalized on save.
- **Dashboard stat cards ignored the "All" filter** — Total / Up-to-date / Outdated / Pinned counts only reflected the currently selected source (Local or Portainer) instead of all containers; now always shows the true total regardless of toolbar filter.
- **Manifest digest & token caching** — Docker Hub manifest digests and `auth.docker.io` bearer tokens are now cached in-memory for 60 seconds, dramatically reducing API calls and eliminating 429 rate-limit errors on rapid successive checks (page refreshes, source/environment switches, auto-refresh).
- **409 race condition on refresh** — concurrent container checks are now properly guarded: `Toolbar` sets `isChecking` optimistically before the WebSocket round-trip, and the redundant `initialCheck` mutation is removed from `DashboardPage`. The auto-refresh interval also skips firing when a check is already in flight.
- **Portainer identity tracking** — containers are now tagged with the correct deployment source based on compose labels (`/data/compose/` prefix for Portainer, local workdir paths for direct Docker). Portainer-discovered containers with local compose labels are no longer mis-tagged as "portainer". Source identity survives across check cycles and is properly deduplicated when the same container is visible on both sources.

## [0.6.0] - 2026-08-05

### Added
- **Delete container & image** — admins (with a new `delete_containers` permission) can delete a container directly from the dashboard, for both local Docker and Portainer-managed containers, plus delete the underlying image for local containers. Both actions require confirmation and are logged to the update history like every other action.
- **Update history & rollback** — every update/rollback attempt is recorded (who, when, old→new tag, success/failure) in a new `update_history` table, visible via a per-container history panel (admin-gated) with a one-click rollback for compose-managed containers.
- **Digest drift alerts** — when a floating tag (e.g. `latest`) silently points at a new image digest, it's now surfaced as a distinct `digest_drift` notification and history entry instead of being folded into an ordinary update event.
- **Portainer container restart** — Portainer-managed containers can now be restarted directly from the dashboard (`POST /containers/{name}/restart`, proxied through Portainer's Docker API).
- **Multi-arch-aware digest comparison** — outdated/drift detection for multi-arch images (manifest lists) now compares the digest of the platform actually deployed (matched via the local Docker daemon's reported architecture) instead of the manifest list's own digest, which changes whenever *any* platform is rebuilt. Falls back to the previous behavior when the daemon is unreachable or the platform isn't present in the list.
- **Multi-user RBAC** — self-service registration, custom roles, per-route permission checks, user/role CRUD with last-admin protection.
- **Authentication** — username/password login via PBKDF2-SHA256 cookies, login lockout, and login/register pages in the dashboard.
- **Container checkboxes** — ignored-containers text input replaced with a discovered-container checklist in Settings.
- **SQLite-backed pinned/ignored** — `container_flags` table replaces TOML fields for pin/ignore, with one-time migration from legacy config.
- **Portainer compose stack updates** — Portainer-managed compose containers can now be fully updated (pull + recreate) via the dashboard. Previously only local Docker containers supported in-place updates; Portainer containers were limited to restart-only.

### Changed
- **Settings page streamlined** — duplicate "Pinned containers" text field removed (dashboard row buttons are the canonical path); Portainer & Trivy sections collapsed under an "Advanced" disclosure.
- **Docker Hub tag lists cached** — Docker Hub REST API tag lists are now cached in-memory for 5 minutes per image, avoiding rate-limit errors on repeated checks. Tag list pagination shared across containers for the same image within a single scan.

### Fixed
- Permission-gated UI controls now hidden from users lacking the permission (Nav, row actions, direct page access).
- Trivy severity bars are now clickable buttons that filter the findings list; zero-count severities disabled.
- Trivy vuln-DB and layer cache now persist across container recreates via a named volume.
- Malformed container records no longer crash the entire dashboard — error boundaries scope failures to individual rows.
- `PUT /settings` now returns 422 (not 500) on non-numeric field values.
- Numeric settings fields now coerce their values, preventing silent string storage.
- Stray debug `print()` in registry replaced with `logger.debug`.
- `_safe_version` now parses distro-suffixed tags (`-alpine`, `-slim`, `-bookworm`) via semver fallback.
- Pin/unpin config read-modify-write race fixed with SQLite serialization.
- Compose tag-rewrite regex no longer risks corrupting a sibling service's image line.
- Update button now rewrites the compose file's image tag, translates Windows host paths for Docker Desktop, and runs `docker compose pull`/`up -d` (or a full Docker SDK recreate for non-compose containers) so the container actually restarts on the new image.
- Stale wheel cache fix: `uv pip install` now forces reinstall of the dockwatch package.
- Pinned/ignored TOML migration now runs on CLI startup, not just on web-server start.
- **`DOCKWATCH_USERNAME`/`DOCKWATCH_PASSWORD` now actually reach the container** — `docker-compose.yml` never passed them through, so the documented "set these in `.env`" bootstrap path silently did nothing, leaving self-service registration open indefinitely on any install that followed the quickstart as written.
- `dockwatch serve`'s startup warning now checks the actual users table instead of the stale legacy single-credential config, and warns explicitly that an empty users table means the next visitor to register becomes admin.
- Upgraded `react-router-dom` to 7.18.2, fixing an open-redirect/XSS advisory (GHSA-jjmj-jmhj-qwj2) and an SSR-hydration constructor-injection advisory (GHSA-337j-9hxr-rhxg) present in the prior 6.x pin; upgraded `postcss` to fix a source-map path-traversal advisory (GHSA-r28c-9q8g-f849).
- Pinned all Dockerfile base images (`python:3.12-slim`, `node:22-slim`, `docker:27-cli`, `aquasec/trivy`, `ghcr.io/astral-sh/uv`) to a specific version and digest — two of these were previously floating on `:latest`, so a malicious or broken upstream push could silently change the next build.
- Portainer-discovered containers now resolve repo digests correctly for outdated/drift comparison.
- Update button hidden on Portainer-sourced rows for containers whose update path is not yet supported.
- New permissions are now synced into the existing admin role on startup, so upgrades automatically grant admins access to newly introduced features.
- Auth hardening: session cookie scoped consistently, registration endpoint returns correct error codes, Portainer settings endpoint requires authentication.
