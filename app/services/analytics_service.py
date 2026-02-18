from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.engagement import ProductEngagementDaily, ProductRanking
from app.models.loyalty import LoyaltyProfile
from app.models.order import Order
from app.models.product import Product, ProductVariant
from app.models.promotion import Promotion, PromotionStatus
from app.services import (
    inventory_service,
    product_question_service,
    promotion_service,
    report_service,
)


async def overview(db: AsyncSession, days: int = 7) -> dict:
    start = datetime.now(timezone.utc) - timedelta(days=days)
    total_revenue_result = await db.execute(
        select(func.coalesce(func.sum(ProductEngagementDaily.revenue), 0)).where(
            ProductEngagementDaily.date >= start.date()
        )
    )
    total_revenue = total_revenue_result.scalar_one()
    total_orders = (await db.execute(select(func.count(Order.id)))).scalar_one()
    pop_mix = await _exposure_mix(db)
    loyalty_distribution = await _loyalty_distribution(db)
    avg_order_value = float(total_revenue or 0) / total_orders if total_orders else 0.0

    return {
        "period": {
            "start": start.isoformat(),
            "end": datetime.now(timezone.utc).isoformat(),
        },
        "kpis": {
            "total_revenue": float(total_revenue or 0),
            "orders": total_orders,
            "average_order_value": round(avg_order_value, 2),
            "average_exposure_mix": pop_mix,
            "loyalty_distribution": loyalty_distribution,
        },
    }


async def dashboard(db: AsyncSession, days: int = 7) -> dict:
    overview_data = await overview(db, days)
    engagement = await _engagement_snapshot(db, days)
    sales_report = await report_service.get_sales_report(db, days)
    inventory_report = await report_service.get_inventory_value_report(db)
    order_breakdown = await _orders_breakdown(db)
    stock_alerts = await _stock_alerts_summary(db, limit=5)
    pending_questions = await product_question_service.list_pending_questions_for_admin(db, limit=5)
    promotions_info = await _promotions_summary(db)

    return {
        "period": overview_data["period"],
        "kpis": overview_data["kpis"],
        "sales": {
            "summary": sales_report.sales_summary.model_dump(),
            "top_sellers": [seller.model_dump() for seller in sales_report.top_sellers[:5]],
        },
        "inventory": {
            "total_estimated_value": inventory_report.total_estimated_value,
            "total_units": inventory_report.total_units,
            "items": [item.model_dump() for item in inventory_report.items[:5]],
        },
        "engagement": engagement,
        "operations": {
            **order_breakdown,
            "stock_alerts": stock_alerts,
            "pending_questions": [question.model_dump() for question in pending_questions],
        },
        "promotions": promotions_info,
    }


async def _exposure_mix(db: AsyncSession) -> dict:
    stmt = select(ProductRanking)
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return {"popular": 0.0, "strategic": 0.0}
    popular = sum(float(r.popularity_score) for r in rows)
    strategic = sum(float(r.cold_score) for r in rows)
    total = popular + strategic
    if total == 0:
        return {"popular": 0.0, "strategic": 0.0}
    return {
        "popular": round(popular / total, 3),
        "strategic": round(strategic / total, 3),
    }


async def _loyalty_distribution(db: AsyncSession) -> dict:
    stmt = select(LoyaltyProfile.level, func.count(LoyaltyProfile.customer_id)).group_by(LoyaltyProfile.level)
    rows = await db.execute(stmt)
    return {row.level: row[1] for row in rows.all()}


async def promotions_dashboard(db: AsyncSession) -> dict:
    rows = (await db.execute(select(Promotion))).scalars().all()
    return {
        "count": len(rows),
        "active": [str(p.id) for p in rows if p.status == PromotionStatus.active],
    }


