"""SQLite-backed manifest state storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from .models import ContainerInfo, TrivyFinding, TrivyScanResult

STATE_DB_PATH = Path.home() / ".config" / "dockwatch" / "manifests.db"


@dataclass(slots=True)
class ManifestRecord:
    image_key: str
    image_ref: str
    current_tag: str
    last_seen_digest: str | None
    last_seen_latest_tag: str | None
    last_checked_at: str


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
        with self._connect() as connection:
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

    def get(self, info: ContainerInfo) -> ManifestRecord | None:
        with self._connect() as connection:
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
        with self._connect() as connection:
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

        with self._connect() as connection:
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

        findings_data = json.loads(scan_json)
        findings = [
            TrivyFinding(**f)
            for f in findings_data
        ]
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
        with self._connect() as connection:
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
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM trivy_scan_cache WHERE image_id = ?", (image_id,))
