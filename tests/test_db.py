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


if __name__ == "__main__":
    unittest.main()
