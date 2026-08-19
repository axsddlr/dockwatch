# Portainer + non-compose rollback — design

Status: draft, pending review.
Scope: extend rollback to Portainer-managed compose stacks and plain
(non-compose) local containers. Local compose rollback already works
and is unaffected by this change.

## Problem

`POST /containers/{name}/rollback` (`api/routes/containers.py:192`)
always calls `build_rollback_plan` then `execute_update` — the
**local-only** executor. `build_rollback_plan` (`updater.py:199`)
hard-blocks anything that isn't `_is_compose_managed(result)` +
`info.source == "local"`:

```python
if not _is_compose_managed(result):
    return _blocked_plan(result, "rollback is only supported for compose-managed containers")
if info.source != "local":
    return _blocked_plan(result, "read-only source; only local Docker rollbacks are supported")
```

So today, rollback silently 422s for:
1. **Portainer-sourced compose stacks** (`info.source == "portainer"`)
2. **Plain/non-compose local containers** (`mode == "plain"` on update)

Both gaps are narrower than they look — the *update* path already
handles both cases correctly and already records the `old_tag`/
`new_tag` history rollback needs (`_log_action` in
`containers.py:179` runs for every mode). Rollback just never grew a
matching branch when Portainer support and plain-mode update were
added. This is a symmetry gap, not a missing subsystem.

## Design

### 1. Portainer-managed compose stack rollback

`execute_portainer_compose_update` (`updater.py:631`) already does
everything a rollback needs: fetch the stack file, rewrite one
service's image tag via `_replace_service_image`, call
`client.update_stack(..., pullImage=True)`. It's parameterized by
`plan.current_tag` / `plan.remote_tag` — for a forward update these
are (deployed, new); for a rollback they're just (deployed, old).
**No new Portainer API calls needed.**

Changes:

- `build_rollback_plan`: replace the blanket
  `info.source != "local"` block with a branch —
  - `source == "portainer"`: skip the `compose_projects` config
    lookup (that's a local-compose-only concept; Portainer stacks
    aren't in `config.compose_projects`). Still require
    `_is_compose_managed(result)` and the existing
    `info.current_tag != new_tag` staleness check. Set
    `mode="portainer-compose"` on the returned plan (matching the
    update path's mode name) instead of `mode="compose"`.
  - `source == "local"`: existing behavior, unchanged.
- `rollback_container` route: branch on `plan.mode` the same way
  `update_container` already does —
  ```python
  if plan.mode == "portainer-compose":
      execution = await execute_portainer_compose_update(plan, config)
  else:
      execution = await asyncio.to_thread(execute_update, plan, config)
  ```
  (Literally the same dispatch `update_container` already has —
  extract to a shared helper, e.g. `_execute_plan`, used by both
  routes, rather than duplicating the branch.)

No new fields needed on `UpdatePlan` — `environment_id` and
`compose_project`/`compose_service` are already populated by
discovery for Portainer-sourced containers.

### 2. Plain (non-compose) local container rollback

Trickier: compose rollback works by rewriting a tag in a file and
re-running `up`. Plain mode has no such file — `_execute_plain_update`
recreates the container directly from `plan.image_ref` (repo:tag).

Reuse is straightforward because rollback *is* forward update with
swapped tags — the exact same recreate-by-image-ref machinery
(`_create_replacement_container`, stop/rename/create/start,
same-name/same-ID guard, `_rollback_plain_update` failure-path
cleanup) works unchanged if `plan.image_ref` points at the old tag.

Changes:

- `build_rollback_plan`: when `not _is_compose_managed(result)` (i.e.
  what update calls `mode="plain"`), don't block — build a `plan`
  with `mode="plain"`, `image_ref` rewritten to
  `f"{repo}:{old_tag}"` (repo split the same way
  `_rewrite_compose_image_tag` already does:
  `plan.image_ref.rsplit(":", 1)[0]`), and the same
  `info.current_tag != new_tag` staleness guard as the compose
  branch (still meaningful: confirms nothing else re-updated the
  container between the recorded update and this rollback attempt).
- `execute_update`'s existing `mode == "compose"` / else dispatch
  already routes anything not `"compose"` to `_execute_plain_update`
  — **no executor change needed**, only plan construction.

One caveat worth flagging in review, not blocking: plain-mode
rollback pulls `old_tag` fresh (`client.images.pull` in
`_execute_plain_update_with_client`) rather than restoring a locally
cached image layer — if the registry has since deleted/overwritten
that tag, rollback will fail with a pull error. Same limitation
already exists for plain-mode *forward* updates; not new here.

### 3. Frontend / API surface

No changes needed. `HistoryPanel.tsx`'s rollback button and
`api.containers.rollback` already call the existing route
unconditionally; today it 422s with `plan.reason` for
Portainer/plain containers, which the existing error-toast path
already surfaces. After this change the same button starts working
for those containers — pure backend capability unlock.

## Out of scope

- Plain-mode rollback via cached image (avoiding the re-pull) —
  would need image-ID tracking in history, not just tag strings.
  Bigger change, not needed for parity with current update behavior.
- Digest-pinned rollback — update already blocks digest-pinned
  images (`DIGEST_PINNED_TAG` / `"@" in info.image_ref` checks);
  rollback inherits the same exclusion via `build_update_plan`'s
  history entry never existing for those in the first place.

## Testing

- `test_updater.py` (or wherever `build_rollback_plan`/
  `build_update_plan` are currently tested): add cases —
  - Portainer-sourced compose container: rollback plan builds with
    `mode="portainer-compose"`, tags swapped correctly.
  - Portainer stack not found: rollback surfaces the same "no
    Portainer stack found" error the update path already returns.
  - Plain local container: rollback plan builds with `mode="plain"`,
    `image_ref` rewritten to old tag.
  - Existing local-compose rollback tests continue passing unchanged
    (regression guard for the refactor extracting the shared dispatch
    helper).
- Manual check: update a Portainer-managed container from the
  dashboard, then roll it back — confirm the stack file's tag
  reverts and Portainer redeploys. Same for a plain local container
  (e.g. one of the `_demo-stacks/` containers run without compose).
