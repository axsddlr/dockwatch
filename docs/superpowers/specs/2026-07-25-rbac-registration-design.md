# Multi-User RBAC + Registration Design

## Context

The previous feature (`feature/simple-auth`, already merged in this branch) added single-operator username/password authentication: one `AuthConfig` (username, PBKDF2 password hash, cookie-signing secret) stored in `config.toml`, a signed HTTP-only session cookie, and a blanket `Depends(require_auth)` gate on every router except `/auth/*`, `/health`, and the static frontend.

The user wants dockwatch to support multiple accounts on the same server — "different accounts for docker containers" — with self-service registration (env-var gated) and named-permission roles, so a server operator can grant different people different levels of access without sharing one credential.

This design replaces the single-credential model with a `users`/`roles` schema, keeps the existing signed-cookie session mechanism, and introduces per-route permission checks instead of the current binary gate.

## Decisions (from brainstorming, do not re-litigate)

- **Permission set** (fixed, five permissions): `view_containers`, `update_containers`, `scan_containers`, `manage_settings`, `manage_users`.
- **Scope**: global only. A permission either applies to all containers or none — no per-container/per-environment scoping in this iteration.
- **Registration gate**: `DOCKWATCH_ALLOW_REGISTRATION=true|false` (default `false`) controls `POST /auth/register` entirely. When `false`, that endpoint always 403s; new users can only be created by an existing `manage_users` holder via the admin-only user-management routes.
- **First registrant becomes admin**: if `count_users() == 0` at registration time, the new account gets the `admin` role (all five permissions) regardless of the registration-gate setting for that one bootstrap case — see "Registration-gate interaction with first-admin bootstrap" below for the exact logic.
- **Existing single-credential migration**: on first startup after this upgrade, if `config.toml`'s `AuthConfig.password_hash` is set and no users exist yet, migrate it into a `users` row as the first `admin` account (same username + password hash, no re-registration required). `AuthConfig`'s fields become unused afterward.
- **Storage**: extend the existing `ManifestStore` (`db.py`) with two new tables, following the exact `container_flags` convention already established (composite keys where natural, `BEGIN IMMEDIATE` on writes, plain-connection reads, short-lived per-call connections). No new store class.
- **Settings visibility**: `GET /settings` requires `manage_settings`, same as `PUT` — settings contains sensitive data (webhook URLs, Portainer API key, compose paths), not something a `viewer` should see even read-only.

## Data model

Two new tables in `ManifestStore._initialize()`, added the same way `container_flags` was added last session:

```sql
CREATE TABLE IF NOT EXISTS roles (
    name TEXT PRIMARY KEY,
    permissions TEXT NOT NULL,  -- JSON array of permission strings
    is_builtin INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role_name TEXT NOT NULL REFERENCES roles(name),
    created_at TEXT NOT NULL
);
```

Two built-in roles are seeded once, on first `_initialize()` run (guarded so re-seeding is a no-op if they already exist, same idempotency pattern as `migrate_pinned_ignored_to_db`):
- `admin`: all five permissions, `is_builtin = 1`.
- `viewer`: `["view_containers"]` only, `is_builtin = 1`. This is the role new self-registered (non-first) users land in.

`is_builtin` blocks deletion and permission-editing of these two default roles specifically — `admin` and `viewer` are fixed. **Custom role creation is in scope for this iteration** (confirmed): `manage_users` holders can create additional roles with any subset of the five permissions, rename/delete them (custom roles only — `is_builtin = 0`), and assign them to users exactly like `admin`/`viewer`. See "New routes" below for `POST /roles`/`DELETE /roles/{name}`.

