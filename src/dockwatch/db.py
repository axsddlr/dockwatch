"""SQLite-backed manifest state storage."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json as _json
import sqlite3

from .models import ContainerInfo, TrivyFinding, TrivyScanResult

STATE_DB_PATH = Path.home() / ".config" / "dockwatch" / "manifests.db"

VALID_PERMISSIONS = frozenset({
    "view_containers",
    "update_containers",
    "scan_containers",
    "manage_settings",
    "manage_users",
})


@dataclass(slots=True)
class ManifestRecord:
    image_key: str
    image_ref: str
    current_tag: str
    last_seen_digest: str | None
    last_seen_latest_tag: str | None
    last_checked_at: str


@dataclass(slots=True)
class UserRecord:
    id: int
    username: str
    password_hash: str
    role_name: str
    created_at: str


@dataclass(slots=True)
class RoleRecord:
    name: str
    permissions: list[str]
    is_builtin: bool


@dataclass(slots=True)
class UpdateHistoryRecord:
    id: int
    container_name: str
    action: str
    source: str
    environment_id: str | None
    old_tag: str | None
    new_tag: str | None
    old_digest: str | None
    new_digest: str | None
    status: str
    error: str | None
    user_id: int | None
    username: str | None
    created_at: str


UPDATE_HISTORY_MAX_PER_CONTAINER = 10


def build_image_key(info: ContainerInfo) -> str:
    return f"{info.registry.value}|{info.namespace}|{info.image_name}|{info.current_tag}"


def build_legacy_image_key(info: ContainerInfo) -> str:
    return f"{info.image_ref}|{info.current_tag}"


class ManifestStore:
    def __init__(self, path: Path = STATE_DB_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _fetch(self, connection: sqlite3.Connection, image_key: str) -> ManifestRecord | None:
        row = connection.execute(
            """
            SELECT image_key, image_ref, current_tag, last_seen_digest, last_seen_latest_tag, last_checked_at
            FROM manifest_state
            WHERE image_key = ?
            """,
            (image_key,),
        ).fetchone()
        if row is None:
            return None
        return ManifestRecord(*row)

    def _fetch_any(self, connection: sqlite3.Connection, info: ContainerInfo) -> tuple[str, ManifestRecord] | None:
        image_key = build_image_key(info)
        current = self._fetch(connection, image_key)
        if current is not None:
            return image_key, current
        legacy_key = build_legacy_image_key(info)
        legacy = self._fetch(connection, legacy_key)
        if legacy is not None:
            return legacy_key, legacy
        return None

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS manifest_state (
                    image_key TEXT PRIMARY KEY,
                    image_ref TEXT NOT NULL,
                    current_tag TEXT NOT NULL,
                    last_seen_digest TEXT,
                    last_seen_latest_tag TEXT,
                    last_checked_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trivy_scan_cache (
                    image_id TEXT PRIMARY KEY,
                    image_ref TEXT NOT NULL,
                    scan_json TEXT NOT NULL,
                    critical_count INTEGER NOT NULL DEFAULT 0,
                    high_count INTEGER NOT NULL DEFAULT 0,
                    medium_count INTEGER NOT NULL DEFAULT 0,
                    low_count INTEGER NOT NULL DEFAULT 0,
                    scanned_at TEXT NOT NULL
                )
                """
            )
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS roles (
                    name TEXT PRIMARY KEY,
                    permissions TEXT NOT NULL,
                    is_builtin INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role_name TEXT NOT NULL REFERENCES roles(name),
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS update_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    container_name TEXT NOT NULL,
                    action TEXT NOT NULL CHECK (action IN ('update', 'rollback', 'restart', 'digest_drift_detected')),
                    source TEXT NOT NULL CHECK (source IN ('local', 'portainer')),
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
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_update_history_container "
                "ON update_history (container_name, created_at)"
            )
            existing_admin = connection.execute(
                "SELECT 1 FROM roles WHERE name = 'admin'"
            ).fetchone()
            if existing_admin is None:
                connection.execute(
                    "INSERT INTO roles (name, permissions, is_builtin) VALUES (?, ?, 1)",
                    ("admin", _json.dumps(sorted(VALID_PERMISSIONS))),
                )
                connection.execute(
                    "INSERT INTO roles (name, permissions, is_builtin) VALUES (?, ?, 1)",
                    ("viewer", _json.dumps(["view_containers"])),
                )

    def get(self, info: ContainerInfo) -> ManifestRecord | None:
        with closing(self._connect()) as connection, connection:
            found = self._fetch_any(connection, info)
            return found[1] if found else None

    def record_observation(
        self,
        info: ContainerInfo,
        *,
        latest_tag: str | None,
        remote_digest: str | None,
        checked_at: str | None = None,
    ) -> str | None:
        observed_at = checked_at or datetime.now(timezone.utc).isoformat()
        image_key = build_image_key(info)
        legacy_key = build_legacy_image_key(info)
        event: str | None = None
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = self._fetch(connection, image_key) or self._fetch(connection, legacy_key)
            if previous is None:
                event = "new"
            elif previous.last_seen_digest != remote_digest or previous.last_seen_latest_tag != latest_tag:
                event = "update"
            connection.execute(
                """
                INSERT INTO manifest_state (
                    image_key,
                    image_ref,
                    current_tag,
                    last_seen_digest,
                    last_seen_latest_tag,
                    last_checked_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(image_key) DO UPDATE SET
                    image_ref = excluded.image_ref,
                    current_tag = excluded.current_tag,
                    last_seen_digest = excluded.last_seen_digest,
                    last_seen_latest_tag = excluded.last_seen_latest_tag,
                    last_checked_at = excluded.last_checked_at
                """,
                (
                    image_key,
                    info.image_ref,
                    info.current_tag,
                    remote_digest,
                    latest_tag,
                    observed_at,
                ),
            )
            if legacy_key != image_key:
                connection.execute("DELETE FROM manifest_state WHERE image_key = ?", (legacy_key,))
        return event

    def trivy_cache_get(
        self,
        image_id: str,
        *,
        cache_ttl_minutes: int = 60,
    ) -> TrivyScanResult | None:
        import json  # noqa: PLC0415

        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT image_ref, scan_json, critical_count, high_count, medium_count, low_count, scanned_at
                FROM trivy_scan_cache
                WHERE image_id = ?
                """,
                (image_id,),
            ).fetchone()
        if row is None:
            return None
        image_ref, scan_json, critical, high, medium, low, scanned_at = row
        try:
            scanned_dt = datetime.fromisoformat(scanned_at)
            age = (datetime.now(timezone.utc) - scanned_dt).total_seconds()
            if age > cache_ttl_minutes * 60:
                return None
        except (ValueError, TypeError):
            return None

        try:
            findings_data = json.loads(scan_json)
            findings = [TrivyFinding(**f) for f in findings_data]
        except (json.JSONDecodeError, TypeError, KeyError):
            return None
        return TrivyScanResult(
            image_ref=image_ref,
            findings=findings,
            critical_count=critical,
            high_count=high,
            medium_count=medium,
            low_count=low,
            scanned_at=scanned_at,
            image_id=image_id,
        )

    def trivy_cache_put(self, image_id: str, result: TrivyScanResult) -> None:
        import json  # noqa: PLC0415

        scanned_at = datetime.now(timezone.utc).isoformat()
        findings_data = json.dumps([{
            "vulnerability_id": f.vulnerability_id,
            "pkg_name": f.pkg_name,
            "installed_version": f.installed_version,
            "fixed_version": f.fixed_version,
            "severity": f.severity,
            "title": f.title,
            "primary_url": f.primary_url,
            "target": f.target,
            "class_type": f.class_type,
        } for f in result.findings])
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO trivy_scan_cache (
                    image_id, image_ref, scan_json,
                    critical_count, high_count, medium_count, low_count,
                    scanned_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(image_id) DO UPDATE SET
                    image_ref = excluded.image_ref,
                    scan_json = excluded.scan_json,
                    critical_count = excluded.critical_count,
                    high_count = excluded.high_count,
                    medium_count = excluded.medium_count,
                    low_count = excluded.low_count,
                    scanned_at = excluded.scanned_at
                """,
                (
                    image_id,
                    result.image_ref,
                    findings_data,
                    result.critical_count,
                    result.high_count,
                    result.medium_count,
                    result.low_count,
                    scanned_at,
                ),
            )

    def trivy_cache_invalidate(self, image_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM trivy_scan_cache WHERE image_id = ?", (image_id,))

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

    # --- Role methods ---

    def get_role(self, name: str) -> RoleRecord | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT name, permissions, is_builtin FROM roles WHERE name = ?",
                (name,),
            ).fetchone()
        if row is None:
            return None
        raw = _json.loads(row[1])
        return RoleRecord(
            name=row[0],
            permissions=[p for p in raw if p in VALID_PERMISSIONS],
            is_builtin=bool(row[2]),
        )

    def list_roles(self) -> list[RoleRecord]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT name, permissions, is_builtin FROM roles ORDER BY name"
            ).fetchall()
        return [
            RoleRecord(
                name=row[0],
                permissions=_json.loads(row[1]),
                is_builtin=bool(row[2]),
            )
            for row in rows
        ]

    def create_role(self, name: str, permissions: list[str]) -> bool:
        name = name.strip()
        normalized = sorted(set(p for p in permissions if p in VALID_PERMISSIONS))
        if not normalized:
            raise ValueError("Role must have at least one valid permission.")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM roles WHERE name = ?", (name,),
            ).fetchone()
            if existing is not None:
                return False
            connection.execute(
                "INSERT INTO roles (name, permissions, is_builtin) VALUES (?, ?, 0)",
                (name, _json.dumps(normalized)),
            )
            return True

    def update_role_permissions(self, name: str, permissions: list[str]) -> bool:
        name = name.strip()
        normalized = sorted(set(p for p in permissions if p in VALID_PERMISSIONS))
        if not normalized:
            raise ValueError("Role must have at least one valid permission.")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            role = connection.execute(
                "SELECT is_builtin FROM roles WHERE name = ?", (name,),
            ).fetchone()
            if role is None:
                return False
            if bool(role[0]):
                return False
            connection.execute(
                "UPDATE roles SET permissions = ? WHERE name = ?",
                (_json.dumps(normalized), name),
            )
            return True

    def delete_role(self, name: str) -> bool:
        name = name.strip()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            role = connection.execute(
                "SELECT is_builtin FROM roles WHERE name = ?", (name,),
            ).fetchone()
            if role is None:
                return False
            if bool(role[0]):
                return False
            connection.execute("DELETE FROM roles WHERE name = ?", (name,))
            return True

    def get_users_by_role(self, role_name: str) -> list[int]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT id FROM users WHERE role_name = ?", (role_name,),
            ).fetchall()
        return [row[0] for row in rows]

    def count_users_with_permission(self, permission: str) -> int:
        roles_with_perm = {r.name for r in self.list_roles() if permission in r.permissions}
        if not roles_with_perm:
            return 0
        with closing(self._connect()) as connection, connection:
            placeholders = ", ".join("?" for _ in roles_with_perm)
            row = connection.execute(
                f"SELECT COUNT(*) FROM users WHERE role_name IN ({placeholders})",
                tuple(roles_with_perm),
            ).fetchone()
        return row[0] if row else 0

    # --- User methods ---

    def create_user(self, username: str, password_hash: str, role_name: str) -> int:
        username = username.strip()
        role_name = role_name.strip()
        created_at = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT 1 FROM users WHERE username = ?", (username,),
            ).fetchone()
            if existing is not None:
                raise ValueError(f"User '{username}' already exists.")
            role = connection.execute(
                "SELECT 1 FROM roles WHERE name = ?", (role_name,),
            ).fetchone()
            if role is None:
                raise ValueError(f"Role '{role_name}' does not exist.")
            cursor = connection.execute(
                "INSERT INTO users (username, password_hash, role_name, created_at) VALUES (?, ?, ?, ?)",
                (username, password_hash, role_name, created_at),
            )
            return cursor.lastrowid

    def get_user_by_username(self, username: str) -> UserRecord | None:
        username = username.strip()
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT id, username, password_hash, role_name, created_at FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None:
            return None
        return UserRecord(*row)

    def get_user_by_id(self, user_id: int) -> UserRecord | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT id, username, password_hash, role_name, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return UserRecord(*row)

    def list_users(self) -> list[UserRecord]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT id, username, password_hash, role_name, created_at FROM users ORDER BY id"
            ).fetchall()
        return [UserRecord(*row) for row in rows]

    def update_user_role(self, user_id: int, role_name: str) -> bool:
        role_name = role_name.strip()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            role = connection.execute(
                "SELECT 1 FROM roles WHERE name = ?", (role_name,),
            ).fetchone()
            if role is None:
                raise ValueError(f"Role '{role_name}' does not exist.")
            cursor = connection.execute(
                "UPDATE users SET role_name = ? WHERE id = ?",
                (role_name, user_id),
            )
            return cursor.rowcount > 0

    def delete_user(self, user_id: int) -> bool:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "DELETE FROM users WHERE id = ?", (user_id,),
            )
            return cursor.rowcount > 0

    def count_users(self) -> int:
        with closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT COUNT(*) FROM users").fetchone()
        return row[0] if row else 0

    # --- Update history methods ---

    def record_update_event(
        self,
        *,
        container_name: str,
        action: str,
        source: str,
        status: str,
        environment_id: str | None = None,
        old_tag: str | None = None,
        new_tag: str | None = None,
        old_digest: str | None = None,
        new_digest: str | None = None,
        error: str | None = None,
        user_id: int | None = None,
        username: str | None = None,
    ) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                INSERT INTO update_history (
                    container_name, action, source, environment_id,
                    old_tag, new_tag, old_digest, new_digest,
                    status, error, user_id, username, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    container_name, action, source, environment_id,
                    old_tag, new_tag, old_digest, new_digest,
                    status, error, user_id, username, created_at,
                ),
            )
            row_id = cursor.lastrowid
            stale_ids = connection.execute(
                """
                SELECT id FROM update_history
                WHERE container_name = ?
                ORDER BY created_at DESC, id DESC
                LIMIT -1 OFFSET ?
                """,
                (container_name, UPDATE_HISTORY_MAX_PER_CONTAINER),
            ).fetchall()
            if stale_ids:
                placeholders = ", ".join("?" for _ in stale_ids)
                connection.execute(
                    f"DELETE FROM update_history WHERE id IN ({placeholders})",
                    tuple(row[0] for row in stale_ids),
                )
            return row_id

    def list_update_history(
        self, container_name: str | None = None, limit: int = 50,
    ) -> list[UpdateHistoryRecord]:
        query = (
            "SELECT id, container_name, action, source, environment_id, "
            "old_tag, new_tag, old_digest, new_digest, status, error, "
            "user_id, username, created_at FROM update_history"
        )
        params: tuple = ()
        if container_name is not None:
            query += " WHERE container_name = ?"
            params = (container_name,)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params = params + (limit,)
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(query, params).fetchall()
        return [UpdateHistoryRecord(*row) for row in rows]

    def get_last_successful_update(self, container_name: str) -> UpdateHistoryRecord | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT id, container_name, action, source, environment_id,
                    old_tag, new_tag, old_digest, new_digest, status, error,
                    user_id, username, created_at
                FROM update_history
                WHERE container_name = ? AND action = 'update' AND status = 'success'
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (container_name,),
            ).fetchone()
        return UpdateHistoryRecord(*row) if row else None
