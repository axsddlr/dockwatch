"""SQLite-backed manifest state storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from .models import ContainerInfo

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
    return f"{info.image_ref}|{info.current_tag}"


class ManifestStore:
    def __init__(self, path: Path = STATE_DB_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

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

    def get(self, info: ContainerInfo) -> ManifestRecord | None:
        image_key = build_image_key(info)
        with self._connect() as connection:
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

    def record_observation(
        self,
        info: ContainerInfo,
        *,
        latest_tag: str | None,
        remote_digest: str | None,
        checked_at: str | None = None,
    ) -> str | None:
        previous = self.get(info)
        event: str | None = None
        if previous is None:
            event = "new"
        elif previous.last_seen_digest != remote_digest or previous.last_seen_latest_tag != latest_tag:
            event = "update"

        observed_at = checked_at or datetime.now(timezone.utc).isoformat()
        image_key = build_image_key(info)
        with self._connect() as connection:
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
        return event
