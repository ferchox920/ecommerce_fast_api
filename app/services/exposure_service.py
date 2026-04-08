from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.metrics import record_exposure_metrics
from app.models.engagement import ExposureSlot, ProductRanking
from app.models.product import Product
from app.models.promotion import Promotion, PromotionStatus, PromotionType
from app.schemas.exposure import ExposureResponse, ExposureItem
from app.services import catalog_client
from app.services.exposure_cache import ExposureCache

POPULARITY_WEIGHT = getattr(settings, "EXPOSURE_POPULARITY_WEIGHT", 0.7)
STRATEGIC_WEIGHT = getattr(settings, "EXPOSURE_STRATEGIC_WEIGHT", 0.3)
CATEGORY_CAP = getattr(settings, "EXPOSURE_CATEGORY_CAP", 3)
COLD_THRESHOLD = getattr(settings, "EXPOSURE_COLD_THRESHOLD", 0.6)
STOCK_THRESHOLD = getattr(settings, "EXPOSURE_STOCK_THRESHOLD", 15)
FRESH_THRESHOLD = getattr(settings, "EXPOSURE_FRESHNESS_THRESHOLD", 0.7)
CACHE_TTL = getattr(settings, "EXPOSURE_CACHE_TTL", 600)

_cache = ExposureCache(ttl_seconds=CACHE_TTL)


# INTEGRATION(AB): feature flag 'exposure_weights' por cohorte.
def _cache_key(context: str, user_id: Optional[str], category_id: Optional[UUID]) -> str:
    cat_component = str(category_id) if category_id else "all"
    return f"{context}:{user_id or 'anon'}:{cat_component}"


def _slot_context(context: str, category_id: Optional[UUID]) -> str:
    cat_component = str(category_id) if category_id else "all"
    return f"{context}|{cat_component}"


def _load_previous_mix(slot: Optional[ExposureSlot]) -> set[str]:
    if not slot or not slot.payload_json:
        return set()
    try:
        return {item.get("product_id") for item in slot.payload_json.get("mix", []) if item.get("product_id")}
    except Exception:
        return set()


async def _select_rankings(db: AsyncSession, category_id: Optional[UUID], limit: int) -> Sequence[tuple[ProductRanking, Product]]:
    stmt = (
        select(ProductRanking, Product)
        .join(Product, ProductRanking.product_id == Product.id)
        .order_by(ProductRanking.exposure_score.desc())
        .limit(limit)
    )
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    result = await db.execute(stmt)
    return result.all()


def _promotion_lookup(promotions: Sequence[Promotion]) -> dict[str, Promotion]:
    promo_by_product: dict[str, Promotion] = {}
    for promo in promotions:
        if promo.type == PromotionType.product:
            for pp in promo.products:
                promo_by_product[str(pp.product_id)] = promo
    return promo_by_product


def _promotion_for_product(promotions: Sequence[Promotion], product: Product, promotion_map: dict[str, Promotion]) -> Optional[Promotion]:
    product_key = str(product.id)
    if product_key in promotion_map:
        return promotion_map[product_key]
    for promo in promotions:
        if promo.type == PromotionType.category:
            category_ids = promo.criteria_json.get("category_ids") if promo.criteria_json else None
            if not category_ids or str(product.category_id) in set(category_ids):
                return promo
        elif promo.type == PromotionType.customer:
            # handled later based on user context
            continue
    return None


def _build_item(product_id: UUID, ranking: ProductRanking, stock: int, promotion: Optional[Promotion], cold_boost: bool) -> ExposureItem:
    reasons: list[str] = []
    badges: list[str] = []

    # INTEGRATION: Personalización usará badges para renders en /exposure.
    popularity_score = float(ranking.popularity_score)
    cold_score = float(ranking.cold_score)
    freshness_score = float(ranking.freshness_score)

    if popularity_score >= 0.5:
        reasons.append(f"popular_{int(POPULARITY_WEIGHT * 100)}")
    if stock >= STOCK_THRESHOLD:
        reasons.append("in_stock")
    if cold_boost and cold_score >= COLD_THRESHOLD:
        reasons.append(f"cold_boost_{int(STRATEGIC_WEIGHT * 100)}")
    if freshness_score >= FRESH_THRESHOLD:
        reasons.append("fresh")

    if promotion:
        badges.append("promo")
        reasons.append(f"promo:{promotion.id}")

    return ExposureItem(product_id=product_id, reason=reasons, badges=badges)


