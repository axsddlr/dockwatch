"""FastAPI application factory."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from .deps import get_results_cache, get_results_lock, get_store
from .routes import auth, containers, environments, settings, trivy, users
from .security import require_auth, require_permission
from .ws import router as ws_router
from .. import __version__
from ..config import CONFIG_PATH, migrate_auth_config_to_users, migrate_pinned_ignored_to_db, load_config


def _find_frontend_dist() -> Path:
    candidates = [
        Path("/app/frontend/dist"),
        Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[1]


def _is_reserved_backend_path(path: str) -> bool:
    parts = path.lstrip("/").split("/")
    if not parts or not parts[0]:
        return False
    return parts[0] in {"api", "ws", "debug", "health"}


def _frontend_file_path(dist_path: Path, requested_path: str) -> Path:
    root = dist_path.resolve()
    candidate = (dist_path / requested_path).resolve()
    try:
        candidate.relative_to(os.path.realpath(str(root)))
    except ValueError as exc:
        raise HTTPException(status_code=404) from exc
    if not candidate.is_file():
        raise HTTPException(status_code=404)
    return candidate


_BACKUP_DIR = Path.home() / ".config" / "dockwatch" / "backups"
_BACKUP_INTERVAL_SECONDS = 60 * 60 * 24
_BACKUP_KEEP = 7


def _prune_old_backups(logger) -> None:
    backups = sorted(_BACKUP_DIR.glob("manifests-*.db"))
    for stale in backups[:-_BACKUP_KEEP]:
        try:
            stale.unlink()
        except OSError:
            logger.warning("failed to prune old backup %s", stale)


@asynccontextmanager
async def _lifespan(app: FastAPI):  # noqa: ANN202, ARG001
    import asyncio
    import logging
    import random
    from datetime import datetime, timezone
    from ..registry import check_all, record_digest_drift_events
    from ..sources import discover_containers
    from .serializers import serialize_update_results
    from .routes.containers import _merge_check_results
    from .ws import manager

    logger = logging.getLogger("dockwatch")

    store = get_store()
    config = load_config()
    migrate_pinned_ignored_to_db(CONFIG_PATH, store)
    migrate_auth_config_to_users(config, store)

    async def _scheduled_check() -> None:
        while True:
            try:
                interval = float(config.schedule_interval_seconds)
                jitter = random.uniform(0, float(config.schedule_jitter_seconds))
                await asyncio.sleep(interval + jitter)

                cache = get_results_cache()
                lock = get_results_lock()
                if lock.locked():
                    continue

                async with lock:
                    discovery = await discover_containers(config, source="all")
                    if not discovery.containers:
                        continue
                    results = await check_all(
                        discovery.containers,
                        config,
                        store=store,
                        max_concurrency=config.max_concurrent_checks,
                    )
                    record_digest_drift_events(results, store)
                    merged = _merge_check_results(cache, results, source="all")
                    cache[:] = merged
                    serialized = serialize_update_results(results)
                    try:
                        await manager.broadcast("check_complete", {"results": serialized})
                    except Exception:
                        pass
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("scheduled check failed")

    async def _scheduled_backup() -> None:
        while True:
            try:
                await asyncio.sleep(_BACKUP_INTERVAL_SECONDS)
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                dest = _BACKUP_DIR / f"manifests-{stamp}.db"
                await asyncio.to_thread(store.backup_to, dest)
                _prune_old_backups(logger)
                logger.info("database backup written to %s", dest)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("scheduled backup failed")

    tasks = [asyncio.create_task(_scheduled_check()), asyncio.create_task(_scheduled_backup())]
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    app = FastAPI(title="dockwatch", version=__version__, lifespan=_lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/version", dependencies=[Depends(require_auth)])
    async def api_version() -> dict[str, str]:
        return {"version": __version__}

    app.include_router(auth.router, prefix="/api")
    app.include_router(containers.router, prefix="/api")
    app.include_router(settings.router, prefix="/api")
    app.include_router(environments.router, prefix="/api")
    app.include_router(trivy.router, prefix="/api")
    app.include_router(users.router, prefix="/api")
    app.include_router(ws_router)

    dist_path = _find_frontend_dist()
    _mounted = dist_path.exists()

    @app.get("/debug/dist", dependencies=[Depends(require_permission("manage_settings"))])
    async def debug_dist() -> dict:
        return {
            "resolved_path": str(dist_path),
            "exists": dist_path.exists(),
            "mounted": _mounted,
            "contents": [p.name for p in dist_path.iterdir()][:50] if dist_path.exists() else [],
        }

    if _mounted:
        assets_path = dist_path / "assets"
        if assets_path.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def frontend(full_path: str):  # noqa: ANN202
            if _is_reserved_backend_path(full_path):
                raise HTTPException(status_code=404)
            if Path(full_path).suffix:
                return FileResponse(_frontend_file_path(dist_path, full_path))
            return FileResponse(_frontend_file_path(dist_path, "index.html"))

    return app
