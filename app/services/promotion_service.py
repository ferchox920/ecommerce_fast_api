from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.operations import flush_async, refresh_async
from app.models.promotion import Promotion, PromotionCustomer, PromotionStatus, PromotionType
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


def _extract_string_list(criteria: dict, key: str) -> list[str]:
    raw = criteria.get(key, [])
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _resolve_scope(promotion_type: PromotionType, scope: Optional[str]) -> str:
    if scope is None or not str(scope).strip():
        if promotion_type == PromotionType.product:
            return "product"
        if promotion_type == PromotionType.category:
            return "category"
        return "global"

    normalized_scope = str(scope).strip().lower()
    allowed_scopes = {"global", "product", "category"}
    if normalized_scope not in allowed_scopes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="scope must be one of: global, product, category",
        )
    if promotion_type == PromotionType.product and normalized_scope != "product":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="product promotions must use scope 'product'",
        )
    if promotion_type == PromotionType.category and normalized_scope != "category":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="category promotions must use scope 'category'",
        )
    return normalized_scope


def _validate_promotion_constraints(
    *,
    promotion_type: PromotionType,
    scope: str,
    criteria: dict,
    start_at: datetime,
    end_at: datetime,
) -> None:
    if end_at <= start_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_at must be greater than start_at",
        )

    if scope == "product" and not _extract_string_list(criteria, "product_ids"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="scope 'product' requires at least one product_id in criteria.product_ids",
        )

    if scope == "category" and not _extract_string_list(criteria, "category_ids"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="scope 'category' requires at least one category_id in criteria.category_ids",
        )

    if promotion_type == PromotionType.customer:
        customer_ids = _extract_string_list(criteria, "customer_ids")
        if not customer_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="customer promotions require customer_ids",
            )
        if _extract_string_list(criteria, "loyalty_levels"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="customer promotions cannot include loyalty_levels; use type 'loyalty'",
            )

    if promotion_type == PromotionType.loyalty:
        loyalty_levels = _extract_string_list(criteria, "loyalty_levels")
        if not loyalty_levels:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="loyalty promotions require loyalty_levels",
            )
        if _extract_string_list(criteria, "customer_ids"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="loyalty promotions cannot include customer_ids; use type 'customer'",
            )


async def create_promotion(db: AsyncSession, payload: PromotionCreate) -> Promotion:
    criteria = payload.criteria or {}
    promotion_type = PromotionType(payload.type)
    scope = _resolve_scope(promotion_type, payload.scope)
    _validate_promotion_constraints(
        promotion_type=promotion_type,
        scope=scope,
        criteria=criteria,
        start_at=payload.start_at,
        end_at=payload.end_at,
    )
    raw_customer_ids = (
        criteria.get("customer_ids", [])
        if isinstance(criteria, dict) and promotion_type == PromotionType.customer
        else []
    )
    customer_ids = (
        list({str(customer_id) for customer_id in raw_customer_ids if str(customer_id).strip()})
        if isinstance(raw_customer_ids, list)
        else []
    )

    promotion = Promotion(
        name=payload.name,
        description=payload.description,
        type=promotion_type,
        scope=scope,
        criteria_json=criteria,
        benefits_json=payload.benefits or {},
        start_at=payload.start_at,
        end_at=payload.end_at,
        status=PromotionStatus.draft,
    )
    db.add(promotion)
    await flush_async(db, promotion)
    if customer_ids:
        for customer_id in customer_ids:
            db.add(PromotionCustomer(promotion_id=promotion.id, customer_id=customer_id))
        await flush_async(db)
    await refresh_async(db, promotion)
    return promotion


async def list_promotions(db: AsyncSession, status_filter: Optional[PromotionStatus] = None):
    stmt = select(Promotion)
    if status_filter:
        stmt = stmt.where(Promotion.status == status_filter)
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
    next_scope = _resolve_scope(promotion.type, payload.scope) if payload.scope is not None else promotion.scope
    next_criteria = payload.criteria if payload.criteria is not None else (promotion.criteria_json or {})
    next_start_at = payload.start_at if payload.start_at is not None else promotion.start_at
    next_end_at = payload.end_at if payload.end_at is not None else promotion.end_at
    _validate_promotion_constraints(
        promotion_type=promotion.type,
        scope=next_scope,
        criteria=next_criteria,
        start_at=next_start_at,
        end_at=next_end_at,
    )

    if payload.name is not None:
        promotion.name = payload.name
    if payload.description is not None:
        promotion.description = payload.description
    promotion.scope = next_scope
    if payload.criteria is not None:
        promotion.criteria_json = payload.criteria
        raw_customer_ids = (
            payload.criteria.get("customer_ids", [])
            if isinstance(payload.criteria, dict) and promotion.type == PromotionType.customer
            else []
        )
        customer_ids = (
            list(
                {
                    str(customer_id)
                    for customer_id in raw_customer_ids
                    if str(customer_id).strip()
                }
            )
            if isinstance(raw_customer_ids, list)
            else []
        )
        promotion.customers = [
            PromotionCustomer(promotion_id=promotion.id, customer_id=customer_id)
            for customer_id in customer_ids
        ]
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
        if not targeted:
            targeted = {str(cid) for cid in criteria.get("customer_ids", []) if str(cid).strip()}
        if targeted and (not user_id or user_id not in targeted):
            return False, ["not_targeted"]

    if promotion.type == PromotionType.loyalty:
        loyalty_levels = {str(level) for level in criteria.get("loyalty_levels", []) if str(level).strip()}
        if loyalty_levels and (not loyalty_level or loyalty_level not in loyalty_levels):
            return False, ["loyalty_level_required"]

    min_order_total = criteria.get("min_order_total")
    if min_order_total and (order_total or 0) < min_order_total:
        return False, ["order_total_too_low"]

    return True, ["eligible"]
