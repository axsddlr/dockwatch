"""Container check, update, and pin/unpin endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ...config import validate_compose_project_config, ComposeProjectConfig
from ...docker_client import compose_labels_to_project_config
from ...models import UpdateResult
from ...registry import check_all
from ...sources import discover_containers
from ...updater import build_update_plan, execute_update
from ..deps import get_config, get_results_cache, get_results_lock, get_store
from ..serializers import serialize_update_results
from ..ws import manager

router = APIRouter()


def _find_result(name: str) -> UpdateResult:
    cache = get_results_cache()
    for r in cache:
        if r.container_info.name == name:
            return r
    raise HTTPException(status_code=404, detail=f"Container '{name}' not found in results. Run a check first.")


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
    match = _find_result(name)
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


@router.get("/containers/{name}/compose-detect")
def detect_compose_config(name: str) -> Any:
    match = _find_result(name)
    info = match.container_info
    if not info.compose_project:
        raise HTTPException(status_code=422, detail=f"'{name}' is not a compose-managed container.")

    detected = compose_labels_to_project_config(info.labels, project_name=info.compose_project)
    warnings = validate_compose_project_config(detected)
    return {
        "compose_project": info.compose_project,
        "detected": {
            "workdir": detected.workdir,
            "files": detected.files,
            "project_name": detected.project_name,
        },
        "warnings": warnings,
    }


@router.post("/containers/{name}/compose-detect/validate")
def validate_compose_config(name: str, body: dict[str, Any]) -> Any:
    _find_result(name)
    cfg = ComposeProjectConfig(
        workdir=str(body.get("workdir", "")),
        files=[str(f) for f in body.get("files", []) if str(f).strip()],
        project_name=str(body.get("project_name", "")),
    )
    return {"warnings": validate_compose_project_config(cfg)}


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
