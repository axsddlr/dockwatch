"""Container check, update, and pin/unpin endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ...models import UpdateResult
from ...registry import check_all
from ...sources import discover_containers
from ...updater import build_update_plan, execute_update
from ..deps import get_config, get_results_cache, get_results_lock, get_store
from ..serializers import serialize_update_results
from ..ws import manager

router = APIRouter()


@router.get("/containers")
def list_containers() -> Any:
    cache = get_results_cache()
    return serialize_update_results(cache)


@router.post("/containers/check")
async def check_containers(
    source: str = Query(default="local"),
    environment: str | None = Query(default=None),
) -> Any:
    lock = get_results_lock()
    if lock.locked():
        raise HTTPException(status_code=409, detail="A check is already in progress.")

    async with lock:
        await manager.broadcast("check_started", {})
        config = get_config()
        discovery = await discover_containers(config, source=source, selected_environment=environment)
        containers = discovery.containers
        store = get_store()
        results = await check_all(containers, config, store=store, max_concurrency=config.max_concurrent_checks)
        cache = get_results_cache()
        cache.clear()
        cache.extend(results)
        serialized = serialize_update_results(results)
        await manager.broadcast("check_complete", {"results": serialized})
        return serialized


@router.post("/containers/{name}/update")
async def update_container(name: str) -> Any:
    cache = get_results_cache()
    match: UpdateResult | None = None
    for r in cache:
        if r.container_info.name == name:
            match = r
            break
    if match is None:
        raise HTTPException(status_code=404, detail=f"Container '{name}' not found in results. Run a check first.")

    config = get_config()
    plan = build_update_plan(match, config)
    if not plan.allowed:
        raise HTTPException(status_code=422, detail=plan.reason or "Update is blocked.")

    execution = await asyncio.to_thread(execute_update, plan, config)
    payload = {
        "name": name,
        "success": execution.success,
        "message": execution.message,
        "details": execution.details,
        "rollback_message": execution.rollback_message,
    }
    await manager.broadcast("container_updated", payload)
    return {"ok": execution.success, "plan": payload}


@router.post("/containers/{name}/pin")
def pin_container(name: str) -> Any:
    from ...config import load_config, save_config

    config = load_config()
    if name not in config.pinned:
        config.pinned = [*config.pinned, name]
        save_config(config)
    return {"ok": True, "pinned": config.pinned}


@router.delete("/containers/{name}/pin")
def unpin_container(name: str) -> Any:
    from ...config import load_config, save_config

    config = load_config()
    if name not in config.pinned:
        raise HTTPException(status_code=404, detail=f"'{name}' is not pinned.")
    config.pinned = [c for c in config.pinned if c != name]
    save_config(config)
    return {"ok": True, "pinned": config.pinned}
