from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.notification_manager import manager as ws_manager
from app.db.session_async import get_async_db
from app.models.user import User

router = APIRouter(prefix="/notifications", tags=["notifications"])

logger = logging.getLogger("app.notifications.ws")


@router.websocket("/ws")
async def notifications_ws(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_db),
) -> None:
    logger.info(
        "WS HS incoming: path=%s client=%s",
        websocket.url.path,
        websocket.client,
    )

    async def deny(code: int, reason: str) -> None:
        logger.warning(
            "WS denying handshake: code=%s reason=%s client=%s", code, reason, websocket.client
        )
        await websocket.accept()
        await websocket.close(code=code, reason=reason)

    if not token:
        logger.warning("WS rejected: missing token from %s", websocket.client)
        await deny(4401, "unauthorized: missing token")
        return

    try:
        token_data = deps.decode_token_no_db(token)
    except Exception:
        logger.warning("WS rejected: invalid token from %s", websocket.client)
        await deny(4401, "unauthorized: invalid token")
        return

    if not token_data.sub:
        logger.warning("WS rejected: token without subject from %s", websocket.client)
        await deny(4401, "unauthorized: no subject")
        return

    user = await db.get(User, token_data.sub)
    if not user or not user.is_active:
        logger.warning("WS rejected: user %s inactive/missing", token_data.sub)
        await deny(4403, "forbidden: inactive user")
        return

    logger.info("WS accepted for user %s (%s)", user.id, websocket.client)
    await ws_manager.connect(user.id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("WS disconnected for user %s (%s)", user.id, websocket.client)
        await ws_manager.disconnect(user.id, websocket)
