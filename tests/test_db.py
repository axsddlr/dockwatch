from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dockwatch.db import ManifestStore
from dockwatch.models import ContainerInfo, RegistryType, UpdateResult
from dockwatch.registry import record_digest_drift_events


def make_container(image_ref: str = "nginx:1.0.0", current_tag: str = "1.0.0") -> ContainerInfo:
    return ContainerInfo(
        name="web",
        container_id="1",
        image_ref=image_ref,
        registry=RegistryType.DOCKERHUB,
        namespace="library",
        image_name="nginx",
        current_tag=current_tag,
    )


class ManifestStoreTests(unittest.TestCase):
    def test_record_observation_classifies_new_then_update(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            container = make_container()

            first_event = store.record_observation(
                container,
                latest_tag="1.1.0",
                remote_digest="sha256:first",
            )
            second_event = store.record_observation(
                container,
                latest_tag="1.1.0",
                remote_digest="sha256:first",
            )
            third_event = store.record_observation(
                container,
                latest_tag="1.2.0",
                remote_digest="sha256:second",
            )

        self.assertEqual(first_event, "new")
        self.assertIsNone(second_event)
        self.assertEqual(third_event, "update")

    def test_record_observation_persists_latest_tag_without_digest_change(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            container = make_container()
            store.record_observation(container, latest_tag="1.1.0", remote_digest="sha256:same")

            event = store.record_observation(container, latest_tag="1.1.1", remote_digest="sha256:same")

        self.assertEqual(event, "update")

    def test_latest_seen_at_tracks_first_observation_of_each_tag(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            container = make_container()

            first_seen = "2025-01-01T00:00:00+00:00"
            store.record_observation(container, latest_tag="1.1.0", remote_digest="sha256:first", checked_at=first_seen)
            self.assertEqual(store.get_latest_seen_at(container), first_seen)

            # Re-observing the same tag preserves the clock start.
            store.record_observation(
                container,
                latest_tag="1.1.0",
                remote_digest="sha256:first",
                checked_at="2025-01-02T00:00:00+00:00",
            )
            self.assertEqual(store.get_latest_seen_at(container), first_seen)

            # A new tag restarts the clock.
            second_seen = "2025-01-03T00:00:00+00:00"
            store.record_observation(container, latest_tag="1.2.0", remote_digest="sha256:second", checked_at=second_seen)
            self.assertEqual(store.get_latest_seen_at(container), second_seen)

    def test_latest_seen_at_migrates_legacy_manifest_state(self) -> None:
        import sqlite3

        with TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "legacy.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE manifest_state (
                    image_key TEXT PRIMARY KEY,
                    image_ref TEXT NOT NULL,
                    current_tag TEXT NOT NULL,
                    last_seen_digest TEXT,
                    last_seen_latest_tag TEXT,
                    last_checked_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT INTO manifest_state (image_key, image_ref, current_tag, last_checked_at) VALUES (?, ?, ?, ?)",
                ("nginx:1.0.0", "nginx:1.0.0", "1.0.0", "2025-01-01T00:00:00+00:00"),
            )
            conn.commit()
            conn.close()

            store = ManifestStore(db_path)
            self.assertIsNone(store.get_latest_seen_at(make_container()))

    def test_equivalent_image_refs_share_the_same_identity(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            first = make_container(image_ref="nginx:1.0.0")
            second = make_container(image_ref="docker.io/library/nginx:1.0.0")

            first_event = store.record_observation(first, latest_tag="1.1.0", remote_digest="sha256:first")
            second_event = store.record_observation(second, latest_tag="1.1.0", remote_digest="sha256:first")

        self.assertEqual(first_event, "new")
        self.assertIsNone(second_event)


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

    def test_auto_update_flag_independent_of_pinned_and_ignored(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("nginx", "auto_update")
        assert store.get_auto_update() == ["nginx"]
        assert store.get_pinned() == []
        assert store.get_ignored() == []

    def test_set_auto_update_bulk_replace(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("nginx", "auto_update")
        store.set_auto_update(["redis", "postgres"])
        assert sorted(store.get_auto_update()) == ["postgres", "redis"]

    def test_container_flags_check_constraint_migrates_from_pre_auto_update_schema(self, tmp_path):
        import sqlite3

        path = tmp_path / "test.db"
        conn = sqlite3.connect(path)
        conn.execute(
            """
            CREATE TABLE container_flags (
                name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('pinned', 'ignored')),
                added_at TEXT NOT NULL,
                PRIMARY KEY (name, kind)
            )
            """
        )
        conn.execute(
            "INSERT INTO container_flags (name, kind, added_at) VALUES ('nginx', 'pinned', '2026-01-01')"
        )
        conn.commit()
        conn.close()

        store = ManifestStore(path=path)
        assert store.get_pinned() == ["nginx"]
        added = store.add_flag("nginx", "auto_update")
        assert added is True
        assert store.get_auto_update() == ["nginx"]


class TestUpdateHistory:
    def test_record_and_list_update_event(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.record_update_event(
            container_name="web",
            action="update",
            source="local",
            status="success",
            old_tag="1.0.0",
            new_tag="1.1.0",
            user_id=1,
            username="admin",
        )
        records = store.list_update_history(container_name="web")
        assert len(records) == 1
        assert records[0].old_tag == "1.0.0"
        assert records[0].new_tag == "1.1.0"
        assert records[0].username == "admin"
        assert records[0].status == "success"

    def test_list_update_history_orders_newest_first(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.record_update_event(
            container_name="web", action="update", source="local",
            status="success", old_tag="1.0.0", new_tag="1.1.0",
        )
        store.record_update_event(
            container_name="web", action="update", source="local",
            status="success", old_tag="1.1.0", new_tag="1.2.0",
        )
        records = store.list_update_history(container_name="web")
        assert [r.new_tag for r in records] == ["1.2.0", "1.1.0"]

    def test_update_history_prunes_beyond_max_per_container(self, tmp_path):
        from dockwatch.db import UPDATE_HISTORY_MAX_PER_CONTAINER

        store = ManifestStore(path=tmp_path / "test.db")
        for i in range(UPDATE_HISTORY_MAX_PER_CONTAINER + 5):
            store.record_update_event(
                container_name="web", action="update", source="local",
                status="success", old_tag=str(i), new_tag=str(i + 1),
            )
        records = store.list_update_history(container_name="web", limit=100)
        assert len(records) == UPDATE_HISTORY_MAX_PER_CONTAINER

    def test_get_last_successful_update_ignores_failed(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.record_update_event(
            container_name="web", action="update", source="local",
            status="success", old_tag="1.0.0", new_tag="1.1.0",
        )
        store.record_update_event(
            container_name="web", action="update", source="local",
            status="failed", old_tag="1.1.0", new_tag="1.2.0", error="boom",
        )
        last = store.get_last_successful_update("web")
        assert last is not None
        assert last.new_tag == "1.1.0"

    def test_update_history_scoped_per_container(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.record_update_event(
            container_name="web", action="update", source="local",
            status="success", old_tag="1.0.0", new_tag="1.1.0",
        )
        store.record_update_event(
            container_name="db", action="update", source="local",
            status="success", old_tag="2.0.0", new_tag="2.1.0",
        )
        assert len(store.list_update_history(container_name="web")) == 1
        assert len(store.list_update_history(container_name="db")) == 1


class TestDigestDriftRecording:
    def test_record_digest_drift_events_writes_history_row(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        container = make_container(image_ref="qmcgaw/gluetun:latest", current_tag="latest")
        result = UpdateResult(
            container_info=container,
            is_outdated=True,
            digest_drift=True,
            deployed_digest="sha256:old",
            remote_digest="sha256:new",
        )

        record_digest_drift_events([result], store)

        history = store.list_update_history(container_name="web")
        assert len(history) == 1
        assert history[0].action == "digest_drift_detected"
        assert history[0].old_digest == "sha256:old"
        assert history[0].new_digest == "sha256:new"

    def test_record_digest_drift_events_skips_non_drift_results(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        container = make_container()
        result = UpdateResult(container_info=container, is_outdated=True, digest_drift=False)

        record_digest_drift_events([result], store)

        assert store.list_update_history(container_name="web") == []

    def test_record_digest_drift_events_noop_without_store(self) -> None:
        container = make_container()
        result = UpdateResult(container_info=container, is_outdated=True, digest_drift=True)
        record_digest_drift_events([result], None)


class TestOnboardingSeen:
    def test_new_user_starts_unseen(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        user_id = store.create_user("alice", "hash", "admin")
        assert store.get_user_by_id(user_id).onboarding_seen == 0

    def test_mark_onboarding_seen_flips_flag(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        user_id = store.create_user("alice", "hash", "admin")

        marked = store.mark_onboarding_seen(user_id)

        assert marked is True
        assert store.get_user_by_id(user_id).onboarding_seen == 1

    def test_mark_onboarding_seen_is_idempotent(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        user_id = store.create_user("alice", "hash", "admin")

        store.mark_onboarding_seen(user_id)
        marked_again = store.mark_onboarding_seen(user_id)

        assert marked_again is True
        assert store.get_user_by_id(user_id).onboarding_seen == 1

    def test_onboarding_seen_migrates_from_pre_tour_schema(self, tmp_path):
        import sqlite3

        path = tmp_path / "test.db"
        conn = sqlite3.connect(path)
        conn.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                session_version INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "INSERT INTO users (username, password_hash, role_name, created_at) "
            "VALUES ('alice', 'hash', 'admin', '2026-01-01')"
        )
        conn.commit()
        conn.close()

        store = ManifestStore(path=path)

        columns = {row[1] for row in sqlite3.connect(path).execute("PRAGMA table_info(users)").fetchall()}
        assert "onboarding_seen" in columns
        assert store.get_user_by_username("alice").onboarding_seen == 0


class TestUpdateHistoryActionMigration:
    def test_update_history_action_check_migrates_to_include_new_actions(self, tmp_path):
        import sqlite3

        path = tmp_path / "test.db"
        conn = sqlite3.connect(path)
        conn.execute(
            """
            CREATE TABLE update_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                container_name TEXT NOT NULL,
                action TEXT NOT NULL CHECK (action IN ('update', 'rollback', 'restart', 'delete_container', 'delete_image', 'digest_drift_detected')),
                source TEXT NOT NULL CHECK (source IN ('local', 'portainer', 'agent')),
                environment_id TEXT,
                old_tag TEXT,
                new_tag TEXT,
                old_digest TEXT,
                new_digest TEXT,
                status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
                error TEXT,
                user_id INTEGER,
                username TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO update_history (container_name, action, source, status, created_at) "
            "VALUES ('web', 'update', 'local', 'success', '2026-01-01')"
        )
        conn.commit()
        conn.close()

        store = ManifestStore(path=path)

        store.record_update_event(
            container_name="web", action="health_restart", source="local", status="success",
        )
        store.record_update_event(
            container_name="web", action="hook", source="local", status="success",
        )
        store.record_update_event(
            container_name="web", action="prune_images", source="local", status="success",
        )

        actions = {r.action for r in store.list_update_history(container_name="web")}
        assert {"health_restart", "hook", "prune_images"} <= actions


class TestContainerFlagsHealthRestartMigration:
    def test_container_flags_check_migrates_to_include_health_restart(self, tmp_path):
        import sqlite3

        path = tmp_path / "test.db"
        conn = sqlite3.connect(path)
        conn.execute(
            """
            CREATE TABLE container_flags (
                name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('pinned', 'ignored', 'auto_update')),
                added_at TEXT NOT NULL,
                PRIMARY KEY (name, kind)
            )
            """
        )
        conn.execute(
            "INSERT INTO container_flags (name, kind, added_at) VALUES ('nginx', 'pinned', '2026-01-01')"
        )
        conn.commit()
        conn.close()

        store = ManifestStore(path=path)
        assert store.get_pinned() == ["nginx"]
        assert store.add_flag("nginx", "health_restart") is True
        assert store.get_health_restart() == ["nginx"]


class TestHealthState:
    def test_health_state_upsert_and_round_trip(self, tmp_path):
        from dockwatch.db import HealthStateRecord

        store = ManifestStore(path=tmp_path / "test.db")
        store.upsert_health_state(
            HealthStateRecord(
                container_key="local||web",
                container_name="web",
                source="local",
                environment_id=None,
                state="unhealthy",
                health_status="unhealthy",
                consecutive_unhealthy=3,
                last_changed_at="2026-01-01T00:00:00+00:00",
                last_restart_at=None,
                restarts_in_window=1,
                window_started_at="2026-01-01T00:00:00+00:00",
                last_notified_key=None,
            )
        )

        record = store.get_health_state("local||web")
        assert record is not None
        assert record.container_key == "local||web"
        assert record.container_name == "web"
        assert record.source == "local"
        assert record.state == "unhealthy"
        assert record.consecutive_unhealthy == 3

        store.upsert_health_state(
            HealthStateRecord(
                container_key="local||web",
                container_name="web",
                source="local",
                environment_id=None,
                state="healthy",
                health_status="healthy",
                consecutive_unhealthy=0,
                last_changed_at="2026-01-02T00:00:00+00:00",
                last_restart_at="2026-01-02T00:00:00+00:00",
                restarts_in_window=1,
                window_started_at="2026-01-01T00:00:00+00:00",
                last_notified_key="healthy:unhealthy",
            )
        )

        record = store.get_health_state("local||web")
        assert record is not None
        assert record.state == "healthy"
        assert record.health_status == "healthy"
        assert record.consecutive_unhealthy == 0
        assert record.last_restart_at == "2026-01-02T00:00:00+00:00"
        assert record.restarts_in_window == 1
        assert record.last_notified_key == "healthy:unhealthy"

        states = store.list_health_states()
        assert len(states) == 1
        assert states[0].container_key == "local||web"
        assert states[0].state == "healthy"

    def test_clear_health_state(self, tmp_path):
        from dockwatch.db import HealthStateRecord

        store = ManifestStore(path=tmp_path / "test.db")
        store.upsert_health_state(
            HealthStateRecord(container_key="local||web", container_name="web", source="local")
        )
        assert store.get_health_state("local||web") is not None
        assert store.clear_health_state("local||web") is True
        assert store.get_health_state("local||web") is None
        assert store.clear_health_state("local||web") is False
        assert store.list_health_states() == []

    def test_get_health_state_missing_returns_none(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        assert store.get_health_state("missing") is None


class TestHealthRestartFlags:
    def test_health_restart_flag_independent_of_other_flags(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("nginx", "pinned")
        store.set_health_restart(["web", "db"])
        assert sorted(store.get_health_restart()) == ["db", "web"]
        assert store.get_pinned() == ["nginx"]

    def test_set_health_restart_empty_clears(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("web", "health_restart")
        store.set_health_restart([])
        assert store.get_health_restart() == []


class TestPermissionsWiden:
    def test_admin_gains_new_permissions_on_upgrade_viewer_does_not(self, tmp_path):
        import json
        import sqlite3

        path = tmp_path / "test.db"
        conn = sqlite3.connect(path)
        conn.execute(
            """
            CREATE TABLE roles (
                name TEXT PRIMARY KEY,
                permissions TEXT NOT NULL,
                is_builtin INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "INSERT INTO roles (name, permissions, is_builtin) VALUES ('admin', ?, 1)",
            (json.dumps([
                "view_containers", "update_containers", "delete_containers",
                "scan_containers", "manage_settings", "manage_users",
            ]),),
        )
        conn.execute(
            "INSERT INTO roles (name, permissions, is_builtin) VALUES ('viewer', ?, 1)",
            (json.dumps(["view_containers"]),),
        )
        conn.commit()
        conn.close()

        store = ManifestStore(path=path)

        admin = store.get_role("admin")
        viewer = store.get_role("viewer")
        assert admin is not None
        assert viewer is not None
        assert "restart_containers" in admin.permissions
        assert "prune_images" in admin.permissions
        assert "restart_containers" not in viewer.permissions
        assert "prune_images" not in viewer.permissions


if __name__ == "__main__":
    unittest.main()
