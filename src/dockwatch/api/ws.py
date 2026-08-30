"""WebSocket connection manager and endpoint."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ..config import load_config
from ..db import ManifestStore
from .security import _verify_raw_cookie

router = APIRouter()


class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.append(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active:
            self.active.remove(websocket)

    async def broadcast(self, type_: str, payload: dict[str, Any]) -> None:
        message = json.dumps({"type": type_, "payload": payload})
        targets = list(self.active)
        results = await asyncio.gather(
            *[self._send(ws, message) for ws in targets],
            return_exceptions=True,
        )
        dead_ids = {id(ws) for ws, r in zip(targets, results) if isinstance(r, Exception)}
        self.active = [ws for ws in self.active if id(ws) not in dead_ids]

    async def _send(self, websocket: WebSocket, message: str) -> None:
        await websocket.send_text(message)


manager = ConnectionManager()


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    config = load_config()
    try:
        data = _verify_raw_cookie(websocket, config)
    except HTTPException:
        await websocket.close(code=1008)
        return

    user_id = data.get("uid")
    if user_id is None:
        await websocket.close(code=1008)
        return

    store = ManifestStore()
    user = store.get_user_by_id(user_id)
    if user is None:
        await websocket.close(code=1008)
        return
    if data.get("sv") != user.session_version:
        await websocket.close(code=1008)
        return
    role = store.get_role(user.role_name)
    if role is None:
        await websocket.close(code=1008)
        return

    if "view_containers" not in role.permissions:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)
