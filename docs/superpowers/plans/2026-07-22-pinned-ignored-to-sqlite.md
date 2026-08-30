# Move pinned/ignored from config.toml to SQLite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the `pinned` and `ignored` container-name lists out of `config.toml` and into the existing SQLite `manifests.db`, closing the config read-modify-write race (in-process and cross-process) at the root instead of papering over it with more locks.

**Architecture:** Add a `container_flags` table to `db.py`'s existing `ManifestStore` (same WAL + `BEGIN IMMEDIATE` pattern already used for `manifest_state`/`trivy_scan_cache`). `DockwatchConfig.pinned`/`.ignored` are removed as TOML-backed fields; every read site (`registry.py`'s per-check `set()` build, `main.py` CLI, `api/routes/containers.py` pin/unpin, `api/serializers.py` settings get/put) is repointed at the new store. The per-check hot path in `registry.py` still does exactly one query per check run (not per container) to build the `set[str]`, preserving current performance.

**Tech Stack:** Python 3.12, sqlite3 (stdlib), FastAPI, Typer CLI, pytest.

## Global Constraints

- `ManifestStore` connections are short-lived per-call (`_connect()` opens, `with closing(...)` closes) — follow this exact pattern for the new table, do not hold a connection across requests.
- All writes to the new table go through `BEGIN IMMEDIATE` transactions, matching `record_observation`/`trivy_cache_put`/`trivy_cache_invalidate` in `db.py`.
- `check_all()` in `registry.py` must still build `pinned`/`ignored` as `set[str]` exactly once per check run — no per-container SQL queries in that hot loop.
- The settings API (`PUT /api/settings`) must keep accepting `pinned`/`ignored` as full-list replace (bulk operation), not just single add/remove — the frontend settings form sends the whole list.
- No changes to `DockwatchConfig`'s other fields (`notify_only`, `include_tags`, etc.) — those stay in TOML. Only `pinned` and `ignored` move.
- Existing `config.toml` files may already have `pinned`/`ignored` populated — migration must import them into SQLite on first load, not silently drop them.
- Run `python -m pytest -q` after every task; all tests must pass before moving to the next task.

---

### Task 1: Add `container_flags` table + `FlagStore` methods to db.py

