"""WebSocket connection manager and endpoint."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)
