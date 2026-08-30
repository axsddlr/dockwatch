# dockwatch vs Tugtainer

Both are self-hosted "review before you update" alternatives to Watchtower. Tugtainer (1.5k stars, Python/Angular) is the closer competitor — worth a direct comparison.

## Where Tugtainer is ahead

- **Multi-host via a real agent** — deploys a Tugtainer Agent per remote host, coordinates over HTTP. dockwatch's multi-host story is Portainer-only (no agent, requires Portainer already running on the fleet).
- **OpenID Connect** — SSO out of the box. dockwatch is local password auth only.
- **Apprise notifications** — one integration, dozens of notification services. dockwatch hand-rolls three (webhook, Discord, ntfy).
- **Per-container auto-update toggle** — auto-update some containers, check-only others, in the same instance. dockwatch is check-only across the board; updating always requires a manual click/command.
- **Auto-update mode exists at all** — opt-in, disabled by default, but present. dockwatch has no unattended-update path by design (arguably a feature, not a gap — see below).

## Where dockwatch is ahead

- **Digest-aware comparison, not just tag-aware** — distinguishes a real version bump from a floating tag silently repointing to new content (digest drift), and does per-platform-safe multi-arch comparison. No indication Tugtainer does digest comparison at all vs. just tag/version checks.
- **RBAC with custom roles** — six granular permissions, combinable into roles beyond admin/viewer. Tugtainer has no access control tiers, just "logged in or not."
- **Vulnerability scanning (Trivy)** — CVE scanning against the running image, built into the dashboard. Tugtainer has none.
- **Compose-aware updates** — rewrites the actual `image:` line in the compose file (or Portainer stack file) so state stays correct after the update, not just a container recreate with drifted compose source.
- **CLI + daemon mode** — scriptable for cron/automation (`dockwatch check --json`, `dockwatch update`), not just a web UI.
- **Full audit log** — every update/rollback/restart/delete recorded with who/when/old→new tag, not just an update-succeeded/failed signal.

## Positioning

Tugtainer wins on breadth of connectivity (agent-based multi-host, SSO, broad notification fanout) and on optional automation. dockwatch wins on *trust in what "outdated" means* (digest-first, multi-arch-safe) and *depth of control once you decide to act* (RBAC, audit trail, CVE scanning, compose-correctness). Roughly: Tugtainer is easier to spread across many hosts and let mostly run itself; dockwatch is stricter about what it tells you and who's allowed to act on it.

## Gaps worth closing

1. **Agent-based multi-host** — biggest structural gap. Portainer-only multi-host is a real limitation for anyone not already running Portainer.
2. **Notification fanout (Apprise)** — cheap win, swap/add Apprise instead of maintaining bespoke integrations.
3. **OIDC** — matters for team/enterprise positioning, ties into the RBAC story already built.
4. **Optional auto-update toggle** — currently a deliberate design stance ("You approve every update"), but an opt-in per-container auto-update mode wouldn't contradict that if it defaults off — worth deciding intentionally rather than by omission.
