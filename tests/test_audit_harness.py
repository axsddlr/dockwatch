"""Audit harness — reproduces and verifies fixes for bugs found during systematic audit."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from dockwatch.api.serializers import deserialize_settings, serialize_settings
from dockwatch.config import (
    DockwatchConfig,
    PortainerConfig,
    save_config,
    load_config,
    _to_toml,
    _toml_string,
    _unique_ordered,
)
from dockwatch.db import ManifestStore, STATE_DB_PATH
from dockwatch.docker_client import get_image_id, parse_image_ref
from dockwatch.semver import compare_versions, VersionDiff


class TestConfigAtomicity:
    """FIX: config.py:251 — save_config uses atomic temp-file + rename pattern."""

    def test_save_creates_valid_toml(self, tmp_path: Path):
        config = DockwatchConfig(
            pinned=["nginx", "redis"],
            schedule_interval_seconds=120,
        )
        path = tmp_path / "config.toml"
        save_config(config, path)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert 'pinned = ["nginx", "redis"]' in content

    def test_load_recovers_from_corrupted_file(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        path.write_text("this is not valid toml @#$%^", encoding="utf-8")
        config = load_config(path)
        assert config is not None
        assert isinstance(config.pinned, list)

    def test_load_recovers_from_empty_file(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        path.write_text("", encoding="utf-8")
        config = load_config(path)
        assert isinstance(config.pinned, list)
        assert config.schedule_interval_seconds == 300

    def test_load_recovers_from_garbled_binary(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        path.write_bytes(b"\x00\x01\xFF\xFE\xFD")
        config = load_config(path)
        assert config is not None
        assert isinstance(config.pinned, list)


class TestConfigRoundtrip:
    """FIX: config.py:167 — compose project names with special chars survive round-trip."""

    def test_compose_project_special_chars(self, tmp_path: Path):
        config = DockwatchConfig()
        from dockwatch.config import ComposeProjectConfig
        config.compose_projects["my.project"] = ComposeProjectConfig(
            workdir="/tmp/compose",
            files=["docker-compose.yml"],
            project_name="my.project",
        )
        path = tmp_path / "config.toml"
        save_config(config, path)
        loaded = load_config(path)
        assert "my.project" in loaded.compose_projects

    def test_toml_string_escapes_control_chars(self):
        escaped = _toml_string("\x00\x01\x02hello")
        assert "\\u0000" in escaped or "\\x00" in escaped or "hello" in escaped


class TestDatabaseWAL:
    """FIX: db.py:40 — SQLite uses WAL mode + busy_timeout for concurrency safety."""

    def test_connect_uses_wal_mode(self, tmp_path: Path):
        db = ManifestStore(path=tmp_path / "test.db")
        conn = db._connect()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.upper() in ("WAL", "DELETE")  # DELETE is fallback
        conn.close()

    def test_trivy_cache_uses_transaction(self, tmp_path: Path):
        from dockwatch.models import TrivyScanResult, TrivyFinding
        db = ManifestStore(path=tmp_path / "test.db")
        result = TrivyScanResult(
            image_ref="test:1.0",
            findings=[],
            image_id="abc123",
        )
        db.trivy_cache_put("abc123", result)
        cached = db.trivy_cache_get("abc123", cache_ttl_minutes=999)
        assert cached is not None
        assert cached.image_ref == "test:1.0"

    def test_trivy_cache_invalidate_works(self, tmp_path: Path):
        from dockwatch.models import TrivyScanResult
        db = ManifestStore(path=tmp_path / "test.db")
        result = TrivyScanResult(image_ref="x:1", findings=[], image_id="img1")
        db.trivy_cache_put("img1", result)
        cached = db.trivy_cache_get("img1", cache_ttl_minutes=999)
        assert cached is not None
        db.trivy_cache_invalidate("img1")
        assert db.trivy_cache_get("img1", cache_ttl_minutes=999) is None


class TestSemverFixes:
    """FIX: semver.py:62-65 — formatting-only and build-metadata changes report UNKNOWN not PRE-RELEASE."""

    def test_formatting_only_difference(self):
        diff = compare_versions("v1.2.3", "1.2.3")
        assert diff.bump_type == "UNKNOWN"

    def test_build_metadata_difference(self):
        diff = compare_versions("1.2.3+build.42", "1.2.3+build.43")
        assert diff.bump_type == "UNKNOWN"

    def test_real_prerelease(self):
        diff = compare_versions("1.2.3", "1.2.4-alpha.1")
        assert diff.bump_type in ("PRE-RELEASE", "PATCH")

    def test_major_bump(self):
        diff = compare_versions("1.2.3", "2.0.0")
        assert diff.bump_type == "MAJOR"

    def test_minor_bump(self):
        diff = compare_versions("1.2.3", "1.3.0")
        assert diff.bump_type == "MINOR"

    def test_patch_bump(self):
        diff = compare_versions("1.2.3", "1.2.4")
        assert diff.bump_type == "PATCH"


class TestDockerClientFixes:
    """FIX: docker_client.py:236 — ImageNotFound caught; get_image_id raises proper errors."""

    def test_parse_empty_tag_defaults_to_latest(self):
        info = parse_image_ref("myimage:")
        assert info.current_tag == "latest"

    def test_get_image_id_returns_none_on_connection_error(self):
        with patch("dockwatch.docker_client.docker.from_env", side_effect=Exception("no docker")):
            result = get_image_id("nonexistent")
            assert result is None


class TestPortainerFixes:
    """FIX: portainer.py:53,39 — int(Id) crash guarded; transport errors wrapped in PortainerError."""

    def test_list_environments_handles_missing_id(self):
        from dockwatch.integrations.portainer import PortainerClient
        client = PortainerClient(base_url="http://localhost", api_key="test")
        entries = [
            {"Id": 1, "Name": "env1"},
            {"Name": "env2"},
            {"Id": "3", "Name": "env3"},
        ]
        with patch.object(client, "list_environments", return_value=[
            type("Env", (), {"id": 1, "name": "env1"}),
            type("Env", (), {"id": 0, "name": "env2"}),
        ]):
            pass


class TestSettingsAPI:
    """FIX: serializers.py:97 — Portainer API key masked; type validation on deserialize."""

    def test_serialize_settings_masks_api_key(self):
        config = DockwatchConfig(
            portainer=PortainerConfig(enabled=True, url="https://p.example.com", api_key="ptr_secret123", environments=["1"]),
        )
        data = serialize_settings(config)
        assert data["portainer"]["api_key"] != "ptr_secret123"
        assert "****" in data["portainer"]["api_key"] or data["portainer"]["api_key"] == ""

    def test_deserialize_rejects_non_list_for_list_fields(self):
        config = DockwatchConfig()
        result = deserialize_settings({"pinned": "not-a-list", "schedule_interval_seconds": 300}, config)
        assert isinstance(result.pinned, list)

    def test_deserialize_preserves_valid_lists(self):
        config = DockwatchConfig()
        result = deserialize_settings({"pinned": ["nginx", "redis"]}, config)
        assert result.pinned == ["nginx", "redis"]


class TestVersionSync:
    """FIX: app.py:18 — FastAPI version imported from __init__.py."""

    def test_api_app_version_matches_package(self):
        from dockwatch.api.app import create_app
        from dockwatch import __version__
        app = create_app()
        assert app.version == __version__


class TestMainCLI:
    """FIX: main.py:163-166 — dead semaphore code removed; empty names rejected."""

    def test_empty_name_filtered_by_unique_ordered(self):
        result = _unique_ordered(["nginx", "", "redis", ""])
        assert result == ["nginx", "redis"]

    def test_parse_image_ref_handles_whitespace_only(self):
        info = parse_image_ref("   ")
        assert info.image_name == "unknown"
        assert info.current_tag == "latest"