async def build_exposure(
    db: AsyncSession,
    context: str,
    user_id: Optional[str],
    category_id: Optional[UUID] = None,
    limit: int = 12,
) -> dict:
    slot_context = _slot_context(context, category_id)

    result_promos = await db.execute(
        select(Promotion)
        .options(selectinload(Promotion.products))
        .where(Promotion.status == PromotionStatus.active)
    )
    active_promos = result_promos.scalars().all()
    promo_by_product = _promotion_lookup(active_promos)

    rankings = await _select_rankings(db, category_id, limit * 4)
    previous_slot_result = await db.execute(
        select(ExposureSlot).where(ExposureSlot.context == slot_context).where(ExposureSlot.user_id == user_id)
    )
    previous_slot = previous_slot_result.scalar_one_or_none()
    previous_products = _load_previous_mix(previous_slot)

        # INTEGRATION: Admin puede forzar pinning/unpinning temporal (flag en DB).
    category_counts: dict[str, int] = defaultdict(int)
    selected_items: list[ExposureItem] = []
    selected_ids: set[str] = set()
    skipped_for_repeat: list[tuple[ProductRanking, Product]] = []

    cold_candidates: list[tuple[ProductRanking, Product]] = []

    for ranking, product in rankings:
        product_id_str = str(ranking.product_id)
        product_category = str(product.category_id)

        if CATEGORY_CAP and category_counts[product_category] >= CATEGORY_CAP:
            continue

        stock_info = await catalog_client.get_financial_metrics(db, product.id)
        stock = stock_info.get("stock_on_hand", 0)

        if product_id_str in previous_products:
            skipped_for_repeat.append((ranking, product))
            cold_candidates.append((ranking, product))
            continue

        cold_candidates.append((ranking, product))

        promotion = promo_by_product.get(product_id_str) or _promotion_for_product(active_promos, product, promo_by_product)

        item = _build_item(product.id, ranking, stock, promotion, cold_boost=False)
        selected_items.append(item)
        selected_ids.add(product_id_str)
        category_counts[product_category] += 1

        if len(selected_items) >= limit:
            break

    if len(selected_items) < limit and skipped_for_repeat:
        for ranking, product in skipped_for_repeat:
            if len(selected_items) >= limit:
                break
            product_id_str = str(ranking.product_id)
            product_category = str(product.category_id)
            if CATEGORY_CAP and category_counts[product_category] >= CATEGORY_CAP:
                continue
            stock_info = await catalog_client.get_financial_metrics(db, product.id)
            stock = stock_info.get("stock_on_hand", 0)
            promotion = promo_by_product.get(product_id_str) or _promotion_for_product(active_promos, product, promo_by_product)
            item = _build_item(product.id, ranking, stock, promotion, cold_boost=False)
            selected_items.append(item)
            selected_ids.add(product_id_str)
            category_counts[product_category] += 1

    # Cold boost pass
    cold_items = sorted(cold_candidates, key=lambda rp: float(rp[0].cold_score), reverse=True)
    for ranking, product in cold_items:
        if len(selected_items) >= limit:
            break
        product_id_str = str(ranking.product_id)
        if product_id_str in selected_ids:
            continue
        if float(ranking.cold_score) < COLD_THRESHOLD:
            continue
        product_category = str(product.category_id)
        if CATEGORY_CAP and category_counts[product_category] >= CATEGORY_CAP:
            continue
        stock_info = await catalog_client.get_financial_metrics(db, product.id)
        stock = stock_info.get("stock_on_hand", 0)
        if stock < STOCK_THRESHOLD:
            continue
        promotion = promo_by_product.get(product_id_str) or _promotion_for_product(active_promos, product, promo_by_product)
        item = _build_item(product.id, ranking, stock, promotion, cold_boost=True)
        selected_items.append(item)
        selected_ids.add(product_id_str)
        category_counts[product_category] += 1

    generated_at = datetime.now(timezone.utc)
    expires_at = generated_at + timedelta(seconds=CACHE_TTL)

    payload = {
        "context": context,
        "user_id": user_id,
        "category_id": str(category_id) if category_id else None,
        "generated_at": generated_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "mix": [item.model_dump(mode="json") for item in selected_items[:limit]],
    }

    cache_key = _cache_key(context, user_id, category_id)
    _cache.set(cache_key, payload, expires_at.timestamp())

    if previous_slot:
        previous_slot.payload_json = payload
        previous_slot.generated_at = generated_at
        previous_slot.expires_at = expires_at
    else:
        db.add(
            ExposureSlot(
                context=slot_context,
                user_id=user_id,
                payload_json=payload,
                generated_at=generated_at,
                expires_at=expires_at,
            )
        )

    await db.commit()
    return payload


async def get_exposure(
    db: AsyncSession,
    context: str,
    user_id: Optional[str],
    category_id: Optional[UUID] = None,
    limit: int = 12,
) -> ExposureResponse:
    started_at = datetime.now(timezone.utc)
    cache_key = _cache_key(context, user_id, category_id)
    cached = _cache.get(cache_key)
    if cached:
        response = ExposureResponse(**cached)
        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
        record_exposure_metrics(
            context=context,
            cache_hit=True,
            items_served=len(response.mix),
            elapsed=elapsed,
        )
        return response
    payload = await build_exposure(db, context, user_id, category_id, limit)
    response = ExposureResponse(**payload)
    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    record_exposure_metrics(
        context=context,
        cache_hit=False,
        items_served=len(response.mix),
        elapsed=elapsed,
    )
    return response


async def clear_cache(db: AsyncSession, context: Optional[str] = None, user_id: Optional[str] = None, category_id: Optional[UUID] = None) -> None:
    if context:
        cache_key = _cache_key(context, user_id, category_id)
        _cache.clear(cache_key)
        slot_context = _slot_context(context, category_id)
        await db.execute(
            delete(ExposureSlot)
            .where(ExposureSlot.context == slot_context)
            .where(ExposureSlot.user_id == user_id)
        )
        await db.commit()
    else:
        _cache.clear()
        await db.execute(delete(ExposureSlot))
        await db.commit()



