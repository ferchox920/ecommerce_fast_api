from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Security
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session_async import get_async_db
from app.models.user import User
from app.schemas.notification import NotificationRead, NotificationUpdate
from app.services import notification_service
from app.services.exceptions import ServiceError

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
async def list_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["users:me"]),
) -> list[NotificationRead]:
    notifications = await notification_service.list_notifications(db, current_user, limit, offset)
    return [NotificationRead.model_validate(n, from_attributes=True) for n in notifications]


@router.patch("/{notification_id}", response_model=NotificationRead)
async def mark_notification(
    notification_id: str,
    payload: NotificationUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["users:me"]),
) -> NotificationRead:
    try:
        notif = await notification_service.mark_read(db, notification_id, current_user, payload)
        await db.commit()
    except ServiceError:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise
    return NotificationRead.model_validate(notif, from_attributes=True)
