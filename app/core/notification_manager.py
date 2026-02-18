from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Dict, Set
import logging

from fastapi import WebSocket


class NotificationManager:
    def __init__(self) -> None:
        self._connections: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._logger = logging.getLogger("app.notifications.manager")
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[user_id].add(websocket)
            self._logger.debug(
                "Registered WS connection for user %s (%s active)", user_id, len(self._connections[user_id])
            )

    async def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._connections.get(user_id)
            if not conns:
                return
            conns.discard(websocket)
            if not conns:
                self._connections.pop(user_id, None)
                self._logger.debug("Removed last WS connection for user %s", user_id)
            else:
                self._logger.debug(
                    "WS connection removed for user %s (%s remaining)", user_id, len(conns)
                )

    async def send_to_user(self, user_id: str, payload: dict) -> None:
        async with self._lock:
            conns = list(self._connections.get(user_id, set()))
        for conn in conns:
            try:
                await conn.send_json(payload)
            except Exception:
                self._logger.exception("Failed to send WS payload to user %s; dropping connection", user_id)
                await self.disconnect(user_id, conn)


manager = NotificationManager()
