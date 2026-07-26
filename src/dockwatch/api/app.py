"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from .deps import get_store
from .routes import auth, containers, environments, settings, trivy, users
from .security import require_permission
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
    normalized = path.lstrip("/")
    if normalized in {"api", "ws", "debug", "health"}:
        return True
    return normalized.startswith(("api/", "ws/", "debug/", "health/"))


def _frontend_file_path(dist_path: Path, requested_path: str) -> Path:
    root = dist_path.resolve()
    candidate = (dist_path / requested_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404) from exc
    if not candidate.is_file():
        raise HTTPException(status_code=404)
    return candidate


@asynccontextmanager
async def _lifespan(app: FastAPI):  # noqa: ANN202, ARG001
    store = get_store()
    config = load_config()
    migrate_pinned_ignored_to_db(CONFIG_PATH, store)
    migrate_auth_config_to_users(config, store)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="dockwatch", version=__version__, lifespan=_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

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
