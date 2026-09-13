"""Image pruning preview and execution endpoints."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ... import docker_client
from ...config import VALID_PRUNE_MODES
from ...prune import plan_prune, prune_all
from ..deps import get_config, get_store
from ..rate_limit import rate_limit
from ..security import require_permission
from ..ws import manager

router = APIRouter()
_mutate_limit = Depends(rate_limit(10, 60))


class PruneBody(BaseModel):
    mode: str | None = None
    keep_recent: int | None = None


def _require_enabled(config) -> None:
    if not config.prune.enabled:
        raise HTTPException(
            status_code=422,
            detail="Image pruning is not enabled. Set prune.enabled=true in config.",
        )


def _resolve_params(config, mode: str | None, keep_recent: int | None) -> tuple[str, int]:
    resolved_mode = mode if mode is not None else config.prune.mode
    if resolved_mode not in VALID_PRUNE_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {sorted(VALID_PRUNE_MODES)}")
    resolved_keep = keep_recent if keep_recent is not None else config.prune.keep_recent_per_repository
    if resolved_keep < 0:
        raise HTTPException(status_code=422, detail="keep_recent must be >= 0")
    return resolved_mode, resolved_keep


def _serialize_preview(preview) -> dict[str, Any]:
    return {
        "mode": preview.mode,
        "keep_recent": preview.keep_recent,
        "estimated_bytes": preview.estimated_bytes,
        "candidates": [asdict(candidate) for candidate in preview.candidates],
        "retained": [asdict(candidate) for candidate in preview.retained],
    }


@router.get("/prune/preview", dependencies=[Depends(require_permission("prune_images"))])
async def preview_prune() -> Any:
    """Return the dry-run preview without mutating anything."""
    config = get_config()
    _require_enabled(config)
    mode, keep_recent = _resolve_params(config, None, None)
    images = await asyncio.to_thread(docker_client.list_images)
    in_use = await asyncio.to_thread(docker_client.in_use_image_ids)
    preview = plan_prune(images, in_use, mode=mode, keep_recent=keep_recent)
    return {"ok": True, "preview": _serialize_preview(preview)}


@router.post("/prune/images", dependencies=[_mutate_limit, Depends(require_permission("prune_images"))])
async def prune_images(body: PruneBody | None = None) -> Any:
    """Prune images locally and on every enabled agent host, honouring the retention guard."""
    config = get_config()
    _require_enabled(config)
    store = get_store()
    mode, keep_recent = _resolve_params(
        config,
        body.mode if body is not None else None,
        body.keep_recent if body is not None else None,
    )

    try:
        result = await prune_all(
            config,
            mode=mode,
            keep_recent=keep_recent,
            store=store,
            broadcast=manager.broadcast,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "ok": True,
        "removed": result.removed,
        "failed": result.failed,
        "reclaimed_bytes": result.reclaimed_bytes,
    }
