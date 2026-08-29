# Production Readiness Assessment

Assessed 2026-08-18. Backend engineering (WAL-mode SQLite, daily backups,
resilient scheduler, real RBAC, 38+ auth tests) is more mature than a
typical homelab project. The gaps below are specific and fixable, not
architectural — none require a rewrite.

Status legend: `[ ]` open, `[x]` done.

---

## Blockers — fix before shipping to non-technical/consumer users

### 1. Session cookie defaults to insecure (no `Secure` flag)

- **Where:** `docker-compose.yml:18`, `src/dockwatch/api/security.py:40-42`
- **Root cause:** `DOCKWATCH_SECURE_COOKIE` defaults to `"false"`.
  ```python
  secure = os.environ.get("DOCKWATCH_SECURE_COOKIE", "").strip().lower() == "true"
  ```
  Anyone deploying via the documented quickstart (`docker compose up`,
  no `.env` overrides) gets a session cookie sent over plain HTTP.
  Sniffable on the wire (LAN, shared hosting, any MITM position).
- **Fix:**
  - [ ] Default `DOCKWATCH_SECURE_COOKIE` to `true`, and require an
    explicit opt-out for HTTP-only dev/testing setups.
  - [ ] If flipping the default breaks common reverse-proxy-less LAN
    deployments (HTTP-only by design for many homelab users), instead:
    detect `X-Forwarded-Proto: https` when present and force `secure`
    only when TLS is actually terminating somewhere, otherwise warn
    loudly at startup (same pattern as the existing "no user exists
    yet" warning in `main.py`).
  - [ ] Document the tradeoff in `README.md`/`docs/DEMO_RUNBOOK.md`.

### 2. No self-service password reset if the sole admin is locked out

- **Where:** `src/dockwatch/api/routes/auth.py`, `users.py` — no
  `/auth/reset-password` or forgot-password route exists. Recovery
  today is CLI (`dockwatch config set-password`, requires host/container
  exec access) or direct DB edit.
- **Root cause:** Never built. Fine for an operator with shell access
  to their own box; not fine for a consumer whose "admin" is a NAS
  web UI with no other access path.
- **Fix:**
  - [ ] Decide on a recovery mechanism appropriate for self-hosted
    single-admin deployments — options, roughly in order of effort:
    1. Document the existing CLI path clearly (`docs/`) — cheapest,
       ships today, doesn't fix the underlying UX gap.
    2. Email-based reset (needs SMTP config — likely too heavy for
       this app's scope).
    3. One-time recovery token written to a file on first boot /
       printed to `docker logs`, redeemable once via a `/recover`
       route — matches the trust model already used for admin
       bootstrap (`bootstrap_auth_from_env` in `config.py`).
  - [ ] At minimum, add the CLI recovery path to `README.md`'s
    troubleshooting section so it's discoverable without reading
    source.

### 3. Rate limiting / lockout is IP-keyed and reverse-proxy-blind

- **Where:** `src/dockwatch/api/routes/auth.py:24-65`
  (`_failed_attempts`, `_client_key`), `src/dockwatch/api/rate_limit.py`
- **Root cause:**
  ```python
  def _client_key(request: Request) -> str:
      return request.client.host if request.client else "unknown"
  ```
  Both the login lockout (5 attempts / 5 min) and the general mutation
  rate limiter key strictly off the raw TCP peer address. Behind any
  reverse proxy that doesn't forward/parse `X-Forwarded-For`
  (Nginx Proxy Manager, Cloudflare Tunnel, Traefik without explicit
  trusted-proxy config — all common self-hosted setups), every request
  appears to originate from the proxy's IP. Two failure modes:
  - One bad actor (or one user who mistypes their password 5 times)
    locks out **every** user behind that proxy.
  - An attacker rotating source IPs behind a botnet is never
    rate-limited at all, since the proxy is the only IP the app sees
    in the worst case, or conversely if it *does* see real IPs without
    validation, a spoofed `X-Forwarded-For` header defeats the limiter
    entirely.
- **Fix:**
  - [ ] Add explicit trusted-proxy configuration (e.g.
    `DOCKWATCH_TRUST_PROXY_HEADERS=true` + optional trusted CIDR list)
    that only honors `X-Forwarded-For`/`X-Real-IP` when the immediate
    peer is in the trusted set — never trust the header unconditionally.
  - [ ] Document the default behavior (raw peer IP, safe-but-naive)
    clearly so reverse-proxy users know to configure it.
  - [ ] Consider moving `_failed_attempts` state to the SQLite store
    (already used for everything else) so lockouts survive restarts —
    currently in-memory only, wiped on every container recreate. Lower
    priority than the proxy-blindness issue.

---

## Real gaps — not blockers, but should be tracked

### 4. Zero accessibility support

- **Where:** frontend-wide — grep for `aria-`/`role=` across
  `frontend/src/pages/*.tsx` returns 0 matches.
- **Impact:** Screen-reader users get an unusable app. Not a blocker
  for a homelab tool used by its own author; is one if "consumer"
  includes accessibility-conscious or legally-obligated deployments.
- **Fix:**
  - [ ] Pass over interactive elements (buttons, toggles, the new
    `ActionMenu` dropdown, modals) adding `aria-label`, `role`, and
    focus-trap behavior for dialogs.
  - [ ] At minimum: labeled form inputs, keyboard-dismissible modals
    (Escape key), focus returned to trigger element on close.

### 5. Minimal mobile responsiveness

- **Where:** only 2 files in `frontend/src/` use responsive
  classes/media queries.
- **Impact:** Dashboard likely unusable on phone/tablet widths — the
  12-column `ContainerRow` grid in particular (already patched once
  this session for icon overflow, but not for narrow viewports).
- **Fix:**
  - [ ] Decide if mobile support is in scope at all for a
    self-hosted ops dashboard (many such tools intentionally don't
    support mobile). If yes, plan a responsive pass separately —
    non-trivial given the dense table layout.

### 6. No in-app "update available" signal for dockwatch itself

- **Where:** N/A — feature doesn't exist.
- **Impact:** Ironic for an update-watcher: users must manually check
  GitHub for new dockwatch releases.
- **Fix:**
  - [ ] Add a lightweight version-check (compare running version
    against latest GitHub release tag) surfaced in the UI header,
    matching the existing `v0.7.3` badge already shown — could just
    add a "new version available" indicator next to it.

### 7. No git tags despite a maintained CHANGELOG

- **Where:** `CHANGELOG.md` documents versions 0.7.0–0.7.3 in detail;
  `git tag` shows none.
- **Impact:** Can't `git checkout v0.7.2` to roll back to a known-good
  release; Docker image tags (`dockwatch-local:dev`) aren't
  version-pinned either.
- **Fix:**
  - [ ] Tag existing releases retroactively where possible
    (`git tag v0.7.3 <commit>` for the commit that bumped the version).
  - [ ] Going forward, tag on every version bump commit.
  - [ ] Consider publishing versioned images to a registry (GHCR)
    instead of building `:dev` locally via compose, so users can pin
    a specific version.

### 8. This session's features aren't documented

- **Where:** `CHANGELOG.md` (latest entry 0.7.3, Portainer fixes only),
  `README.md` — neither mentions:
  - Per-container auto-update toggle (`POST/DELETE
    /containers/{name}/auto-update`)
  - Container logs viewer (`GET /containers/{name}/logs`)
  - Crimson accent / design token change
  - Action-menu (kebab) UI refactor
  - `set-password --create` flag change (breaking: old behavior
    silently created users, now requires the flag)
- **Fix:**
  - [ ] Add a CHANGELOG entry before the next version bump/tag.
  - [ ] Update `README.md`'s feature list.
  - [ ] Call out the `set-password` behavior change explicitly since
    it's a breaking CLI change for anyone scripting against it.

---

## Confirmed non-issues (already solid — no action needed)

- **SQLite concurrency:** WAL mode + `busy_timeout=5000`, per-request
  connections (`db.py`). No `check_same_thread` risk, no lock
  contention under normal load.
- **Backups:** Daily automated backup to
  `~/.config/dockwatch/backups/` via SQLite's online backup API
  (safe under WAL), pruned automatically, persisted in the
  `dockwatch_config` named volume — survives container recreation.
  (Restore is manual file-copy, no CLI command — minor, could add a
  `dockwatch config restore` command later if it comes up.)
- **Scheduler resilience:** Both the check loop and backup loop in
  `api/app.py` wrap each iteration in try/except with
  `logger.exception`, so one bad tick doesn't kill the background
  task. (Note: the CLI-only `ScheduledCheckRunner.serve_forever()` in
  `scheduler.py` lacks this — low priority since the shipped Docker
  image runs `dockwatch serve`, not the CLI scheduler path.)
- **Authorization model:** Server-side permission checks throughout
  (`security.py`), last-admin-can't-be-demoted/deleted protection in
  `users.py`, new permissions auto-synced into existing admin role on
  upgrade. No privilege-escalation path found in this review.
- **Test coverage:** Substantial — `test_auth.py` (38 tests),
  `test_docker_client.py`, `test_scheduler.py`, `test_updater.py`,
  `test_updater_portainer_gate.py`.

---

## Suggested order of work

1. Blocker #1 (secure cookie default) — smallest diff, highest impact.
2. Blocker #3 (rate-limit proxy blindness) — security-critical,
   moderate effort.
3. Gap #8 (document this session's features + changelog) — cheap,
   unblocks a clean version tag.
4. Gap #7 (tag releases) — process change, no code.
5. Blocker #2 (password recovery) — biggest design decision, do after
   the above are settled so the recovery mechanism can reuse whatever
   secure-cookie/proxy-trust decisions were made.
6. Gaps #4–6 (accessibility, mobile, self-update-check) — track but
   not urgent; revisit based on actual user feedback.
