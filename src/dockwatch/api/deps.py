"""FastAPI dependencies providing shared singletons."""

from __future__ import annotations

import asyncio

from ..config import DockwatchConfig, load_config
from ..db import ManifestStore
from ..models import UpdateResult

_store = ManifestStore()
_results_lock = asyncio.Lock()
_results_cache: list[UpdateResult] = []


def get_store() -> ManifestStore:
    return _store


def get_config() -> DockwatchConfig:
    return load_config()


def get_results_cache() -> list[UpdateResult]:
    return _results_cache


def get_results_lock() -> asyncio.Lock:
    return _results_lock
