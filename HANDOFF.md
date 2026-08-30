# Handoff: Multi-User RBAC + Registration for dockwatch

## Where things stand

Branch: `feature/simple-auth` (repo root: `D:\Programs\gitrepos\PROJS\2026\dockpkgWatch`)

Two features have landed on this branch so far, in order:

1. **Simple single-operator auth** (commit `4ee9d72`) — one username/password pair stored in `config.toml`, signed cookie sessions, blanket `Depends(require_auth)` gate on every API route except `/auth/*`, `/health`, and the static frontend. Fully implemented, tested (212 backend tests passing), and live-verified against a running container.
2. **Design spec for the next feature** (commit `839d735`, this handoff describes it) — multi-user RBAC with self-service registration. **Design only, zero implementation yet.** The full spec is at `docs/superpowers/specs/2026-07-25-rbac-registration-design.md` — read that file in full before writing any code, this handoff summarizes it but the spec is the source of truth for exact schemas/logic.

## Why this feature exists

The user wants dockwatch to support multiple accounts on the same server ("different accounts for docker containers"), with:
- Self-service registration, gated on/off by an env var.
- Named-permission roles (they explicitly asked for **fully custom roles**, not just a fixed admin/viewer split) — an admin can create a role with any subset of five fixed permissions and assign it to users.
- First person to ever register becomes admin automatically.

This directly builds on and replaces the single-credential auth from feature #1 above — that auth model's `config.toml`-stored username/password is now a legacy bootstrap path that migrates into the new multi-user table, not the permanent storage mechanism.

## The permission model (fixed, do not add/remove without asking)

