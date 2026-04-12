from __future__ import annotations

import asyncio
from typing import Any, Dict, Set

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, event: Dict[str, Any]) -> None:
        stale: Set[WebSocket] = set()
        for ws in self._connections:
            try:
                await ws.send_json(event)
            except Exception:
                stale.add(ws)
        for ws in stale:
            self._connections.discard(ws)

    def broadcast_from_thread(self, event: Dict[str, Any]) -> None:
        if not self._loop:
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(event), self._loop)