New `ManifestStore` methods (mirroring `container_flags`'s method style):
- `create_user(username, password_hash, role_name) -> int` (returns new user id; raises on duplicate username)
- `get_user_by_username(username) -> UserRecord | None`
- `get_user_by_id(user_id) -> UserRecord | None`
- `list_users() -> list[UserRecord]`
- `update_user_role(user_id, role_name) -> bool`
- `delete_user(user_id) -> bool`
- `count_users() -> int`
- `get_role(name) -> RoleRecord | None`
- `list_roles() -> list[RoleRecord]`

`UserRecord`/`RoleRecord` are small dataclasses (matching `ManifestRecord`'s existing style in `db.py`), not raw tuples.

## Session and auth-dependency changes

**Cookie payload** changes from `{"u": username}` to `{"u": username, "uid": user_id}`. `uid` is the primary lookup key going forward (usernames can theoretically be renamed later; ids are stable) — `u` is kept for display/logging convenience but `require_auth` resolves the user via `uid`.

**`require_auth`** (`security.py`) still verifies the signed cookie's signature and expiry exactly as before, but instead of returning a bare `str`, it now looks up the user by id via `ManifestStore.get_user_by_id`, resolves their role's permissions via `get_role`, and returns:

```python
@dataclass(slots=True)
class AuthenticatedUser:
    user_id: int
    username: str
    role_name: str
    permissions: frozenset[str]
```

If the looked-up user no longer exists (deleted since the cookie was issued) or their role no longer exists, `require_auth` raises `401` — this is what makes role changes and account deletion take effect on the very next request rather than waiting for the cookie to expire or the user to log out. The cost is one additional SQLite read per authenticated request; this matches the existing pattern where `load_config()` is already called fresh on every request with no caching, so it's consistent with the codebase's existing performance posture, not a new tradeoff class.

**`require_permission(permission: str)`** is a new dependency factory in `security.py`:

```python
def require_permission(permission: str):
    def _check(user: AuthenticatedUser = Depends(require_auth)) -> AuthenticatedUser:
        if permission not in user.permissions:
            raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")
        return user
    return _check
```

Every existing router-level `dependencies=[Depends(require_auth)]` in `app.py` is removed in favor of per-route `Depends(require_permission("..."))` declarations inside each route file, since a single router (e.g. `containers.py`) now mixes routes needing different permissions (`view_containers` for listing, `update_containers` for updates). `app.py` still gates `/debug/dist` directly, using `manage_settings` (it exposes internal filesystem info — settings-tier sensitivity).

## Route → permission mapping

| Route(s) | Permission |
|---|---|
| `GET /containers`, `POST /containers/check` | `view_containers` |
| `POST /containers/{name}/update`, `POST/DELETE /containers/{name}/pin`, `GET /containers/{name}/compose-detect`, `POST /containers/{name}/compose-detect/validate` | `update_containers` |
| `GET/POST/DELETE /containers/{name}/scan` | `scan_containers` |
| `GET/PUT /settings`, `POST /settings/test-notification`, `POST /settings/test-portainer`, `GET /environments`, `GET /debug/dist` | `manage_settings` |
| `GET/POST /users`, `PATCH/DELETE /users/{id}`, `GET /roles` | `manage_users` |
| `WEBSOCKET /ws` | `view_containers` |
| `POST /auth/login`, `POST /auth/logout`, `GET /auth/session`, `GET /auth/registration-enabled` | ungated |
| `POST /auth/register` | ungated at the dependency layer, but 403s internally if `DOCKWATCH_ALLOW_REGISTRATION` is not `true` **and** at least one user already exists (see "Registration-gate interaction with first-admin bootstrap" below) |

## New routes

- **`POST /auth/register`** (`routes/auth.py`) — body `{username, password}`. Logic: if `count_users() > 0` and `DOCKWATCH_ALLOW_REGISTRATION` env var is not `"true"`, raise `403`. Otherwise create the user (role = `admin` if `count_users() == 0` else `viewer`), issue a session cookie (auto-login, matching `/auth/login`'s response shape), return `{"ok": true, "username": ...}`.
- **`GET /auth/registration-enabled`** (`routes/auth.py`, ungated, no side effects) — returns `{"enabled": bool}` so the frontend can decide whether to show the "Register" link on the login page without needing to attempt a registration first. Also returns `true` unconditionally when `count_users() == 0` (bootstrap case is always allowed regardless of the env var, since there is no admin yet to gate against).
- **`routes/users.py`** (new file, all routes require `manage_users`):
  - `GET /users` — list all users (id, username, role_name, created_at — never password_hash).
  - `POST /users` — admin manually creates a user with a chosen role (used when self-registration is disabled).
  - `PATCH /users/{id}` — change a user's `role_name`. Hard-blocked (422/409) if this would leave zero users with a role granting `manage_users` (see "Last-admin protection" below — the check is really "last user who can manage users," not literally "last user named admin," since a custom role could also carry `manage_users`).
  - `DELETE /users/{id}` — same hard-block as above, plus refuses self-deletion (must be done by a different `manage_users` holder).
  - `GET /roles` — list all roles (built-in + custom) for the frontend's role-selection dropdown.
  - `POST /roles` — create a custom role: `{name, permissions: string[]}`. Rejects names colliding with `admin`/`viewer`, rejects unknown permission strings, rejects empty-permission roles.
  - `PATCH /roles/{name}` — update a custom role's permission set. 403/422 if the role is `is_builtin`.
  - `DELETE /roles/{name}` — delete a custom role. 403/422 if `is_builtin`. Hard-blocked if any user currently holds this role (reassign or delete those users first — no cascading role reassignment, to avoid silently changing someone's access).

## Last-admin protection

Hard-blocked (confirmed), and defined precisely as: **at least one user must always hold a role that grants `manage_users`.** This is a live check against current role assignments and permission sets, not a hardcoded reference to the literal `admin` role name — a custom role that includes `manage_users` counts too. Both `PATCH /users/{id}` (role change) and `DELETE /users/{id}` compute "would this action leave zero users with `manage_users`?" before applying, and reject with `409 Conflict` if so. Same check applies to `DELETE /roles/{name}`: deleting a custom role is blocked if any user currently holds it (regardless of whether that role happens to grant `manage_users` — this is the simpler "no orphaned role references" rule, and it subsumes the admin-lockout case for custom roles since a user can't be demoted out of a role that's being deleted out from under them without an explicit reassignment step first).

## Registration-gate interaction with first-admin bootstrap

Confirmed: the very first registration is **always** allowed, regardless of `DOCKWATCH_ALLOW_REGISTRATION`. `POST /auth/register`'s logic is precisely:

```python
if store.count_users() == 0:
    role = "admin"
    # always allowed — this is the only way to get an admin account
    # without touching the CLI or a pre-existing config.toml credential
elif os.environ.get("DOCKWATCH_ALLOW_REGISTRATION") == "true":
    role = "viewer"
else:
    raise HTTPException(status_code=403, detail="Registration is disabled.")
```

`GET /auth/registration-enabled` mirrors this exactly: returns `{"enabled": true}` whenever `count_users() == 0` OR the env var is `"true"`, so the frontend's "Register" link visibility always matches what `/auth/register` will actually accept.

## Migration path

A new `config.py` function, `migrate_auth_config_to_users(config: DockwatchConfig, store: ManifestStore) -> None`, called once at startup (same call site as `migrate_pinned_ignored_to_db`, in `api/app.py`'s lifespan and `main.py`'s CLI callback):

```python
def migrate_auth_config_to_users(config: DockwatchConfig, store: ManifestStore) -> None:
    if store.count_users() > 0:
        return
    if not config.auth.password_hash:
        return
    store.create_user(config.auth.username, config.auth.password_hash, role_name="admin")
```

Guarded the same way the pinned/ignored migration was: only runs when the `users` table is empty, so it never re-imports or clobbers accounts created after the first migration. `bootstrap_auth_from_env` (the existing `DOCKWATCH_USERNAME`/`DOCKWATCH_PASSWORD` env-var bootstrap) continues to populate `config.auth` exactly as before — it now just becomes the *input* to this migration rather than the final destination, so no changes are needed to that function itself. The env-var bootstrap path and the registration path both ultimately land in the same `users` table.

## Frontend changes

- **`LoginPage.tsx`**: add a "Register" link/button, shown based on `GET /auth/registration-enabled`'s response (fetched on mount, alongside the existing session check). Hidden if the endpoint returns `{"enabled": false}`.
- **New `RegisterPage.tsx`**: structurally mirrors `LoginPage.tsx` (username/password form, same error-message mapping for 401/429/503, plus a new 403 case: "Registration is disabled."). Posts to `/auth/register`, auto-navigates to `/` on success (matching login's post-success behavior).
- **New `UsersPage.tsx`** (or a "Users" tab folded into `SettingsPage.tsx`'s existing Advanced-disclosure pattern — implementer's call, follows whichever reads more naturally once the settings page is in front of them): lists users via `GET /users`, a role dropdown per row (populated from `GET /roles`) calling `PATCH /users/{id}`, a delete button calling `DELETE /users/{id}`. Entire page/tab is hidden from users without `manage_users` (checked client-side from `/auth/session`'s now-expanded response — see below — as well as enforced server-side).
- **`/auth/session`'s response** expands from `{authenticated, username}` to `{authenticated, username, role, permissions}` so the frontend can conditionally render UI (hide the "Update" button for a `viewer`, hide the Users tab for non-admins) without waiting on a 403 round-trip. This is a UX nicety, not the security boundary — every permission check still happens server-side via `require_permission`.
- **`RequireAuth.tsx`**: no structural change to its binary authenticated/redirect logic. Individual pages/buttons read `permissions` from the session response to conditionally hide actions.

## Testing

Following the existing `tests/test_auth.py` pattern (`TestClient`, `_patch_config_path` for `CONFIG_PATH`/`load_config.__defaults__` isolation, real SQLite via `ManifestStore(path=tmp_path/...)`, no mocking):

- Role seeding: `admin`/`viewer` roles exist after `ManifestStore.__init__`, with the correct permission sets; re-initializing an existing store doesn't duplicate/reset them.
- `create_user`/`get_user_by_username`/`get_user_by_id`/`list_users`/`update_user_role`/`delete_user`/`count_users` — direct `ManifestStore` unit tests, including duplicate-username rejection.
- Registration: first user becomes `admin` regardless of the env var; subsequent registration is blocked with the env var unset/false and allowed (landing in `viewer`) when set to `true`.
- `require_permission`: a `viewer`-role session gets 403 on `update_containers`-gated routes, 200 on `view_containers`-gated routes; an `admin` session gets 200 on everything.
- Role/deletion changes take effect immediately: log in, change the same user's role directly via the store, confirm the very next request re-resolves permissions from the new role (not the cookie).
- Last-`manage_users`-holder protection: attempting to delete or demote the sole remaining user who holds `manage_users` returns a 409, not a silent success.
- Migration: seed `config.toml` with an existing `AuthConfig.password_hash`, run `migrate_auth_config_to_users`, confirm exactly one `admin` user exists with the migrated credentials; running it again is a no-op.
- Custom roles: create a role with a permission subset, assign it to a user, confirm `require_permission` checks reflect exactly that subset (not more, not less); reject creating a role named `admin`/`viewer`; reject creating a role with an unknown permission string; reject deleting/editing a `is_builtin` role; reject deleting a custom role still assigned to a user.
- Last-`manage_users`-holder protection: create a custom role that also grants `manage_users`, assign it to a second user, confirm the original admin CAN now be demoted/deleted (since the custom-role holder covers the invariant) — this is the precise test that the check is permission-based, not name-based.
- Frontend: `npm run build` clean TypeScript; no automated frontend test runner exists in this repo (confirmed in prior sessions), so frontend verification remains manual/build-only, consistent with how the simple-auth feature was verified.

## Resolved decisions (from design review)

1. **First-registration bootstrap always allowed**, independent of `DOCKWATCH_ALLOW_REGISTRATION` — see "Registration-gate interaction with first-admin bootstrap" above.
2. **Custom role creation is in scope for this iteration** — `POST/PATCH/DELETE /roles/{name}` ship alongside user management, not deferred.
3. **Last-admin protection is hard-blocked**, defined as "last user holding `manage_users`" (permission-based, not name-based) — see "Last-admin protection" above.
