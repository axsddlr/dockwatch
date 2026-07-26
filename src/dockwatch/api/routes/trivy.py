"""Trivy vulnerability scan endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...config import load_config
from ...db import ManifestStore
from ...docker_client import get_image_id
from ...models import TrivyScanResult
from ...trivy import TrivyNotFoundError, scan_image
from ..security import require_permission
from ..ws import manager

router = APIRouter()


def _serialize_finding(finding) -> dict[str, Any]:
    return {
        "vulnerability_id": finding.vulnerability_id,
        "pkg_name": finding.pkg_name,
        "installed_version": finding.installed_version,
        "fixed_version": finding.fixed_version,
        "severity": finding.severity,
        "title": finding.title,
        "primary_url": finding.primary_url,
        "target": finding.target,
        "class_type": finding.class_type,
    }


def _serialize_scan_result(result: TrivyScanResult) -> dict[str, Any]:
    return {
        "image_ref": result.image_ref,
        "critical_count": result.critical_count,
        "high_count": result.high_count,
        "medium_count": result.medium_count,
        "low_count": result.low_count,
        "total_count": result.total_count,
        "error": result.error,
        "scanned_at": result.scanned_at,
        "image_id": result.image_id,
        "findings": [_serialize_finding(f) for f in result.findings],
    }


@router.get("/containers/{name}/scan", dependencies=[Depends(require_permission("scan_containers"))])
def get_scan(name: str) -> Any:
    image_id = get_image_id(name)
    if not image_id:
        return {"ok": False, "message": "Container not found or not running."}

    store = ManifestStore()
    config = load_config()
    cached = store.trivy_cache_get(image_id, cache_ttl_minutes=config.trivy.cache_ttl_minutes)
    if cached is None:
        return {"ok": False, "message": "No scan cached for this container."}

    return {"ok": True, "result": _serialize_scan_result(cached)}


@router.post("/containers/{name}/scan", dependencies=[Depends(require_permission("scan_containers"))])
async def run_scan(name: str) -> Any:
    config = load_config()
    if not config.trivy.enabled:
        raise HTTPException(status_code=422, detail="Trivy scanning is not enabled. Set trivy.enabled=true in config.")

    image_id = get_image_id(name)
    if not image_id:
        raise HTTPException(status_code=404, detail="Container not found or not running.")

    store = ManifestStore()
    cached = store.trivy_cache_get(image_id, cache_ttl_minutes=config.trivy.cache_ttl_minutes)
    if cached is not None:
        await manager.broadcast("scan_complete", {"name": name, "result": _serialize_scan_result(cached)})
        return {"ok": True, "cached": True, "result": _serialize_scan_result(cached)}

    container = None
    discovery = await _discover_container(name, load_config())
    if discovery:
        container = discovery
    image_ref = container.image_ref if container else name

    await manager.broadcast("scan_started", {"name": name})

    try:
        result = await scan_image(image_ref, config.trivy)
    except TrivyNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if image_id and not result.error:
        store.trivy_cache_put(image_id, result)

    serialized = _serialize_scan_result(result)
    await manager.broadcast("scan_complete", {"name": name, "result": serialized})
    return {"ok": True, "cached": False, "result": serialized}


@router.delete("/containers/{name}/scan", dependencies=[Depends(require_permission("scan_containers"))])
def invalidate_scan(name: str) -> Any:
    image_id = get_image_id(name)
    if not image_id:
        raise HTTPException(status_code=404, detail="Container not found or not running.")

    store = ManifestStore()
    store.trivy_cache_invalidate(image_id)
    return {"ok": True, "message": "Scan cache cleared."}


async def _discover_container(name: str, config):
    from ...sources import discover_containers
    discovery = await discover_containers(config, source="local")
    for c in discovery.containers:
        if c.name == name:
            return c
    return None