**Files:**
- Modify: `src/dockwatch/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing new (uses stdlib `sqlite3`, existing `ManifestStore._connect()` pattern)
- Produces:
  - `ManifestStore.get_pinned() -> list[str]`
  - `ManifestStore.get_ignored() -> list[str]`
  - `ManifestStore.set_pinned(names: list[str]) -> None` (bulk replace)
  - `ManifestStore.set_ignored(names: list[str]) -> None` (bulk replace)
  - `ManifestStore.add_flag(name: str, kind: str) -> bool` (kind is `"pinned"` or `"ignored"`; returns `True` if newly added, `False` if already present)
  - `ManifestStore.remove_flag(name: str, kind: str) -> bool` (returns `True` if removed, `False` if not present)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db.py` (check existing imports at top of file first — this repo's `ManifestStore` is imported as `from dockwatch.db import ManifestStore`):

```python
class TestContainerFlags:
    def test_add_pin_returns_true_when_new(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        added = store.add_flag("nginx", "pinned")
        assert added is True
        assert store.get_pinned() == ["nginx"]

    def test_add_pin_returns_false_when_already_present(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("nginx", "pinned")
        added_again = store.add_flag("nginx", "pinned")
        assert added_again is False
        assert store.get_pinned() == ["nginx"]

    def test_remove_flag_returns_true_when_present(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("nginx", "pinned")
        removed = store.remove_flag("nginx", "pinned")
        assert removed is True
        assert store.get_pinned() == []

    def test_remove_flag_returns_false_when_absent(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        removed = store.remove_flag("nginx", "pinned")
        assert removed is False

    def test_pinned_and_ignored_are_independent(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("nginx", "pinned")
        store.add_flag("redis", "ignored")
        assert store.get_pinned() == ["nginx"]
        assert store.get_ignored() == ["redis"]

    def test_set_pinned_bulk_replace(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("nginx", "pinned")
        store.set_pinned(["redis", "postgres"])
        assert sorted(store.get_pinned()) == ["postgres", "redis"]

    def test_set_ignored_bulk_replace_empty_list_clears(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("nginx", "ignored")
        store.set_ignored([])
        assert store.get_ignored() == []

    def test_flags_persist_across_store_instances(self, tmp_path):
        path = tmp_path / "test.db"
        store1 = ManifestStore(path=path)
        store1.add_flag("nginx", "pinned")
        store2 = ManifestStore(path=path)
        assert store2.get_pinned() == ["nginx"]

    def test_get_pinned_preserves_insertion_order(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("zebra", "pinned")
        store.add_flag("apple", "pinned")
        assert store.get_pinned() == ["zebra", "apple"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db.py::TestContainerFlags -v`
Expected: FAIL with `AttributeError: 'ManifestStore' object has no attribute 'add_flag'` (or similar — the methods don't exist yet)

- [ ] **Step 3: Add the table and methods to db.py**

In `src/dockwatch/db.py`, add the table creation inside `_initialize()` (after the existing `trivy_scan_cache` table creation, still inside the same `with closing(...)` block):

```python
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS container_flags (
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('pinned', 'ignored')),
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (name, kind)
                )
                """
            )
```

Then add these methods to the `ManifestStore` class, after `trivy_cache_invalidate` (end of class):

```python
    def _get_flags(self, kind: str) -> list[str]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT name FROM container_flags WHERE kind = ? ORDER BY added_at",
                (kind,),
            ).fetchall()
        return [row[0] for row in rows]

    def get_pinned(self) -> list[str]:
        return self._get_flags("pinned")

    def get_ignored(self) -> list[str]:
        return self._get_flags("ignored")

    def _set_flags(self, kind: str, names: list[str]) -> None:
        deduped = list(dict.fromkeys(n.strip() for n in names if n.strip()))
        observed_at = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM container_flags WHERE kind = ?", (kind,))
            connection.executemany(
                "INSERT INTO container_flags (name, kind, added_at) VALUES (?, ?, ?)",
                [(name, kind, observed_at) for name in deduped],
            )

    def set_pinned(self, names: list[str]) -> None:
        self._set_flags("pinned", names)

    def set_ignored(self, names: list[str]) -> None:
        self._set_flags("ignored", names)

    def add_flag(self, name: str, kind: str) -> bool:
        name = name.strip()
        observed_at = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM container_flags WHERE name = ? AND kind = ?",
                (name, kind),
            ).fetchone()
            if existing is not None:
                return False
            connection.execute(
                "INSERT INTO container_flags (name, kind, added_at) VALUES (?, ?, ?)",
                (name, kind, observed_at),
            )
            return True

    def remove_flag(self, name: str, kind: str) -> bool:
        name = name.strip()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "DELETE FROM container_flags WHERE name = ? AND kind = ?",
                (name, kind),
            )
            return cursor.rowcount > 0
```

Note: `add_flag`/`remove_flag` return inside the `with closing(...) as connection, connection:` block — this is safe because `connection` as a context manager commits/rolls back on `__exit__`, which still runs correctly on an early `return` from within a `with` block (Python guarantees `__exit__` runs on any exit path, including `return`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db.py::TestContainerFlags -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Run full test suite to check no regressions**

Run: `python -m pytest -q`
Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add src/dockwatch/db.py tests/test_db.py
git commit -m "feat: add container_flags table for pinned/ignored to db.py

New ManifestStore methods (get_pinned/get_ignored/set_pinned/set_ignored/
add_flag/remove_flag) backed by a container_flags table, using the same
WAL + BEGIN IMMEDIATE pattern as manifest_state/trivy_scan_cache. Not
wired into config.py/routes/CLI yet -- this task only adds the storage
layer and its tests."
```

---

### Task 2: Migrate existing config.toml pinned/ignored into SQLite on load

**Files:**
- Modify: `src/dockwatch/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `ManifestStore.get_pinned()`, `ManifestStore.get_ignored()`, `ManifestStore.set_pinned()`, `ManifestStore.set_ignored()` from Task 1
- Produces: `migrate_pinned_ignored_to_db(config_path: Path, store: ManifestStore) -> None` — one-time migration helper. Called from `main.py`/`api/app.py` startup in Task 4, not from `load_config` itself (avoids a DB dependency inside `config.py`'s otherwise-pure TOML loader).

This task does NOT yet remove `pinned`/`ignored` from `DockwatchConfig` — that happens in Task 3 after the migration path exists and is tested. Order matters: migrate first, cut over second, so there's always a working intermediate state.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py` (check the top of that file for existing import style first):

```python
class TestPinnedIgnoredMigration:
    def test_migrates_existing_toml_values_into_store(self, tmp_path):
        from dockwatch.config import migrate_pinned_ignored_to_db
        from dockwatch.db import ManifestStore

        config_path = tmp_path / "config.toml"
        config_path.write_text(
            'pinned = ["nginx", "redis"]\nignored = ["postgres"]\n',
            encoding="utf-8",
        )
        store = ManifestStore(path=tmp_path / "test.db")

        migrate_pinned_ignored_to_db(config_path, store)

        assert sorted(store.get_pinned()) == ["nginx", "redis"]
        assert store.get_ignored() == ["postgres"]

    def test_migration_is_idempotent(self, tmp_path):
        from dockwatch.config import migrate_pinned_ignored_to_db
        from dockwatch.db import ManifestStore

        config_path = tmp_path / "config.toml"
        config_path.write_text('pinned = ["nginx"]\n', encoding="utf-8")
        store = ManifestStore(path=tmp_path / "test.db")

        migrate_pinned_ignored_to_db(config_path, store)
        migrate_pinned_ignored_to_db(config_path, store)  # run twice

        assert store.get_pinned() == ["nginx"]

    def test_migration_skips_when_store_already_has_data(self, tmp_path):
        from dockwatch.config import migrate_pinned_ignored_to_db
        from dockwatch.db import ManifestStore

        config_path = tmp_path / "config.toml"
        config_path.write_text('pinned = ["nginx"]\n', encoding="utf-8")
        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("already-here", "pinned")

        migrate_pinned_ignored_to_db(config_path, store)

        # Migration must not clobber flags a user already set post-migration
        # on a previous run -- it only imports when the store is empty.
        assert store.get_pinned() == ["already-here"]

    def test_migration_handles_missing_config_file(self, tmp_path):
        from dockwatch.config import migrate_pinned_ignored_to_db
        from dockwatch.db import ManifestStore

        config_path = tmp_path / "does-not-exist.toml"
        store = ManifestStore(path=tmp_path / "test.db")

        migrate_pinned_ignored_to_db(config_path, store)  # must not raise

        assert store.get_pinned() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py::TestPinnedIgnoredMigration -v`
Expected: FAIL with `ImportError: cannot import name 'migrate_pinned_ignored_to_db'`

- [ ] **Step 3: Implement the migration function**

In `src/dockwatch/config.py`, add near the top (after existing imports — check current imports first, this needs `tomllib` which is likely already imported for `load_config`):

```python
def migrate_pinned_ignored_to_db(path: Path, store: "ManifestStore") -> None:
    """One-time import of pinned/ignored from config.toml into SQLite.

    Only runs when the store has no flags yet, so it never clobbers
    changes made after an earlier migration (or a fresh SQLite-only
    install with no legacy TOML values to import).
    """
    if store.get_pinned() or store.get_ignored():
        return
    if not path.exists():
        return
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError):
        return
    pinned = _parse_list(data.get("pinned"))
    ignored = _parse_list(data.get("ignored"))
    if pinned:
        store.set_pinned(pinned)
    if ignored:
        store.set_ignored(ignored)
```

Add the type-only import for `ManifestStore` near the top of `config.py` under `TYPE_CHECKING` (to avoid a runtime circular import, since `db.py` does not import `config.py` — check this is actually true with `grep -n "^from\|^import" src/dockwatch/db.py` before adding; if `db.py` has zero imports from `config.py`, a plain top-level import is fine instead of `TYPE_CHECKING`):

```python
from .db import ManifestStore
```

(Use a plain import, not `TYPE_CHECKING`, since the function signature needs it at runtime for the type check to be meaningful — but only add this import if `grep -n "from .config\|from dockwatch.config" src/dockwatch/db.py` returns nothing, confirming no circular import risk.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py::TestPinnedIgnoredMigration -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest -q`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add src/dockwatch/config.py tests/test_config.py
git commit -m "feat: add one-time migration of pinned/ignored from TOML to SQLite

migrate_pinned_ignored_to_db imports existing config.toml pinned/ignored
values into the new container_flags table on first run, guarded so it
never overwrites flags already present in the store. Not called from
anywhere yet -- wired into startup in the next task."
```

---

### Task 3: Remove pinned/ignored from DockwatchConfig, repoint registry.py's hot path

**Files:**
- Modify: `src/dockwatch/config.py`
- Modify: `src/dockwatch/registry.py`
- Test: `tests/test_config.py`, `tests/test_registry.py`

**Interfaces:**
- Consumes: `ManifestStore.get_pinned()`, `ManifestStore.get_ignored()` from Task 1
- Produces: `DockwatchConfig` with `pinned`/`ignored` fields removed. `check_all()` now takes the pinned/ignored sets from the passed-in `store` parameter instead of `config.pinned`/`config.ignored`.

This is the biggest behavior-changing task — read it fully before starting.

- [ ] **Step 1: Find every remaining reference to config.pinned/config.ignored**

Run: `grep -rn "\.pinned\b\|\.ignored\b" src/dockwatch/`

Expected output at this point (before this task's edits) should show references in:
- `src/dockwatch/config.py` (the field definitions + any `_to_toml`/`save_config` serialization of them)
- `src/dockwatch/registry.py` (lines ~456-457 `_resolve_effective_tag_filters`, ~794-795 `check_all`)
- `src/dockwatch/api/serializers.py` (get/put settings — handled in Task 4, skip for now)
- `src/dockwatch/api/routes/containers.py` (pin/unpin routes — handled in Task 5, skip for now)
- `src/dockwatch/main.py` (CLI commands — handled in Task 6, skip for now)

This task only touches `config.py` and `registry.py`.

- [ ] **Step 2: Write the failing test for registry.py's new store-based flag resolution**

Add to `tests/test_registry.py` (check existing test file for `check_all` test patterns and fixtures first — this repo likely already has container/config fixtures to reuse):

```python
class TestCheckAllUsesStoreForFlags:
    @pytest.mark.asyncio
    async def test_pinned_container_from_store_is_precomputed(self, tmp_path):
        from dockwatch.config import DockwatchConfig
        from dockwatch.db import ManifestStore
        from dockwatch.models import ContainerInfo, RegistryType
        from dockwatch.registry import check_all

        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("nginx", "pinned")

        container = ContainerInfo(
            name="nginx",
            container_id="abc123",
            image_ref="nginx:1.0.0",
            registry=RegistryType.DOCKERHUB,
            namespace="library",
            image_name="nginx",
            current_tag="1.0.0",
        )
        config = DockwatchConfig()

        results = await check_all([container], config, store=store, max_concurrency=1)

        assert len(results) == 1
        assert results[0].status == "PINNED"

    @pytest.mark.asyncio
    async def test_ignored_container_from_store_is_excluded(self, tmp_path):
        from dockwatch.config import DockwatchConfig
        from dockwatch.db import ManifestStore
        from dockwatch.models import ContainerInfo, RegistryType
        from dockwatch.registry import check_all

        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("redis", "ignored")

        container = ContainerInfo(
            name="redis",
            container_id="def456",
            image_ref="redis:7.0.0",
            registry=RegistryType.DOCKERHUB,
            namespace="library",
            image_name="redis",
            current_tag="7.0.0",
        )
        config = DockwatchConfig()

        results = await check_all([container], config, store=store, max_concurrency=1)

        assert len(results) == 0
```

Check whether `tests/test_registry.py` already has `pytest-asyncio` configured (look for `@pytest.mark.asyncio` elsewhere in that file, or an `asyncio_mode` setting in `pyproject.toml`/`pytest.ini`) — if `check_all` tests already exist and pass without explicit markers, match that existing style instead of adding `@pytest.mark.asyncio`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_registry.py::TestCheckAllUsesStoreForFlags -v`
Expected: FAIL — either `store` parameter is ignored for flags (falls back to `config.pinned` which is now empty since nothing sets it in this test) or an `AttributeError`/`TypeError` if `DockwatchConfig` no longer has `.pinned` after Step 4 runs first. Run this test BEFORE Step 4's edits to confirm the pre-change baseline behavior (test should fail because `config.pinned` is empty, not because the attribute is missing).

- [ ] **Step 4: Remove pinned/ignored from DockwatchConfig, update registry.py to read from store**

In `src/dockwatch/config.py`, remove these two lines from the `DockwatchConfig` dataclass:

```python
    pinned: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
```

Find and remove any serialization of `pinned`/`ignored` in `_to_toml`/`save_config` (search `grep -n "pinned\|ignored" src/dockwatch/config.py` after removing the field to catch any remaining references — there will likely be a line like `pinned = {_toml_string_list(config.pinned)}` in the TOML-building function that must also be deleted).

Find and remove any parsing of `pinned`/`ignored` in `_fallback_config`/`load_config`'s TOML-reading path (same grep will surface these).

In `src/dockwatch/registry.py`, update `check_all` (around line 786-795) to require a non-None `store` for flag resolution and read from it instead of `config`:

```python
async def check_all(
    containers: list[ContainerInfo],
    config: DockwatchConfig | None = None,
    *,
    store: ManifestStore | None = None,
    max_concurrency: int | None = None,
) -> list[UpdateResult]:
    resolved_config = config or load_config()
    ignored = set(store.get_ignored()) if store else set()
    pinned = set(store.get_pinned()) if store else set()
```

Update `_resolve_effective_tag_filters` (around line 451-469) to drop the now-nonexistent `pinned=config.pinned, ignored=config.ignored` kwargs when constructing the temporary `effective_config` — since `DockwatchConfig` no longer has these fields, this line must be deleted entirely from the constructor call, not just left with stale kwargs (leaving them would be a `TypeError: unexpected keyword argument`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_registry.py::TestCheckAllUsesStoreForFlags -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run full test suite — expect failures in other files, that's expected**

Run: `python -m pytest -q`
Expected: FAILURES in `tests/test_config.py` (tests referencing `config.pinned`), `tests/test_main.py` or similar (CLI tests), `tests/test_audit_harness.py` if it references `.pinned`/`.ignored` directly. These are fixed in Tasks 4-6. Note the list of failing test files/names now so you can confirm they're all resolved by Task 6's end.

Run: `python -m pytest -q 2>&1 | grep FAILED` and record the output.

- [ ] **Step 7: Commit**

```bash
git add src/dockwatch/config.py src/dockwatch/registry.py tests/test_registry.py
git commit -m "refactor: remove pinned/ignored from DockwatchConfig, read from SQLite store

check_all() now resolves pinned/ignored sets from ManifestStore
(get_pinned/get_ignored) instead of config.pinned/config.ignored, which
no longer exist on DockwatchConfig. This is expected to break
config.py/main.py/api tests referencing the removed fields until Tasks
4-6 repoint those call sites -- do not merge past this commit alone."
```

---

### Task 4: Repoint settings API (serializers.py) at the store

**Files:**
- Modify: `src/dockwatch/api/serializers.py`
- Modify: `src/dockwatch/api/routes/settings.py`
- Modify: `src/dockwatch/api/deps.py`
- Modify: `src/dockwatch/api/app.py` (to call the Task 2 migration on startup)
- Test: `tests/test_serializers.py` or `tests/test_settings.py` (check which file exists — `grep -rn "serialize_settings\|deserialize_settings" tests/` to find it)

**Interfaces:**
- Consumes: `ManifestStore.get_pinned()`, `.get_ignored()`, `.set_pinned()`, `.set_ignored()` from Task 1; `migrate_pinned_ignored_to_db()` from Task 2; `get_store()` from `api/deps.py` (already exists)
- Produces: `serialize_settings(config, store)` and `deserialize_settings(data, existing, store)` — both now take a `store` parameter. This changes their signatures; every call site must be updated in this task.

- [ ] **Step 1: Find all call sites of serialize_settings/deserialize_settings**

Run: `grep -rn "serialize_settings\|deserialize_settings" src/dockwatch/`

Expected: `api/routes/settings.py` (both `get_settings`/`put_settings`), possibly `api/routes/containers.py` if pin/unpin routes call these (check — if they do, Task 5 must also update those calls).

- [ ] **Step 2: Write the failing test**

Find the existing test file covering `serialize_settings`/`deserialize_settings` (likely `tests/test_audit_harness.py`'s `TestSettingsAPI` class based on earlier exploration, or a dedicated `tests/test_serializers.py`). Add:

```python
class TestSettingsUsesStoreForFlags:
    def test_serialize_settings_reads_pinned_from_store(self, tmp_path):
        from dockwatch.api.serializers import serialize_settings
        from dockwatch.config import DockwatchConfig
        from dockwatch.db import ManifestStore

        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("nginx", "pinned")
        store.add_flag("redis", "ignored")

        data = serialize_settings(DockwatchConfig(), store)

        assert data["pinned"] == ["nginx"]
        assert data["ignored"] == ["redis"]

    def test_deserialize_settings_writes_pinned_to_store(self, tmp_path):
        from dockwatch.api.serializers import deserialize_settings
        from dockwatch.config import DockwatchConfig
        from dockwatch.db import ManifestStore

        store = ManifestStore(path=tmp_path / "test.db")
        config = DockwatchConfig()

        deserialize_settings({"pinned": ["nginx", "redis"]}, config, store)

        assert sorted(store.get_pinned()) == ["nginx", "redis"]

    def test_deserialize_settings_empty_pinned_clears_store(self, tmp_path):
        from dockwatch.api.serializers import deserialize_settings
        from dockwatch.config import DockwatchConfig
        from dockwatch.db import ManifestStore

        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("nginx", "pinned")
        config = DockwatchConfig()

        deserialize_settings({"pinned": []}, config, store)

        assert store.get_pinned() == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_audit_harness.py::TestSettingsUsesStoreForFlags -v` (adjust path to wherever you added the test class in Step 2)
Expected: FAIL with `TypeError: serialize_settings() takes 1 positional argument but 2 were given`

- [ ] **Step 4: Update serializers.py**

In `src/dockwatch/api/serializers.py`, update the function signatures:

```python
def serialize_settings(config: DockwatchConfig, store: "ManifestStore") -> dict[str, Any]:
    return {
        "pinned": store.get_pinned(),
        "ignored": store.get_ignored(),
        "notify_only": config.notify_only,
        "include_tags": config.include_tags,
        "exclude_tags": config.exclude_tags,
        "notify_on": config.notify_on,
        "first_check_notify": config.first_check_notify,
        "webhook_url": config.webhook_url,
        "discord_webhook": config.discord_webhook,
        "ntfy_url": config.ntfy_url,
        "schedule_interval_seconds": config.schedule_interval_seconds,
        "schedule_jitter_seconds": config.schedule_jitter_seconds,
        "run_on_startup": config.run_on_startup,
        "max_concurrent_checks": config.max_concurrent_checks,
        "portainer": {
            "enabled": config.portainer.enabled,
            "url": config.portainer.url,
            "api_key": _mask_api_key(config.portainer.api_key),
            "environments": config.portainer.environments,
        },
        "trivy": {
            "enabled": config.trivy.enabled,
            "binary_path": config.trivy.binary_path,
            "severity": config.trivy.severity,
            "scanners": config.trivy.scanners,
            "timeout_seconds": config.trivy.timeout_seconds,
            "skip_db_update": config.trivy.skip_db_update,
            "cache_ttl_minutes": config.trivy.cache_ttl_minutes,
        },
        "compose_projects": {
            key: {
                "workdir": value.workdir,
                "files": value.files,
                "project_name": value.project_name,
            }
            for key, value in config.compose_projects.items()
        },
    }


def deserialize_settings(data: dict[str, Any], existing: DockwatchConfig, store: "ManifestStore") -> DockwatchConfig:
    if "pinned" in data:
        store.set_pinned(_ensure_list(data.get("pinned"), store.get_pinned()))
    if "ignored" in data:
        store.set_ignored(_ensure_list(data.get("ignored"), store.get_ignored()))
    existing.notify_only = _ensure_list(data.get("notify_only", existing.notify_only), existing.notify_only)
    existing.include_tags = _ensure_list(data.get("include_tags", existing.include_tags), existing.include_tags)
    existing.exclude_tags = _ensure_list(data.get("exclude_tags", existing.exclude_tags), existing.exclude_tags)
    existing.notify_on = _ensure_list(data.get("notify_on", existing.notify_on), existing.notify_on)
```

(The rest of `deserialize_settings` — everything after `notify_on` — is unchanged; only the `pinned`/`ignored` lines at the top are replaced. Do not touch the rest of the function body.)

Add the `ManifestStore` import at the top of `serializers.py`:

```python
from ..db import ManifestStore
```

- [ ] **Step 5: Update api/routes/settings.py call sites**

Read `src/dockwatch/api/routes/settings.py` first (`get_settings`/`put_settings` handlers) to see the exact current call shape, then update both to pass `store`:

```python
@router.get("/settings")
def get_settings() -> Any:
    config = get_config()
    store = get_store()
    return serialize_settings(config, store)


@router.put("/settings")
def put_settings(body: dict[str, Any]) -> Any:
    with _settings_write_lock:
        existing = load_config()
        store = get_store()
        try:
            updated = deserialize_settings(body, existing, store)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"invalid settings value: {exc}") from exc
        save_config(updated)
    return serialize_settings(updated, store)
```

Add `get_store` to the imports from `..deps` in `settings.py` if not already imported (check current import line first: `grep -n "from ..deps import" src/dockwatch/api/routes/settings.py`).

- [ ] **Step 6: Wire migration into app startup**

In `src/dockwatch/api/app.py`, find where the app is created/started (likely `create_app()` or a startup event handler). Add a call to run the migration once at startup, using the module-level store from `deps.py`:

```python
from .deps import get_store
from ..config import migrate_pinned_ignored_to_db, CONFIG_PATH

# inside create_app() or an @app.on_event("startup") handler:
migrate_pinned_ignored_to_db(CONFIG_PATH, get_store())
```

Read the actual current structure of `app.py` before editing — this repo may use FastAPI's `lifespan` context manager instead of the deprecated `@app.on_event("startup")`; match whichever pattern is already there (`grep -n "on_event\|lifespan" src/dockwatch/api/app.py` to check).

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_audit_harness.py::TestSettingsUsesStoreForFlags -v` (or wherever you placed the tests)
Expected: PASS (3 tests)

- [ ] **Step 8: Run full test suite**

Run: `python -m pytest -q`
Expected: Remaining failures should now only be in `main.py`/CLI-related tests and `api/routes/containers.py` pin/unpin tests — fixed in Tasks 5-6. Confirm the failure count has shrunk from Task 3's Step 6 baseline.

- [ ] **Step 9: Commit**

```bash
git add src/dockwatch/api/serializers.py src/dockwatch/api/routes/settings.py src/dockwatch/api/app.py tests/
git commit -m "refactor: settings API reads/writes pinned/ignored via SQLite store

serialize_settings/deserialize_settings now take a ManifestStore parameter
and use get_pinned/get_ignored/set_pinned/set_ignored instead of
config.pinned/config.ignored. Migration from any existing config.toml
values now runs once at app startup."
```

---

### Task 5: Repoint pin/unpin routes at the store, remove the now-redundant lock

**Files:**
- Modify: `src/dockwatch/api/routes/containers.py`
- Test: `tests/test_audit_harness.py` (update `TestPinUnpinRace` — it currently tests the TOML-based lock from an earlier fix this session; needs updating to test the store-based version instead)

**Interfaces:**
- Consumes: `ManifestStore.add_flag(name, kind)`, `.remove_flag(name, kind)` from Task 1, `get_store()` from `api/deps.py` (already exists)
- Produces: `pin_container`/`unpin_container` routes backed entirely by SQLite; `_pin_write_lock` (the `threading.Lock` added earlier this session) is removed since SQLite's own `BEGIN IMMEDIATE` transaction now provides the serialization — the DB does the locking, an application-level lock on top is redundant.

- [ ] **Step 1: Write the failing test**

The existing `TestPinUnpinRace` test in `tests/test_audit_harness.py` (added earlier this session) tests concurrent writes through `load_config`/`save_config` with `containers_routes._pin_write_lock`. Replace it — read the current test first (`grep -n "class TestPinUnpinRace" -A 40 tests/test_audit_harness.py`) then rewrite it to exercise the store directly through the route functions:

```python
class TestPinUnpinRace:
    """Fix verified: pin_container/unpin_container write through
    ManifestStore.add_flag/remove_flag, which serializes writes via
    SQLite's own BEGIN IMMEDIATE transaction -- this closes the race
    both within one process (many threads) and across processes (CLI
    vs web server), unlike the earlier threading.Lock fix which only
    protected concurrent requests within a single server process."""

    def test_concurrent_pins_do_not_lose_updates(self, tmp_path):
        import threading
        from dockwatch.db import ManifestStore

        store = ManifestStore(path=tmp_path / "test.db")
        names = [f"container-{i}" for i in range(8)]
        errors: list[BaseException] = []

        def pin(name: str) -> None:
            try:
                store.add_flag(name, "pinned")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=pin, args=(n,)) for n in names]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert sorted(store.get_pinned()) == sorted(names)

    def test_concurrent_pin_and_unpin_of_different_names_both_succeed(self, tmp_path):
        import threading
        from dockwatch.db import ManifestStore

        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("existing", "pinned")

        results: dict[str, bool] = {}

        def pin_new():
            results["pin"] = store.add_flag("new-container", "pinned")

        def unpin_existing():
            results["unpin"] = store.remove_flag("existing", "pinned")

        t1 = threading.Thread(target=pin_new)
        t2 = threading.Thread(target=unpin_existing)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert results["pin"] is True
        assert results["unpin"] is True
        assert store.get_pinned() == ["new-container"]
```

- [ ] **Step 2: Run tests to verify they fail (or pass — Task 1 already implemented add_flag/remove_flag)**

Run: `python -m pytest tests/test_audit_harness.py::TestPinUnpinRace -v`

Expected: These tests exercise `ManifestStore` directly (already implemented in Task 1), so they should PASS immediately. This step confirms Task 1's implementation actually holds under concurrent load — if it fails here, Task 1's `add_flag`/`remove_flag` has a bug and must be fixed before continuing.

- [ ] **Step 3: Update the pin/unpin routes**

Read the current `src/dockwatch/api/routes/containers.py` pin/unpin section (lines ~119-141 as of this session) before editing. Replace with:

```python
@router.post("/containers/{name}/pin")
def pin_container(name: str) -> Any:
    store = get_store()
    store.add_flag(name, "pinned")
    return {"ok": True, "pinned": store.get_pinned()}


@router.delete("/containers/{name}/pin")
def unpin_container(name: str) -> Any:
    store = get_store()
    removed = store.remove_flag(name, "pinned")
    if not removed:
        raise HTTPException(status_code=404, detail=f"'{name}' is not pinned.")
    return {"ok": True, "pinned": store.get_pinned()}
```

Remove the now-unused `_pin_write_lock` module-level variable and its `threading` import (check nothing else in the file uses `threading` first: `grep -n "threading" src/dockwatch/api/routes/containers.py`).

Remove the local `from ...config import load_config, save_config` imports inside the old route bodies (no longer needed — `get_store` is already imported at the top of the file from `..deps`, confirm with `grep -n "from ..deps import" src/dockwatch/api/routes/containers.py`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_audit_harness.py::TestPinUnpinRace -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest -q`
Expected: Only `main.py`/CLI tests should still be failing at this point (Task 6 fixes those).

- [ ] **Step 6: Commit**

```bash
git add src/dockwatch/api/routes/containers.py tests/test_audit_harness.py
git commit -m "refactor: pin/unpin routes write through SQLite store, drop app-level lock

pin_container/unpin_container now call store.add_flag/remove_flag
directly. The threading.Lock added earlier this session
(_pin_write_lock) is removed -- SQLite's BEGIN IMMEDIATE transaction
inside add_flag/remove_flag already serializes concurrent writes, and
does so across processes too (CLI vs web server), which the
threading.Lock never could."
```

---

### Task 6: Repoint CLI commands (main.py) at the store

**Files:**
- Modify: `src/dockwatch/main.py`
- Test: `tests/test_main.py` (check exact filename: `grep -rln "pin_container\|def test.*pin" tests/`)

**Interfaces:**
- Consumes: `ManifestStore.add_flag`, `.remove_flag`, `.get_pinned`, `.get_ignored` from Task 1
- Produces: `dockwatch pin`, `dockwatch unpin`, `dockwatch ignore`, `dockwatch unignore`, `dockwatch config list` CLI commands backed by SQLite instead of TOML.

- [ ] **Step 1: Read the current CLI commands and find how ManifestStore is already constructed elsewhere in main.py**

Run: `grep -n "ManifestStore(" src/dockwatch/main.py`

The CLI's `check`/`scan` commands likely already construct a `ManifestStore()` instance for the manifest-state tracking (see `check_all(..., store=store, ...)` calls). Find that exact construction pattern to reuse — likely `store = ManifestStore()` with no path argument (using the default `STATE_DB_PATH`).

- [ ] **Step 2: Write the failing test**

Find the existing CLI test file (`tests/test_main.py` or similar — check `grep -rln "from typer.testing import CliRunner" tests/`) and its existing pin/unpin test pattern, then add:

```python
class TestCLIPinUsesStore(unittest.TestCase):
    def test_pin_command_writes_to_store(self):
        from typer.testing import CliRunner
        from unittest.mock import patch
        from dockwatch.main import app
        from dockwatch.db import ManifestStore

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            with patch("dockwatch.main.ManifestStore", lambda: ManifestStore(path=db_path)):
                result = runner.invoke(app, ["pin", "nginx"])
                assert result.exit_code == 0
                store = ManifestStore(path=db_path)
                assert store.get_pinned() == ["nginx"]
```

Check the exact CLI test invocation pattern already used in the existing test file (`CliRunner`/`app` import path, whether `ManifestStore` is patched via `dockwatch.main.ManifestStore` or a different reference) and match it — the mock target above is a guess based on typical Typer test patterns and must be verified against this codebase's actual `main.py` structure before running.

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_main.py::TestCLIPinUsesStore -v`
Expected: FAIL — command still uses `load_config`/`save_config` for pinning, so the DB file is never written to via `store.get_pinned()`, or the mock target doesn't match yet.

- [ ] **Step 4: Update the CLI commands**

Read `src/dockwatch/main.py` lines ~342-410 (the pin/unpin/ignore/unignore/config-list commands documented earlier in this session) before editing, then replace:

```python
@app.command("pin")
def pin_container(container: str) -> None:
    """Pin a container so update checks mark it as PINNED."""
    store = ManifestStore()
    store.add_flag(container, "pinned")
    typer.echo(f"Pinned: {container}")


@app.command("ignore")
def ignore_container(container: str) -> None:
    """Ignore a container in update checks."""
    store = ManifestStore()
    store.add_flag(container, "ignored")
    typer.echo(f"Ignored: {container}")


@app.command("unpin")
def unpin_container(container: str) -> None:
    """Remove a container from the pinned list."""
    store = ManifestStore()
    removed = store.remove_flag(container, "pinned")
    if not removed:
        typer.echo(f"'{container}' is not pinned.", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Unpinned: {container}")


@app.command("unignore")
def unignore_container(container: str) -> None:
    """Remove a container from the ignored list."""
    store = ManifestStore()
    removed = store.remove_flag(container, "ignored")
    if not removed:
        typer.echo(f"'{container}' is not ignored.", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Unignored: {container}")


@config_app.command("list")
def list_config() -> None:
    """Show pinned and ignored containers from config."""
    config: DockwatchConfig = load_config()
    store = ManifestStore()
    typer.echo("Pinned:")
    pinned = store.get_pinned()
    if pinned:
        for item in pinned:
            typer.echo(f"  - {item}")
    else:
        typer.echo("  (none)")

    typer.echo("Ignored:")
    ignored = store.get_ignored()
    if ignored:
        for item in ignored:
            typer.echo(f"  - {item}")
    else:
        typer.echo("  (none)")

    typer.echo("Notifications:")
    typer.echo(f"  include_tags: {', '.join(config.include_tags) if config.include_tags else '(none)'}")
```

(The `typer.echo("Notifications:")` line onward, after `list_config`, is unchanged — only the Pinned/Ignored sections switch from `config.pinned`/`config.ignored` to `store.get_pinned()`/`store.get_ignored()`.)

Remove the now-unused `_update_named_list` helper function if nothing else in `main.py` calls it (check: `grep -n "_update_named_list" src/dockwatch/main.py`).

Confirm `ManifestStore` is already imported at the top of `main.py` (`grep -n "from .db import\|from dockwatch.db import" src/dockwatch/main.py`) — it almost certainly is, given `check`/`scan` commands already use it.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_main.py::TestCLIPinUsesStore -v`
Expected: PASS

- [ ] **Step 6: Run full test suite — this should now be all green**

Run: `python -m pytest -q`
Expected: all tests pass, zero failures

- [ ] **Step 7: Verify no dangling references remain**

Run: `grep -rn "\.pinned\b\|\.ignored\b" src/dockwatch/ | grep -v "get_pinned\|get_ignored\|set_pinned\|set_ignored\|pinned_override\|ignored_override"`

Expected: no output (or only false-positive matches on unrelated identifiers like `is_effectively_pinned` variable names, which are fine — those are local variables now sourced from the store, not `DockwatchConfig` fields).

- [ ] **Step 8: Commit**

```bash
git add src/dockwatch/main.py tests/test_main.py
git commit -m "refactor: CLI pin/ignore/unpin/unignore commands use SQLite store

Completes the pinned/ignored migration off config.toml. All four CLI
mutation commands and 'dockwatch config list' now read/write via
ManifestStore instead of load_config/save_config. This closes the
cross-process race between the CLI and the running web server that a
threading.Lock inside the server process could never protect against --
SQLite's own transaction serialization now covers both."
```

---

### Task 7: Rebuild the Docker image and manually verify against the live demo containers

**Files:**
- None (verification only)

**Interfaces:**
- Consumes: everything from Tasks 1-6

- [ ] **Step 1: Run the full test suite one final time**

Run: `python -m pytest -q`
Expected: all tests pass

- [ ] **Step 2: Rebuild the container**

Run: `bash scripts/recreate-container.sh`
Expected: build succeeds, container starts

- [ ] **Step 3: Verify pinned/ignored survive a container restart via the DB volume**

```bash
curl -X POST http://localhost:10801/api/containers/jackett/pin
docker restart dockwatch
sleep 3
curl http://localhost:10801/api/settings | python3 -c "import json,sys; print(json.load(sys.stdin)['pinned'])"
```
Expected: `["jackett"]` — proves the pin survived a full container restart via the `dockwatch_config` volume (where `manifests.db` lives), not just an in-process cache.

- [ ] **Step 4: Verify pin via CLI is visible via API (cross-process proof)**

```bash
docker exec dockwatch dockwatch unpin jackett
curl http://localhost:10801/api/settings | python3 -c "import json,sys; print(json.load(sys.stdin)['pinned'])"
```
Expected: `[]` — proves a CLI-issued unpin (a different process than the running `serve` web server) is immediately visible through the API, demonstrating the cross-process race is actually closed.

- [ ] **Step 5: Clean up demo pin state**

No cleanup needed if Step 4 already unpinned; otherwise:
```bash
curl -X DELETE http://localhost:10801/api/containers/jackett/pin
```

This task has no commit — it's manual verification of Tasks 1-6's combined result against the real running container.

---

## Self-Review Notes

**Spec coverage:** Every read/write site identified during scoping (`config.py` dataclass, `registry.py` hot path, `api/serializers.py` get/put, `api/routes/containers.py` pin/unpin, `main.py` 4 CLI commands + config list) has a corresponding task. Migration path (Task 2) ensures no data loss for existing installs. Bulk-replace requirement (settings form sends full list) is covered by `set_pinned`/`set_ignored` in Task 1 and used in Task 4.

**Placeholder scan:** No TBD/TODO markers. All code blocks are complete, not "similar to Task N" references.

**Type consistency:** `ManifestStore.add_flag(name: str, kind: str) -> bool` / `remove_flag(name: str, kind: str) -> bool` signatures are identical across Task 1's definition and Task 5/6's call sites. `serialize_settings(config, store)` / `deserialize_settings(data, existing, store)` signatures match between Task 4's definition and its call sites in the same task.
