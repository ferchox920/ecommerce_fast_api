from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.notification_manager import manager as ws_manager
from app.db.operations import flush_async, refresh_async
from app.models.notification import Notification, NotificationType
from app.models.order import Order
from app.models.product_question import ProductQuestion, ProductAnswer
from app.models.user import User
from app.schemas.notification import NotificationCreate, NotificationUpdate
from app.services import email_service
from app.services.exceptions import DomainValidationError, ResourceNotFoundError


@event.listens_for(Session, "after_commit")
def _deliver_committed_notifications(session: Session) -> None:
    for user_id, payload in session.info.pop("pending_notifications", []):
        asyncio.get_running_loop().create_task(ws_manager.send_to_user(user_id, payload))
    for to_email, subject, message in session.info.pop("pending_notification_emails", []):
        email_service.send_notification_email(
            to_email=to_email, subject=subject, message=message
        )


@event.listens_for(Session, "after_rollback")
def _discard_rolled_back_notifications(session: Session) -> None:
    session.info.pop("pending_notifications", None)
    session.info.pop("pending_notification_emails", None)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def list_notifications(db: AsyncSession, user: User, limit: int = 50, offset: int = 0) -> list[Notification]:
    stmt = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def _get_user(db: AsyncSession, user_id: str | uuid.UUID) -> User | None:
    """
    Devuelve el usuario por PK. Si el PK del modelo User es UUID,
    convertimos el valor entrante a UUID de forma segura.
    """
    pk = user_id
    try:
        pk = uuid.UUID(str(user_id))
    except Exception:
        # Si el PK no es UUID en tu modelo, se intentará con el valor original
        pass
    return await db.get(User, pk)


async def create_notification(
    db: AsyncSession,
    data: NotificationCreate,
    *,
    send_email: bool = False,
) -> Notification:
    notification = Notification(
        user_id=uuid.UUID(str(data.user_id)),
        type=NotificationType(data.type),
        title=data.title,
        message=data.message,
        payload=data.payload,
    )
    db.add(notification)
    await flush_async(db, notification)
    await refresh_async(db, notification)

    payload = {
        "id": str(notification.id),
        "type": notification.type.value,
        "title": notification.title,
        "message": notification.message,
        "payload": notification.payload,
        "created_at": notification.created_at.isoformat(),
    }

    # user_id para websockets es string
    db.sync_session.info.setdefault("pending_notifications", []).append(
        (str(notification.user_id), payload)
    )

    if send_email:
        user = await _get_user(db, notification.user_id)
        if user and user.email:
            db.sync_session.info.setdefault("pending_notification_emails", []).append(
                (user.email, notification.title, notification.message)
            )

    return notification


async def mark_read(
    db: AsyncSession,
    notification_id: str,
    user: User,
    payload: NotificationUpdate,
) -> Notification:
    try:
        notif_uuid = uuid.UUID(str(notification_id))
    except Exception as exc:
        raise DomainValidationError("Invalid notification id") from exc

    notification = await db.get(Notification, notif_uuid)
    if not notification or notification.user_id != user.id:
        raise ResourceNotFoundError("Notification not found")

    notification.is_read = payload.is_read
    notification.read_at = _utcnow() if payload.is_read else None
    db.add(notification)
    await flush_async(db, notification)
    await refresh_async(db, notification)
    return notification


async def _iter_admins(db: AsyncSession) -> Iterable[User]:
    # ojo: en tu proyecto usás is_superuser; respetamos eso
    stmt = select(User).where(User.is_superuser == True)  # noqa: E712
    result = await db.execute(stmt)
    return result.scalars().all()


async def notify_admin_new_question(db: AsyncSession, question: ProductQuestion) -> None:
    admins = await _iter_admins(db)
    title = "Nueva pregunta de producto"
    message = f"Pregunta sobre producto {question.product_id}: {question.content[:140]}"
    for admin in admins:
        data = NotificationCreate(
            user_id=str(admin.id),
            type=NotificationType.product_question.value,
            title=title,
            message=message,
            payload={"question_id": str(question.id), "product_id": str(question.product_id)},
        )
        await create_notification(db, data)


async def notify_question_answer(db: AsyncSession, question: ProductQuestion, answer: ProductAnswer) -> None:
    if not question.user_id:
        return
    data = NotificationCreate(
        user_id=str(question.user_id),
        type=NotificationType.product_answer.value,
        title="Respuesta a tu pregunta",
        message=answer.content[:200],
        payload={
            "question_id": str(question.id),
            "answer_id": str(answer.id),
            "product_id": str(question.product_id),
        },
    )
    await create_notification(db, data, send_email=True)


async def notify_order_status(db: AsyncSession, order: Order, title: str, message: str) -> None:
    if not order.user_id:
        return
    data = NotificationCreate(
        user_id=str(order.user_id),
        type=NotificationType.order_status.value,
        title=title,
        message=message,
        payload={
            "order_id": str(order.id),
            "status": order.status.value,
            "payment_status": order.payment_status.value,
            "shipping_status": order.shipping_status.value,
        },
    )
    await create_notification(db, data, send_email=True)


async def notify_new_order(db: AsyncSession, order: Order) -> None:
    admins = await _iter_admins(db)
    title = "Nueva orden creada"
    message = f"Orden {order.id} por total {order.total_amount}"
    for admin in admins:
        data = NotificationCreate(
            user_id=str(admin.id),
            type=NotificationType.new_order.value,
            title=title,
            message=message,
            payload={"order_id": str(order.id)},
        )
        await create_notification(db, data)


async def notify_new_promotion(db: AsyncSession, promotion) -> None:
    admins = await _iter_admins(db)
    title = "Promoción activada"
    message = f"{promotion.name} activo hasta {promotion.end_at.date()}"
    for admin in admins:
        data = NotificationCreate(
            user_id=str(admin.id),
            type=NotificationType.promotion.value,
            title=title,
            message=message,
            payload={"promotion_id": str(promotion.id)},
        )
        await create_notification(db, data)


async def notify_loyalty_upgrade(db: AsyncSession, profile, previous_level: str) -> None:
    data = NotificationCreate(
        user_id=str(profile.customer_id),
        type=NotificationType.loyalty.value,
        title="Subiste de nivel",
        message=f"Bienvenido al nivel {profile.level} (antes {previous_level}).",
        payload={
            "level": profile.level,
            "previous_level": previous_level,
            "points": profile.points,
        },
    )
    await create_notification(db, data, send_email=True)
