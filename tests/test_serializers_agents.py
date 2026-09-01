from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dockwatch.api.serializers import deserialize_settings
from dockwatch.config import DockwatchConfig
from dockwatch.db import ManifestStore


class DeserializeAgentsTests(unittest.TestCase):
    def _store(self, tmp_dir: str) -> ManifestStore:
        return ManifestStore(Path(tmp_dir) / "manifests.db")

    def test_rejects_duplicate_agent_names(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            data = {
                "agents": [
                    {"name": "media-pc", "url": "http://a:8081", "token": "a" * 16, "enabled": True},
                    {"name": "media-pc", "url": "http://b:8081", "token": "b" * 16, "enabled": True},
                ]
            }
            with self.assertRaises(ValueError):
                deserialize_settings(data, DockwatchConfig(), store)

    def test_rejects_short_agent_token(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            data = {"agents": [{"name": "media-pc", "url": "http://a:8081", "token": "short", "enabled": True}]}
            with self.assertRaises(ValueError):
                deserialize_settings(data, DockwatchConfig(), store)

    def test_accepts_unique_agents_with_strong_tokens(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            data = {
                "agents": [
                    {"name": "media-pc", "url": "http://a:8081", "token": "a" * 16, "enabled": True},
                    {"name": "nas", "url": "http://b:8081", "token": "b" * 16, "enabled": True},
                ]
            }
            updated = deserialize_settings(data, DockwatchConfig(), store)
            self.assertEqual({a.name for a in updated.agents}, {"media-pc", "nas"})


if __name__ == "__main__":
    unittest.main()
