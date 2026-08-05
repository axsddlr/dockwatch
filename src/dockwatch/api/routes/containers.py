"""Container check, update, and pin/unpin endpoints."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from docker.errors import DockerException

from ... import docker_client
from ...config import validate_compose_project_config, ComposeProjectConfig
from ...integrations import PortainerClient, PortainerError
from ...models import UpdateResult
from ...registry import check_all, record_digest_drift_events
from ...sources import discover_containers
from ...updater import build_rollback_plan, build_update_plan, execute_portainer_compose_update, execute_update
from ..deps import get_config, get_results_cache, get_results_lock, get_store
from ..security import AuthenticatedUser, require_permission
from ..serializers import serialize_update_results
from ..ws import manager

router = APIRouter()


def _merge_check_results(
    cache: list[UpdateResult], results: list[UpdateResult], source: str,
) -> list[UpdateResult]:
    """Merge a fresh check's results into the existing cache.

    Fresh results are deduplicated by container name: when the same
    container appears more than once (e.g. via both local Docker and
    Portainer in an "all" check), the Portainer entry wins.

    A subsequent local-only check must not downgrade a container that
    Portainer previously reported as managed; Portainer identity
    (source, environment_id, environment_name) is preserved.

    Stale cache entries whose names are absent from the fresh results
    survive so that e.g. a Portainer-only check doesn't erase containers
    only visible on the local Docker socket, and vice versa.
    """
    # Step 1: deduplicate fresh results within themselves.
    deduped: dict[str, UpdateResult] = {}
    for r in results:
        name = r.container_info.name
        existing = deduped.get(name)
        if existing is None:
            deduped[name] = r
        elif r.container_info.source == "portainer" and existing.container_info.source != "portainer":
            deduped[name] = r
    deduped_list = list(deduped.values())

    # Step 2: build a map of prior Portainer identities from the cache.
    prior_portainer: dict[str, ContainerInfo] = {
        r.container_info.name: r.container_info
        for r in cache
        if r.container_info.source == "portainer"
    }

    # Step 3: apply prior Portainer identity to fresh results whose name
    # matches a known Portainer container from the cache.
    if source != "portainer":
        for i, result in enumerate(deduped_list):
            prior = prior_portainer.get(result.container_info.name)
            if prior is not None and result.container_info.source != "portainer":
                deduped_list[i] = replace(
                    result,
                    container_info=replace(
                        result.container_info,
                        source=prior.source,
                        environment_id=prior.environment_id,
                        environment_name=prior.environment_name,
                    ),
                )

    # Step 4: keep stale cache entries not present in fresh results.
    fresh_names = {r.container_info.name for r in deduped_list}
    stale = [r for r in cache if r.container_info.name not in fresh_names]

    return stale + deduped_list


def _log_action(
    name: str,
    action: str,
    source: str,
    *,
    success: bool,
    error: str | None,
    current_user: AuthenticatedUser,
    **extra: Any,
) -> None:
    get_store().record_update_event(
        container_name=name,
        action=action,
        source=source,
        status="success" if success else "failed",
        error=error,
        user_id=current_user.user_id,
        username=current_user.username,
        **extra,
    )


def _find_result(name: str) -> UpdateResult:
    cache = get_results_cache()
    for r in cache:
        if r.container_info.name == name:
            return r
    raise HTTPException(status_code=404, detail=f"Container '{name}' not found in results. Run a check first.")


@router.get("/containers", dependencies=[Depends(require_permission("view_containers"))])
def list_containers() -> Any:
    cache = get_results_cache()
    return serialize_update_results(cache)


@router.post("/containers/check", dependencies=[Depends(require_permission("scan_containers"))])
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
        record_digest_drift_events(results, store)

        cache = get_results_cache()
        merged = _merge_check_results(cache, results, source)
        cache[:] = merged

        serialized = serialize_update_results(results)
        await manager.broadcast("check_complete", {"results": serialized})
        return serialized


@router.post("/containers/{name}/update")
async def update_container(
    name: str,
    current_user: AuthenticatedUser = Depends(require_permission("update_containers")),
) -> Any:
    match = _find_result(name)
    config = get_config()
    plan = build_update_plan(match, config)
    if not plan.allowed:
        raise HTTPException(status_code=422, detail=plan.reason or "Update is blocked.")

    if plan.mode == "portainer-compose":
        execution = await execute_portainer_compose_update(plan, config)
    else:
        execution = await asyncio.to_thread(execute_update, plan, config)
    payload = {
        "name": name,
        "success": execution.success,
        "message": execution.message,
        "details": execution.details,
        "rollback_message": execution.rollback_message,
    }
    _log_action(
        name, "update", plan.source,
        success=execution.success,
        error=None if execution.success else execution.message,
        current_user=current_user,
        old_tag=plan.current_tag,
        new_tag=plan.remote_tag,
        environment_id=plan.environment_id,
    )
    await manager.broadcast("container_updated", payload)
    return {"ok": execution.success, "plan": payload}


@router.post("/containers/{name}/rollback")
async def rollback_container(
    name: str,
    current_user: AuthenticatedUser = Depends(require_permission("update_containers")),
) -> Any:
    match = _find_result(name)
    store = get_store()
    last = store.get_last_successful_update(name)
    if last is None or not last.old_tag or not last.new_tag:
        raise HTTPException(status_code=404, detail=f"No recorded update to roll back for '{name}'.")

    config = get_config()
    plan = build_rollback_plan(match, config, old_tag=last.old_tag, new_tag=last.new_tag)
    if not plan.allowed:
        raise HTTPException(status_code=422, detail=plan.reason or "Rollback is blocked.")

    execution = await asyncio.to_thread(execute_update, plan, config)
    payload = {
        "name": name,
        "success": execution.success,
        "message": execution.message,
        "details": execution.details,
        "rollback_message": execution.rollback_message,
    }
    _log_action(
        name, "rollback", plan.source,
        success=execution.success,
        error=None if execution.success else execution.message,
        current_user=current_user,
        old_tag=plan.current_tag,
        new_tag=plan.remote_tag,
    )
    await manager.broadcast("container_updated", payload)
    return {"ok": execution.success, "plan": payload}


@router.post("/containers/{name}/restart")
async def restart_container(
    name: str,
    current_user: AuthenticatedUser = Depends(require_permission("update_containers")),
) -> Any:
    match = _find_result(name)
    info = match.container_info
    if info.source != "portainer":
        raise HTTPException(status_code=422, detail="Restart is only supported for Portainer-managed containers.")
    if not info.environment_id:
        raise HTTPException(status_code=422, detail=f"'{name}' has no associated Portainer environment.")

    config = get_config()
    try:
        client = PortainerClient(base_url=config.portainer.url, api_key=config.portainer.api_key)
        await client.restart_container(int(info.environment_id), info.container_id)
    except PortainerError as exc:
        _log_action(
            name, "restart", "portainer",
            success=False, error=str(exc), current_user=current_user,
            environment_id=info.environment_id,
        )
        raise HTTPException(status_code=502, detail=str(exc))

    _log_action(
        name, "restart", "portainer",
        success=True, error=None, current_user=current_user,
        environment_id=info.environment_id,
    )
    payload = {"name": name, "success": True, "message": f"Restarted '{name}' via Portainer."}
    await manager.broadcast("container_updated", payload)
    return {"ok": True, "plan": payload}


@router.delete("/containers/{name}")
async def delete_container(
    name: str,
    force: bool = Query(default=False),
    current_user: AuthenticatedUser = Depends(require_permission("delete_containers")),
) -> Any:
    match = _find_result(name)
    info = match.container_info

    if info.source == "portainer":
        if not info.environment_id:
            raise HTTPException(status_code=422, detail=f"'{name}' has no associated Portainer environment.")
        config = get_config()
        try:
            client = PortainerClient(base_url=config.portainer.url, api_key=config.portainer.api_key)
            await client.delete_container(int(info.environment_id), info.container_id, force=force)
        except PortainerError as exc:
            _log_action(
                name, "delete_container", "portainer",
                success=False, error=str(exc), current_user=current_user,
                environment_id=info.environment_id,
            )
            raise HTTPException(status_code=502, detail=str(exc))
        _log_action(
            name, "delete_container", "portainer",
            success=True, error=None, current_user=current_user,
            environment_id=info.environment_id,
        )
    else:
        try:
            await asyncio.to_thread(docker_client.delete_container, name, force=force)
        except DockerException as exc:
            _log_action(name, "delete_container", "local", success=False, error=str(exc), current_user=current_user)
            raise HTTPException(status_code=502, detail=str(exc))
        _log_action(name, "delete_container", "local", success=True, error=None, current_user=current_user)

    cache = get_results_cache()
    cache[:] = [r for r in cache if r.container_info.name != name]
    await manager.broadcast("container_deleted", {"name": name})
    return {"ok": True, "name": name}


@router.delete("/containers/{name}/image")
async def delete_container_image(
    name: str,
    force: bool = Query(default=False),
    current_user: AuthenticatedUser = Depends(require_permission("delete_containers")),
) -> Any:
    match = _find_result(name)
    info = match.container_info
    if info.source != "local":
        raise HTTPException(status_code=422, detail="Image delete is only supported for local Docker containers.")

    image_id = docker_client.get_image_id(name)
    if not image_id:
        raise HTTPException(status_code=404, detail=f"Could not resolve an image ID for '{name}'.")

    try:
        await asyncio.to_thread(docker_client.delete_image, image_id, force=force)
    except DockerException as exc:
        _log_action(
            name, "delete_image", "local", success=False, error=str(exc), current_user=current_user,
            old_digest=image_id,
        )
        raise HTTPException(status_code=502, detail=str(exc))

    _log_action(
        name, "delete_image", "local", success=True, error=None, current_user=current_user,
        old_digest=image_id,
    )
    return {"ok": True, "name": name, "image_id": image_id}


@router.get("/containers/{name}/compose-detect", dependencies=[Depends(require_permission("update_containers"))])
def detect_compose_config(name: str) -> Any:
    match = _find_result(name)
    info = match.container_info
    if not info.compose_project:
        raise HTTPException(status_code=422, detail=f"'{name}' is not a compose-managed container.")

    detected = docker_client.compose_labels_to_project_config(info.labels, project_name=info.compose_project)
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


@router.post("/containers/{name}/compose-detect/validate", dependencies=[Depends(require_permission("update_containers"))])
def validate_compose_config(name: str, body: dict[str, Any]) -> Any:
    _find_result(name)
    cfg = ComposeProjectConfig(
        workdir=str(body.get("workdir", "")),
        files=[str(f) for f in body.get("files", []) if str(f).strip()],
        project_name=str(body.get("project_name", "")),
    )
    return {"warnings": validate_compose_project_config(cfg)}


@router.post("/containers/{name}/pin", dependencies=[Depends(require_permission("update_containers"))])
def pin_container(name: str) -> Any:
    store = get_store()
    store.add_flag(name, "pinned")
    return {"ok": True, "pinned": store.get_pinned()}


@router.delete("/containers/{name}/pin", dependencies=[Depends(require_permission("update_containers"))])
def unpin_container(name: str) -> Any:
    store = get_store()
    removed = store.remove_flag(name, "pinned")
    if not removed:
        raise HTTPException(status_code=404, detail=f"'{name}' is not pinned.")
    return {"ok": True, "pinned": store.get_pinned()}


@router.get("/containers/{name}/history", dependencies=[Depends(require_permission("manage_settings"))])
def get_container_history(name: str) -> Any:
    store = get_store()
    records = store.list_update_history(container_name=name)
    return [
        {
            "id": r.id,
            "action": r.action,
            "source": r.source,
            "environment_id": r.environment_id,
            "old_tag": r.old_tag,
            "new_tag": r.new_tag,
            "old_digest": r.old_digest,
            "new_digest": r.new_digest,
            "status": r.status,
            "error": r.error,
            "user_id": r.user_id,
            "username": r.username,
            "created_at": r.created_at,
        }
        for r in records
    ]