async def _orders_breakdown(db: AsyncSession) -> dict:
    orders_by_status = await db.execute(
        select(Order.status, func.count(Order.id)).group_by(Order.status)
    )
    payments_by_status = await db.execute(
        select(Order.payment_status, func.count(Order.id)).group_by(Order.payment_status)
    )
    shipments_by_status = await db.execute(
        select(Order.shipping_status, func.count(Order.id)).group_by(Order.shipping_status)
    )

    def _normalize(rows: Iterable[tuple]) -> dict:
        normalized: dict[str, int] = {}
        for status, count in rows:
            key = status.value if hasattr(status, "value") else str(status)
            normalized[key] = int(count or 0)
        return normalized

    return {
        "orders_by_status": _normalize(orders_by_status.all()),
        "payments_by_status": _normalize(payments_by_status.all()),
        "shipments_by_status": _normalize(shipments_by_status.all()),
    }


async def _engagement_snapshot(db: AsyncSession, days: int) -> dict:
    start = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(
            ProductEngagementDaily.date,
            func.sum(ProductEngagementDaily.views).label("views"),
            func.sum(ProductEngagementDaily.clicks).label("clicks"),
            func.sum(ProductEngagementDaily.carts).label("carts"),
            func.sum(ProductEngagementDaily.purchases).label("purchases"),
            func.sum(ProductEngagementDaily.revenue).label("revenue"),
        )
        .where(ProductEngagementDaily.date >= start.date())
        .group_by(ProductEngagementDaily.date)
        .order_by(ProductEngagementDaily.date)
    )
    rows = await db.execute(stmt)
    totals = {"views": 0, "clicks": 0, "carts": 0, "purchases": 0, "revenue": 0.0}
    trend: list[dict] = []
    for row in rows.all():
        date = row.date.isoformat()
        views = int(row.views or 0)
        clicks = int(row.clicks or 0)
        carts = int(row.carts or 0)
        purchases = int(row.purchases or 0)
        revenue = float(row.revenue or 0)

        totals["views"] += views
        totals["clicks"] += clicks
        totals["carts"] += carts
        totals["purchases"] += purchases
        totals["revenue"] += revenue

        trend.append(
            {
                "date": date,
                "views": views,
                "clicks": clicks,
                "carts": carts,
                "purchases": purchases,
                "revenue": revenue,
            }
        )

    conversion_rate = (totals["purchases"] / totals["views"]) if totals["views"] else 0.0
    cart_rate = (totals["carts"] / totals["views"]) if totals["views"] else 0.0
    return {
        "totals": {
            **totals,
            "conversion_rate": round(conversion_rate, 4),
            "cart_rate": round(cart_rate, 4),
        },
        "trend": trend,
    }


async def _stock_alerts_summary(db: AsyncSession, limit: int = 5) -> list[dict]:
    alerts = await inventory_service.compute_stock_alerts(db)
    if not alerts:
        return []
    sorted_alerts = sorted(alerts, key=lambda alert: alert.available)
    top_alerts = sorted_alerts[:limit]
    variant_ids = [alert.variant_id for alert in top_alerts]
    stmt = (
        select(
            ProductVariant.id.label("variant_id"),
            ProductVariant.sku,
            Product.title.label("product_title"),
            ProductVariant.stock_on_hand,
        )
        .join(Product, ProductVariant.product_id == Product.id)
        .where(ProductVariant.id.in_(variant_ids))
    )
    rows = await db.execute(stmt)
    variant_lookup = {row.variant_id: row for row in rows.all()}
    serialized = []
    for alert in top_alerts:
        meta = variant_lookup.get(alert.variant_id)
        serialized.append(
            {
                "variant_id": str(alert.variant_id),
                "sku": getattr(meta, "sku", None),
                "product_title": getattr(meta, "product_title", None),
                "available": alert.available,
                "reorder_point": alert.reorder_point,
                "missing": alert.missing,
            }
        )
    return serialized


async def _promotions_summary(db: AsyncSession) -> dict:
    active_promotions = await promotion_service.list_active_promotions(db)

    return {
        "active_count": len(active_promotions),
        "active": [
            {
                "id": str(promo.id),
                "name": promo.name,
                "scope": promo.scope,
                "status": promo.status.value if hasattr(promo.status, "value") else promo.status,
                "starts_at": promo.start_at.isoformat() if promo.start_at else None,
                "ends_at": promo.end_at.isoformat() if promo.end_at else None,
            }
            for promo in active_promotions
        ],
    }
