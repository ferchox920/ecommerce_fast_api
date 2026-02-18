from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.operations import flush_async, refresh_async
from app.models.promotion import Promotion, PromotionStatus, PromotionType
from app.schemas.promotion import PromotionCreate, PromotionUpdate
from app.services import notification_service
from app.services.event_bus import emit_promotion_event


def _ensure_aware(value: datetime | None, fallback: datetime) -> datetime:
    if value is None:
        return fallback
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _is_time_active(promotion: Promotion, now: datetime) -> bool:
    start_at = _ensure_aware(promotion.start_at, datetime.min.replace(tzinfo=timezone.utc))
    end_at = _ensure_aware(promotion.end_at, datetime.max.replace(tzinfo=timezone.utc))
    return start_at <= now <= end_at


async def create_promotion(db: AsyncSession, payload: PromotionCreate) -> Promotion:
    promotion = Promotion(
        name=payload.name,
        description=payload.description,
        type=PromotionType(payload.type),
        scope=payload.scope or "global",
        criteria_json=payload.criteria or {},
        benefits_json=payload.benefits or {},
        start_at=payload.start_at,
        end_at=payload.end_at,
        status=PromotionStatus.draft,
    )
    db.add(promotion)
    await flush_async(db, promotion)
    await refresh_async(db, promotion)
    return promotion


async def list_promotions(db: AsyncSession, status_filter: Optional[str] = None):
    stmt = select(Promotion)
    if status_filter:
        stmt = stmt.where(Promotion.status == PromotionStatus(status_filter))
    result = await db.execute(stmt.order_by(Promotion.start_at.desc()))
    return result.scalars().all()


async def list_active_promotions(db: AsyncSession):
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Promotion).where(Promotion.status == PromotionStatus.active)
    )
    promotions = result.scalars().all()
    return [promo for promo in promotions if _is_time_active(promo, now)]


async def get_promotion(db: AsyncSession, promotion_id: UUID) -> Promotion:
    promotion = await db.get(Promotion, promotion_id)
    if not promotion:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Promotion not found")
    return promotion


async def update_promotion(
    db: AsyncSession, promotion_id: UUID, payload: PromotionUpdate
) -> Promotion:
    promotion = await get_promotion(db, promotion_id)
    if payload.name is not None:
        promotion.name = payload.name
    if payload.description is not None:
        promotion.description = payload.description
    if payload.scope is not None:
        promotion.scope = payload.scope
    if payload.criteria is not None:
        promotion.criteria_json = payload.criteria
    if payload.benefits is not None:
        promotion.benefits_json = payload.benefits
    if payload.start_at is not None:
        promotion.start_at = payload.start_at
    if payload.end_at is not None:
        promotion.end_at = payload.end_at
    if payload.status is not None:
        promotion.status = PromotionStatus(payload.status)
    db.add(promotion)
    await flush_async(db, promotion)
    await refresh_async(db, promotion)
    return promotion


async def activate_promotion(db: AsyncSession, promotion_id: UUID) -> Promotion:
    promotion = await get_promotion(db, promotion_id)
    promotion.status = PromotionStatus.active
    db.add(promotion)
    await flush_async(db, promotion)
    await refresh_async(db, promotion)
    await notification_service.notify_new_promotion(db, promotion)
    emit_promotion_event(
        "promotion_start",
        {
            "promotion_id": str(promotion.id),
            "name": promotion.name,
            "start_at": promotion.start_at.isoformat(),
            "end_at": promotion.end_at.isoformat(),
        },
    )
    return promotion


async def deactivate_promotion(db: AsyncSession, promotion_id: UUID) -> Promotion:
    promotion = await get_promotion(db, promotion_id)
    promotion.status = PromotionStatus.expired
    db.add(promotion)
    await flush_async(db, promotion)
    await refresh_async(db, promotion)
    emit_promotion_event(
        "promotion_end",
        {
            "promotion_id": str(promotion.id),
            "name": promotion.name,
        },
    )
    return promotion


def evaluate_eligibility(
    promotion: Promotion,
    *,
    user_id: Optional[str] = None,
    loyalty_level: Optional[str] = None,
    category_id: Optional[UUID] = None,
    product_id: Optional[UUID] = None,
    order_total: Optional[float] = None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    now = datetime.now(timezone.utc)
    if promotion.start_at > now:
        reasons.append("not_started")
    if promotion.end_at < now:
        reasons.append("expired")
    if reasons:
        return False, reasons

    criteria = promotion.criteria_json or {}

    if promotion.scope == "category":
        required_categories = {str(cid) for cid in criteria.get("category_ids", [])}
        if required_categories and str(category_id) not in required_categories:
            return False, ["category_mismatch"]
    if promotion.scope == "product":
        required_products = {str(pid) for pid in criteria.get("product_ids", [])}
        if required_products and str(product_id) not in required_products:
            return False, ["product_scope_mismatch"]

    if promotion.type == PromotionType.customer:
        targeted = {pc.customer_id for pc in promotion.customers}
        if targeted and (not user_id or user_id not in targeted):
            return False, ["not_targeted"]

    loyalty_levels = criteria.get("loyalty_levels")
    if loyalty_levels and loyalty_level not in loyalty_levels:
        return False, ["loyalty_level_required"]

    min_order_total = criteria.get("min_order_total")
    if min_order_total and (order_total or 0) < min_order_total:
        return False, ["order_total_too_low"]

    return True, ["eligible"]
