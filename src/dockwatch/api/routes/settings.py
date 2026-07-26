"""Settings management endpoints."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...config import load_config, save_config
from ...integrations import PortainerClient, PortainerError
from ...models import ContainerInfo, RegistryType, UpdateResult
from ...notifiers import send_configured_notifications
from ..deps import get_config, get_store
from ..security import require_permission
from ..serializers import deserialize_settings, serialize_settings

router = APIRouter()

# PUT handlers run in FastAPI's threadpool; serialize the config
# read-modify-write cycle so concurrent saves cannot drop each other's changes.
_settings_write_lock = threading.Lock()


@router.get("/settings", dependencies=[Depends(require_permission("manage_settings"))])
def get_settings() -> Any:
    config = get_config()
    store = get_store()
    return serialize_settings(config, store)


@router.put("/settings", dependencies=[Depends(require_permission("manage_settings"))])
def put_settings(body: dict[str, Any]) -> Any:
    with _settings_write_lock:
        existing = load_config()
        store = get_store()
        try:
            updated = deserialize_settings(body, existing, store)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"invalid settings value: {exc}") from exc
        save_config(updated)
    return serialize_settings(updated, store)


@router.post("/settings/test-notification", dependencies=[Depends(require_permission("manage_settings"))])
async def test_notification() -> Any:
    config = load_config()
    test_result = UpdateResult(
        container_info=ContainerInfo(
            name="dockwatch-test",
            container_id="test",
            image_ref="ghcr.io/example/app:1.0.0",
            registry=RegistryType.GHCR,
            namespace="example",
            image_name="app",
            current_tag="1.0.0",
        ),
        latest_tag="1.1.0",
        is_outdated=True,
        status=None,
        event="update",
        deployed_tag="1.0.0",
        remote_tag="1.1.0",
        comparison_basis="version",
        comparison_reason="remote version 1.1.0 is newer than deployed 1.0.0",
    )
    errors = await send_configured_notifications([test_result], config, apply_filters=False)
    if errors:
        raise HTTPException(status_code=502, detail="; ".join(errors))
    return {"ok": True, "message": "Test notification sent."}


@router.post("/settings/test-portainer", dependencies=[Depends(require_permission("manage_settings"))])
def test_portainer(body: dict[str, str]) -> Any:
    url = body.get("url", "").strip()
    api_key = body.get("api_key", "").strip()
    if not url or not api_key:
        raise HTTPException(status_code=422, detail="Both 'url' and 'api_key' are required.")

    try:
        client = PortainerClient(base_url=url, api_key=api_key)
    except PortainerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        environments = asyncio.run(client.test_connection())
    except PortainerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"ok": True, "environments": [{"id": e.id, "name": e.name} for e in environments]}
