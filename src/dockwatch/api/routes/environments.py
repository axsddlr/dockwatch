"""Environment discovery endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

from ...config import load_config
from ...integrations import PortainerError
from ...sources import discover_environments

router = APIRouter()


@router.get("/environments")
def get_environments() -> Any:
    config = load_config()
    try:
        environments = asyncio.run(discover_environments(config))
    except (PortainerError, Exception) as exc:  # noqa: BLE001
        return {"environments": [], "error": str(exc)}
    return {"environments": [{"id": e.id, "name": e.name} for e in environments]}
