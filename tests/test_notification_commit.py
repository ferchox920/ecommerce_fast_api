import asyncio

import pytest

from app.schemas.notification import NotificationCreate
from app.services import notification_service


@pytest.mark.asyncio
async def test_notification_delivery_waits_for_commit(async_db_session, normal_user, monkeypatch):
    delivered = []

    async def fake_send(user_id, payload):
        delivered.append((user_id, payload["title"]))

    monkeypatch.setattr(notification_service.ws_manager, "send_to_user", fake_send)
    data = NotificationCreate(
        user_id=normal_user.id,
        type="generic",
        title="Rolled back",
        message="No delivery",
    )
    await notification_service.create_notification(async_db_session, data)
    await asyncio.sleep(0)
    assert delivered == []
    await async_db_session.rollback()
    await asyncio.sleep(0)
    assert delivered == []

    data.title = "Committed"
    await notification_service.create_notification(async_db_session, data)
    await async_db_session.commit()
    await asyncio.sleep(0)
    assert delivered == [(str(normal_user.id), "Committed")]
