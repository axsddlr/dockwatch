# dockpkgWatch Next Steps

- [ ] Run the full unit test suite in a dependency-complete Python environment and fix any failures.
- [ ] Decide what to do with the remaining untracked workspace files: `.gitignore`, `design/`, and `idea.txt`.
- [ ] Deduplicate `build_registry_url()` and `build_registry_link()` so the link helper has one source of truth.
- [ ] Add a small CLI smoke test for the new `Link` column output in the Rich tables.
- [ ] Add a dashboard smoke test for the per-row registry/source link rendering.
- [ ] Decide whether GHCR and LSCR links should stay fallback-only or gain source metadata enrichment.

## Improvement Plan - 2026-04-07

Generated: 2026-04-07
Codebase: dockwatch

## Critical Priority
- [x] Replace manual TOML interpolation with safe TOML serialization - `src/dockwatch/config.py:80` - Quoted URLs, backslashes, or future string fields can produce invalid config files and break startup. Implemented in commit `e9e4758`.
- [x] Stop rewriting the config file on every read - `src/dockwatch/config.py:130` - Loading should not strip comments or mutate user-managed formatting as a side effect. Implemented in commit `e9e4758`.
- [x] Isolate unexpected per-container failures inside the batch runner - `src/dockwatch/registry.py:482` - One uncaught exception can abort the entire check run and daemon cycle. Implemented in commit `60db01a`.
- [x] Make manifest event recording atomic - `src/dockwatch/db.py:76` - The current read-then-write split can misclassify `new` vs `update` under concurrent runs. Implemented in commit `f2ef598`.
- [x] Add retry/backoff around registry HTTP calls - `src/dockwatch/registry.py:233` - Transient registry failures currently become false `UNKNOWN` results with no recovery attempt. Implemented in commit `d5a8e71`.

## High Priority
- [x] Reuse a shared `httpx.AsyncClient` per run instead of creating one per registry check - `src/dockwatch/registry.py:234` - Current connection churn will scale poorly with more containers and increases rate-limit pressure. Implemented in commit `65bdb41`.
- [x] Add retry/backoff to notifier delivery - `src/dockwatch/notifiers/webhook.py:40` - A brief network flap currently drops notifications outright. Implemented in commit `606911a`.
- [x] Normalize manifest identity away from raw `image_ref|current_tag` - `src/dockwatch/db.py:25` - Equivalent image refs can map to different rows and weaken persistence continuity. Implemented in commit `9b943c0`.
- [x] Fix the false-success notification path in the CLI - `src/dockwatch/main.py:93` - The CLI can print `Notifications sent.` even when filters suppress all deliveries. Implemented in commit `606911a`.
- [x] Collapse the duplicated registry-check flow - `src/dockwatch/registry.py:214` - Token fetch, tag fetch, filter, manifest fetch, and result assembly are repeated three times and will drift. Implemented in commit `ccad2d5`.
- [x] Collapse repeated `ContainerInfo(...)` construction paths - `src/dockwatch/docker_client.py:73` - The parser repeats the same field mapping across multiple return branches, which is a maintenance trap. Implemented in commit `1b9c5bf`.
- [x] Add direct tests for Docker label parsing and container discovery - `src/dockwatch/docker_client.py:190` - Current tests cover registry/config logic but not the Docker metadata boundary that feeds everything else. Implemented in commit `1b9c5bf`.

## Medium Priority
- [x] Turn off browser auto-open in server mode - `src/dockwatch/web/app.py:16` - `show=True` is a poor default for headless hosts and containers. Implemented in commit `9229faf`.
- [x] Add CLI coverage for the main command surfaces - `src/dockwatch/main.py:51` - `check`, `daemon`, and `notify test` are unverified compared with the smaller config commands. Implemented in commit `13474f1`.
- [x] Add dashboard/component smoke tests - `src/dockwatch/web/pages/dashboard.py:19` - The web path is featureful but currently untested. Implemented in commit `b98bb53`.
- [x] Deduplicate link generation so one helper owns both label and URL - `src/dockwatch/links.py:18` - `build_registry_url` and `build_registry_link` repeat the same routing logic. Implemented in commit `13474f1`.
- [x] Make the CLI `Link` column actionable or rename it - `src/dockwatch/display.py:28` - Showing only `Hub`/`Repo`/`Source` reads like a link but is not usable in terminal output. Implemented in commit `13474f1`.
- [x] Align the documented test command and CLI reference - `README.md:116` - Docs omit newer commands and tell contributors to run a different test command than CI. Implemented in commit `13474f1`.
- [x] Remove or make optional the forced dark-mode side effect - `src/dockwatch/web/pages/dashboard.py:25` - Global theme selection inside controller construction makes future UI behavior harder to control. Implemented in commit `352c058`.
- [x] Align the auto-refresh lower bound between the input and handler - `src/dockwatch/web/pages/dashboard.py:37` - The UI advertises a 10-second minimum but the callback accepts 1 second. Implemented in commit `352c058`.

## Architecture Notes
The project has a good split between config, discovery, registry, notification, and UI layers.

The main debt is orchestration logic accumulating in `registry.py`, `main.py`, and `dashboard.py`, where side effects and branching are starting to outgrow the current structure.

Tests are solid for config parsing, registry selection, manifest storage, and notifier filtering, but they do not yet cover the Docker API boundary, CLI output paths, or the NiceGUI surface.
