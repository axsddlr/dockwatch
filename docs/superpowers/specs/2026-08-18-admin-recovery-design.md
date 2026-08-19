# Admin password recovery — design

Status: approved, pending implementation.
Scope: readiness doc blocker #2, plus gaps #7 (git tags) and #8 (docs)
tracked separately in the implementation plan. Blockers #1 and #3 from
the readiness doc are already fixed (commit `4a5a499`) — the doc was
stale relative to that commit; no work needed there.

## Problem

No self-service or shell-free recovery path exists if the sole admin
account is locked out. Today's only recovery is
`dockwatch config set-password`, which requires host/container exec
access — fine for an operator with shell access, not fine if the
"admin" is only a web UI with no other access path.

## Design

### Trigger: CLI command

`dockwatch config recover-admin`

- No arguments. Targets the **earliest-created** user with the `admin`
  role (deterministic — usually the bootstrap account). If no admin
  user exists, errors out (nothing to recover).
- Generates `secrets.token_urlsafe(32)`.
- Persists `sha256(token)`, target `user_id`, and a 15-minute expiry
  in a new `recovery_tokens` table. Never persists the raw token.
- Prints the raw token to stdout (visible in `docker logs` when run
  via `docker exec`). Same trust model as env-var bootstrap
  (`bootstrap_auth_from_env` in `config.py`) — whoever can read logs
  or exec into the container is the trusted operator.

### Redemption: new route

`POST /auth/recover`

Request body: `{"token": str, "new_password": str}`

- Look up `recovery_tokens` by `sha256(token)`. Reject if not found,
  already used (`used_at` set), or expired.
- Reset the target user's `password_hash` via the existing
  `hash_password()` path.
- Bump `users.session_version` for that user (see below) so any
  existing session dies.
- Mark the token used (`used_at = now`) — single use.
- Rate-limited identically to `/auth/login` (same `_client_key` /
  lockout machinery), keyed separately so a `/recover` brute-force
  attempt doesn't reuse the login lockout counter for a legitimate
  operator's real login attempts.

No email, no SMTP — out of scope per the readiness doc's own
reasoning (too heavy for this app).

### Session invalidation: per-user session_version

Sessions today are stateless: a single global `secret_key` signs
`{"u": username, "uid": user_id}` with no per-user versioning
(`security.py`). Recovery must be able to kill a specific user's
sessions without rotating the global secret (which would log out
every user of the instance).

- New column: `users.session_version INTEGER NOT NULL DEFAULT 0`
  (migration in `db.py`, same pattern as
  `_migrate_container_flags_check`).
- `issue_session_cookie` includes `"sv": user.session_version` in the
  signed payload.
- `_verify_raw_cookie` / `require_auth` in `security.py` additionally
  loads the user and rejects (401, same "Session expired or invalid"
  message) if `data.get("sv") != user.session_version`.
- Recovery increments `session_version` by 1 for the target user as
  part of the password reset transaction.
- `set-password` CLI (existing) should also bump `session_version` —
  consistent behavior, same reasoning: changing a password should
  invalidate old sessions. This is a small addition to existing code,
  included in this pass since it shares the same code path.

### Frontend: `/recover` page

New route in `frontend/src/pages/` (follow existing page structure —
check `LoginPage.tsx` for the pattern to match). Two fields: token,
new password. On submit, `POST /auth/recover`; on success redirect to
`/login`; on error show the returned message inline (expired/invalid
token, weak password, etc — reuse whatever password validation
`/auth/register` already applies).

No link to this page from the login page — it's operator-invoked
(they got the token from logs), not user-discoverable, avoiding a
lockout-oracle UI element that invites brute-forcing.

### Docs

- README troubleshooting section: document both recovery paths — the
  existing `dockwatch config set-password` CLI command and the new
  `recover-admin` token flow — so this is discoverable without
  reading source.
- CHANGELOG entry (see below, bundled with gap #8).

## Out of scope

- Multi-admin username selection (`--username` flag) — earliest-admin
  default only, per approved design choice.
- Email-based reset — explicitly rejected as too heavy for this app's
  scope, matches the readiness doc's own ordering.
- Accessibility, mobile responsiveness, self-update-check (readiness
  doc gaps #4–#6) — explicitly deferred, tracked but not urgent per
  the doc's own "suggested order of work."

## Testing

- New `test_auth.py` cases: recover-admin CLI generates a valid token
  targeting the right user; `/auth/recover` accepts a valid unexpired
  unused token and rejects expired/used/invalid ones; password reset
  actually changes login credentials; old session cookie is rejected
  after recovery; rate limiting on `/auth/recover` behaves like login.
- Manual check: full flow — lock out, run CLI, capture token from
  stdout, hit `/recover` via the new frontend page, confirm old
  session's cookie now 401s and new password logs in.

## Bundled non-architectural work (gaps #7, #8)

Tracked in the same implementation plan since they're cheap and the
plan needs a CHANGELOG entry anyway for the recovery feature itself:

- **#7 — git tags**: tag existing releases retroactively
  (`git tag v0.7.0` .. `v0.7.3` on the commits that bumped
  `pyproject.toml`/version strings), document the tag-on-bump process
  going forward (a line in `CONTRIBUTING.md` or README dev section —
  check if one exists first).
- **#8 — session docs**: CHANGELOG entry covering this session's
  undocumented features (per-container auto-update toggle, log
  viewer, crimson accent, action-menu refactor, the breaking
  `set-password --create` flag change) plus the new recovery feature.
  README feature list updated to match.
