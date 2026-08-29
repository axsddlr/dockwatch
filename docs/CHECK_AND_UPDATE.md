# Check & Update

How dockwatch decides a container is outdated, and what actually happens
when you click Update.

## Update Checking

dockwatch discovers containers (local Docker, Portainer, or both), resolves each image's registry (Docker Hub, GHCR, Codeberg), and compares what's deployed against what's available:

- **Digest comparison** when both local and remote digests are known — the most reliable signal, and the only one that works for floating tags like `latest`.
- **Version comparison** (semver-aware, with linuxserver.io `-lsNN` and distro-suffix `-alpine`/`-slim` handling) when digests aren't available but both tags parse as versions.
- **Tag comparison** as a last resort — if neither digest nor version comparison is possible, dockwatch reports `UNKNOWN` rather than guessing.

## Updating Containers

Clicking **Update** (or `dockwatch update <container>`) does a real update, not just a metadata change:

- **Compose-managed containers** — rewrites the service's `image:` tag in the compose file (if pinned to an exact tag), then runs `docker compose pull <service>` and `docker compose up -d <service>`, scoped to that one service. Sibling services in the same file are untouched. The same applies to Portainer stacks — only the target service's image line is rewritten in the stack file; Portainer diffs the compose content and recreates only the changed service.
- **Plain containers** — pulls the new image, then does a full recreate via the Docker SDK (stop → rename to backup → create replacement with the same host/network config → start → remove old). Automatically rolls back to the original container if the replacement fails to start.
- **Floating tags** (`latest`, `edge`, `dev`, `nightly`) — skips tag rewriting, just pulls and recreates, and only proceeds if digest comparison confirmed something actually changed.

## Rollback

Every successful update is remembered. If it turns out to be a bad update, click **Rollback** in the container's history panel (or the dashboard's rollback button) to revert to the last known-good tag — dockwatch reruns the same compose pull/up flow in reverse.

Current scope: **compose-managed containers only**. Plain (non-compose) containers don't have a rollback path yet, since there's no compose file to revert.

## Digest Drift Alerts

A floating tag like `latest` can silently start pointing at a different image without anyone touching the compose file — the tag string never changes, only the digest behind it. dockwatch treats this as a distinct, always-notified event (`digest_drift`) instead of folding it into an ordinary "update available" notification, so you don't miss a supply-chain-relevant change just because your `notify_on` filter is scoped to something else.

## Multi-Arch Images

Multi-arch images publish a manifest *list* — one entry per platform (amd64, arm64, ...). That list's own digest changes whenever **any** platform is rebuilt, even if the platform you're actually running is untouched. dockwatch resolves your Docker daemon's actual architecture and compares the digest of *that* platform's manifest entry, not the list's own digest — so an arm64 rebuild upstream doesn't falsely flag your amd64 deployment as outdated or drifted. Falls back to the previous list-digest behavior if the daemon is unreachable or your platform isn't present in the list.
