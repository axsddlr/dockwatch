# Changelog

All notable changes to dockwatch.

## [Unreleased]

### Added
- **Update history & rollback** — every update/rollback attempt is recorded (who, when, old→new tag, success/failure) in a new `update_history` table, visible via a per-container history panel (admin-gated) with a one-click rollback for compose-managed containers.
- **Digest drift alerts** — when a floating tag (e.g. `latest`) silently points at a new image digest, it's now surfaced as a distinct `digest_drift` notification and history entry instead of being folded into an ordinary update event.
- **Portainer container restart** — Portainer-managed containers can now be restarted directly from the dashboard (`POST /containers/{name}/restart`, proxied through Portainer's Docker API). Full pull+recreate for Portainer-managed containers is not yet supported — only local Docker containers can be updated in place today.
- **Multi-arch-aware digest comparison** — outdated/drift detection for multi-arch images (manifest lists) now compares the digest of the platform actually deployed (matched via the local Docker daemon's reported architecture) instead of the manifest list's own digest, which changes whenever *any* platform is rebuilt. Falls back to the previous behavior when the daemon is unreachable or the platform isn't present in the list.
- **Multi-user RBAC** — self-service registration, custom roles, per-route permission checks, user/role CRUD with last-admin protection.
- **Authentication** — username/password login via PBKDF2-SHA256 cookies, login lockout, and login/register pages in the dashboard.
- **Container checkboxes** — ignored-containers text input replaced with a discovered-container checklist in Settings.
- **SQLite-backed pinned/ignored** — `container_flags` table replaces TOML fields for pin/ignore, with one-time migration from legacy config.

### Changed
- **Settings page streamlined** — duplicate "Pinned containers" text field removed (dashboard row buttons are the canonical path); Portainer & Trivy sections collapsed under an "Advanced" disclosure.

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
