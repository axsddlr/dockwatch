"""Container health state and manual-check endpoints."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends

from ...health import HealthMonitor
from ..deps import get_config, get_store
from ..rate_limit import rate_limit
from ..security import require_permission
from ..ws import manager

router = APIRouter()
_mutate_limit = Depends(rate_limit(10, 60))


@router.get("/health/containers", dependencies=[Depends(require_permission("view_containers"))])
def list_health() -> Any:
    """Return the persisted per-container health state list."""
    store = get_store()
    return [asdict(record) for record in store.list_health_states()]


@router.post("/health/check", dependencies=[_mutate_limit, Depends(require_permission("restart_containers"))])
async def run_health_check() -> Any:
    """Run one health sampling cycle on demand.

    ``force=True`` is deliberate: an operator must be able to inspect and
    report health even while the background feature is disabled, matching the
    engine's manual one-shot contract.
    """
    config = get_config()
    store = get_store()
    monitor = HealthMonitor(config=config, store=store, broadcast=manager.broadcast)
    await monitor.run_once(force=True)
    return {"ok": True, "states": [asdict(record) for record in store.list_health_states()]}
