"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .routes import containers, environments, settings, trivy
from .ws import router as ws_router
from .. import __version__

def _find_frontend_dist() -> Path:
    candidates = [
        Path("/app/frontend/dist"),
        Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[1]


class SpaStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope) -> object:  # noqa: ANN001
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or not _is_frontend_route(path, scope):
                raise
            return await super().get_response("index.html", scope)


def _is_frontend_route(path: str, scope) -> bool:  # noqa: ANN001
    request_path = str(scope.get("path", path)).lstrip("/")
    if request_path in {"api", "ws", "debug", "health"}:
        return False
    if request_path.startswith(("api/", "ws/", "debug/", "health/")):
        return False
    return Path(request_path or path.lstrip("/")).suffix == ""


def create_app() -> FastAPI:
    app = FastAPI(title="dockwatch", version=__version__)

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

    app.include_router(containers.router, prefix="/api")
    app.include_router(settings.router, prefix="/api")
    app.include_router(environments.router, prefix="/api")
    app.include_router(trivy.router, prefix="/api")
    app.include_router(ws_router)

    dist_path = _find_frontend_dist()
    _mounted = dist_path.exists()

    @app.get("/debug/dist")
    async def debug_dist() -> dict:
        return {
            "resolved_path": str(dist_path),
            "exists": dist_path.exists(),
            "mounted": _mounted,
            "contents": [p.name for p in dist_path.iterdir()][:50] if dist_path.exists() else [],
        }

    if _mounted:
        app.mount("/", SpaStaticFiles(directory=str(dist_path), html=True), name="static")

    return app