Five permissions, decided during brainstorming and not open for re-litigation without the user's input:
- `view_containers`
- `update_containers` (covers update/pin/unpin/compose-detect — anything that mutates or inspects a specific container's deploy state)
- `scan_containers` (Trivy)
- `manage_settings` (also gates *reading* settings — settings contains sensitive data like webhook URLs and the Portainer API key, so read is not lower-privilege than write here)
- `manage_users` (covers user AND role management — creating/editing/deleting both users and custom roles)

Scope is **global only** in this iteration — a permission applies to every container or none. No per-container/per-environment access grants. This was explicitly decided against in favor of shipping something simpler first; don't add it unless asked.

## Three decisions the user explicitly resolved (all confirmed, not still open)

1. **Custom role creation ships now**, not deferred. `POST/PATCH/DELETE /roles/{name}` are part of this feature, not a "later" item. The user said "create a detailed handoff md document then build it now" when asked whether to defer this — that's why this document exists.
2. **First registration is always allowed**, regardless of the `DOCKWATCH_ALLOW_REGISTRATION` env var. The var only gates registration *after* at least one user exists. This is the only way to get the first admin account without CLI access.
3. **Last-admin protection is hard-blocked** (409, not a warning-and-proceed) — but defined precisely as "at least one user must hold a role granting `manage_users`," not "the literal `admin` role can't be deleted." A custom role that also carries `manage_users` satisfies the invariant just as well as the built-in `admin` role does. Get this distinction right — it's tested explicitly in the spec's testing section (create a second `manage_users`-holding custom role, confirm the original admin CAN then be safely demoted).

## What already exists that this feature builds on (read these files first)

- `src/dockwatch/db.py` — `ManifestStore` class. Already has `manifest_state`, `trivy_scan_cache`, `container_flags` tables, all following the same pattern: short-lived per-call `sqlite3.connect()`, WAL mode, `BEGIN IMMEDIATE` before writes, plain connection for reads. The new `users`/`roles` tables go directly into this same class/file, same pattern — no new store class. Look at how `container_flags`'s methods (`add_flag`, `remove_flag`, `_get_flags` etc.) are written; the new `create_user`/`get_role`/etc. methods should read like siblings of those, not a different style.
- `src/dockwatch/config.py` — has `AuthConfig` (username, password_hash, secret_key), `hash_password`/`verify_password` (stdlib PBKDF2-SHA256, 600k iterations — reuse these, don't add a new hashing scheme), `bootstrap_auth_from_env`, `ensure_auth_secret`, and the existing `migrate_pinned_ignored_to_db` — this last one is the *exact* pattern to copy for the new `migrate_auth_config_to_users` function (guarded by "only runs if target table is empty," idempotent, no re-import on second call).
- `src/dockwatch/api/security.py` — `require_auth`, `verify_session_cookie`, `issue_session_cookie`, `clear_session_cookie`. The cookie payload is currently `{"u": username}`; the spec calls for changing this to `{"u": username, "uid": user_id}` and having `require_auth` do a DB lookup by `uid` on every request rather than trusting the cookie's contents beyond identity. Read the whole file — it's short (~50 lines).
- `src/dockwatch/api/routes/auth.py` — `login`/`logout`/`session_status`, plus the in-memory lockout dict (`_failed_attempts`, keyed by client IP, 5 attempts / 5 min window). `POST /auth/register` and `GET /auth/registration-enabled` are new additions to this same file.
- `src/dockwatch/api/app.py` — currently applies `dependencies=[Depends(require_auth)]` at `include_router(...)` call time for every router except `auth`. This blanket approach goes away — the spec calls for moving to per-route `Depends(require_permission("..."))` inside each route file, since a single router (e.g. `containers.py`) now needs different permissions on different routes within it.
- `tests/test_auth.py` — the existing auth test file. **Important gotcha already solved here, do not rediscover it**: `dockwatch.config.CONFIG_PATH` is a module-level constant frozen at first import, and `load_config`'s `path: Path = CONFIG_PATH` default argument is *also* bound at function-definition time, not call time. `monkeypatch.setenv("USERPROFILE", ...)` alone does NOT redirect either of these once the module has been imported once in the test process. The existing tests solve this via a `_patch_config_path(monkeypatch, tmp_path)` helper that does `monkeypatch.setattr(config_module, "CONFIG_PATH", path)` AND `monkeypatch.setattr(config_module.load_config, "__defaults__", (path,))`. Any new test file touching config/auth must use this same helper or duplicate its logic — this bit me hard during the first auth feature and cost significant back-and-forth to diagnose; don't lose that lesson.
- `src/dockwatch/main.py` — has `@app.callback()` (a Typer root callback that already runs `migrate_pinned_ignored_to_db` before every CLI invocation) and `dockwatch config set-password` (sets the legacy single-credential `AuthConfig`, will likely need a CLI equivalent for the new user table, or at least needs to keep working as a fallback/recovery path — spec doesn't explicitly say to remove it, so leave it working unless it conflicts with the new model).

## Full spec location

`docs/superpowers/specs/2026-07-25-rbac-registration-design.md` in this repo. It has, in full detail: the exact SQL schema for `roles`/`users`, every new `ManifestStore` method signature, the exact `AuthenticatedUser` dataclass and `require_permission` factory code, a complete route→permission mapping table, every new route (`/auth/register`, `/auth/registration-enabled`, and the full `routes/users.py` file including role CRUD), the migration function's exact code, frontend changes (`RegisterPage.tsx`, a users/roles management UI, `/auth/session`'s expanded response shape), and a full testing checklist. Read it end to end — this handoff is a map to it, not a replacement for it.

## Next step

The spec has been through brainstorming and is user-approved. The next step is to invoke the **writing-plans** skill to turn the spec into a concrete, task-by-task implementation plan (following this project's established pattern — see `docs/superpowers/plans/2026-07-22-pinned-ignored-to-sqlite.md` for what a good plan for a similarly-sized SQLite-migration-shaped feature looked like last session, including how it broke work into reviewable tasks and what its Global Constraints section covered). Then execute via subagent-driven-development, same as that prior feature — dispatch a fresh implementer per task, review each task's diff before moving on, final whole-branch review at the end via a most-capable-model reviewer.

Do not skip the plan step and start writing code directly — this feature touches the data model, the session/cookie format, every route file, and three new/expanded frontend pages. That's exactly the shape of work the writing-plans + subagent-driven-development combination exists for, and skipping straight to implementation risks the same kind of cross-task integration gap the final review caught last time (the CLI-vs-server migration wiring gap, in the SQLite plan) — except this feature has more moving parts, not fewer.
