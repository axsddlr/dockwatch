# dockpkgWatch Outdated Detection Plan

## Context
- **Goal:** Port the useful Tugtainer-style digest-first outdated detection approach into `dockpkgWatch` in a way that matches this repo's architecture and UX.
- **Primary users:** Operators checking whether their running Docker containers are out of date.
- **Current state:** `dockpkgWatch` already discovers running containers, inspects deployed digests and labels, queries registries, and renders CLI/dashboard status. The existing logic is close to the target but needs clearer phases, stronger comparison evidence, and more consistent output.
- **Non-goals:**
  - Editing or depending on the upstream `Quenary/tugtainer` codebase.
  - Replacing digest comparison with version-only heuristics.
  - Supporting arbitrary registries beyond the currently handled Docker Hub, GHCR, and LSCR flows.

## Core Rule
- Digest comparison is the source of truth for whether a container is outdated.
- Version and tag information are explanatory metadata used to tell the user *what* is deployed and *what* the registry currently points to.
- When evidence is weak, the UI must say so directly instead of pretending the version is precise.

## Tugtainer Logic To Reuse Here
1. Read the user's deployed container image reference and local digest.
2. Ask the remote registry for the digest behind the relevant tag.
3. Mark the container outdated when the remote digest differs from the deployed digest.
4. Use version labels or non-floating tags only to explain the result, not to replace the digest check.

## Phase 1: Plan And Core Comparison Model

### Scope
- Rewrite this plan so it targets `dockpkgWatch`.
- Tighten the internal comparison model in:
  - `src/dockwatch/models.py`
  - `src/dockwatch/registry.py`
- Make deployed-vs-remote evidence explicit and testable.

### Intended Changes
- Standardize comparison metadata fields on `UpdateResult`.
- Add helper functions for deployed/remote version display and evidence summaries.
- Preserve digest-first behavior when local and remote digests are both available.

### Acceptance Criteria
- [ ] A maintainer can read the model and understand whether a result came from digest, version, or tag comparison.
- [ ] Floating tags such as `latest` continue to prefer digest checks over semver guesses.
- [ ] Tests cover digest drift under the same tag and exact digest match for floating tags.

## Phase 2: Registry Evidence And Persistence

### Scope
- Improve how registry checks carry comparison evidence through the pipeline.
- Extend persistence in:
  - `src/dockwatch/db.py`
- Preserve the evidence needed to explain changes across runs.

### Intended Changes
- Persist the remote digest and latest observed tag in a way that remains stable across equivalent image refs.
- Record enough comparison evidence to classify `new` vs `update` consistently when only version/tag info changes.
- Harden unknown/error paths so failures degrade cleanly without breaking checks for other containers.

### Acceptance Criteria
- [ ] Manifest observations still classify `new` and `update` correctly.
- [ ] Equivalent image references continue to collapse to the same identity.
- [ ] A changed remote tag without a digest change is still visible as a meaningful update signal when appropriate.

## Phase 3: User-Facing Output

### Scope
- Surface the comparison evidence clearly in:
  - `src/dockwatch/display.py`
  - `src/dockwatch/web/components/container_table.py`
- Keep output compact but precise.

### Intended Changes
- Show deployed vs remote information more clearly for floating tags.
- Make the "Why" field and dashboard explanation match the actual comparison basis.
- Avoid overstating certainty when only tag heuristics are available.

### Acceptance Criteria
- [ ] CLI output clearly shows whether the status came from digest, version, or tag evidence.
- [ ] Dashboard cards render the same explanation as the CLI.
- [ ] Tests cover at least one digest-based floating-tag case and one version-based non-floating-tag case.

## Verification
- [ ] `tests/test_registry.py`
- [ ] `tests/test_db.py`
- [ ] `tests/test_display.py`
- [ ] `tests/test_dashboard_component.py`

## Commit Plan
1. `docs(plan): rewrite outdated detection plan for dockpkgWatch`
2. `feat(registry): formalize digest-first comparison evidence`
3. `feat(ui): surface deployed vs remote comparison details`
