"""WebSocket connection manager for live dashboard updates."""

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.append(websocket)
        logger.info("WebSocket connected (%s clients)", len(self.active))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active:
            self.active.remove(websocket)
        logger.info("WebSocket disconnected (%s clients)", len(self.active))

    async def broadcast(self, payload: dict[str, Any]) -> None:
        if not self.active:
            return
        dead: list[WebSocket] = []
        for ws in self.active:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def broadcast_threadsafe(self, payload: dict[str, Any]) -> None:
        if not self._loop or not self.active:
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(payload), self._loop)


ws_manager = ConnectionManager()
