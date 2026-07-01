"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
    if dist_path.exists():
        app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="static")

    return app
