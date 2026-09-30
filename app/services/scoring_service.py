"""Scoring layer for Rate View."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from math import exp
from typing import Dict
from uuid import UUID as UUIDType

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.operations import flush_async
from app.models.engagement import ProductEngagementDaily, ProductRanking
from app.services import catalog_client

POPULARITY_WEIGHT = settings.EXPOSURE_POPULARITY_WEIGHT
STRATEGIC_WEIGHT = settings.EXPOSURE_STRATEGIC_WEIGHT
WINDOW_DAYS = settings.SCORING_WINDOW_DAYS
HALF_LIFE_DAYS = settings.SCORING_HALF_LIFE_DAYS
FRESHNESS_HALF_LIFE = settings.SCORING_FRESHNESS_HALF_LIFE


class ScoringResult(Dict[str, float]):
    ...


def _decay_factor(age_days: float) -> float:
    if HALF_LIFE_DAYS <= 0:
        return 1.0
    return exp(-age_days * 0.693 / HALF_LIFE_DAYS)


def _freshness_factor(age_days: float) -> float:
    if FRESHNESS_HALF_LIFE <= 0:
        return 1.0
    return exp(-age_days * 0.693 / FRESHNESS_HALF_LIFE)


async def _load_engagement(db: AsyncSession, window_days: int):
    today = datetime.now(timezone.utc).date()
    start_date = today - timedelta(days=window_days - 1)
    result = await db.execute(
        select(ProductEngagementDaily).where(ProductEngagementDaily.date >= start_date)
    )
    records = result.scalars().all()
    grouped: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "views": 0.0,
            "clicks": 0.0,
            "carts": 0.0,
            "purchases": 0.0,
            "revenue": Decimal("0"),
            "freshness": 0.0,
            "latest_age": float("inf"),
        }
    )

    for record in records:
        age_days = float((today - record.date).days)
        decay = _decay_factor(age_days)
        key = str(record.product_id)
        data = grouped[key]
        data["views"] += record.views * decay
        data["clicks"] += record.clicks * decay
        data["carts"] += record.carts * decay
        data["purchases"] += record.purchases * decay
        data["revenue"] += Decimal(record.revenue or 0) * Decimal(decay)
        data["freshness"] = max(data["freshness"], _freshness_factor(age_days))
        data["latest_age"] = min(data["latest_age"], age_days)
    return grouped


async def run_scoring(db: AsyncSession, window_days: int = WINDOW_DAYS) -> dict:
    engagements = await _load_engagement(db, window_days)
    if not engagements:
        return {"updated": [], "count": 0, "window_days": window_days}

    popularity_values = []
    profit_values = []
    cold_raw_values = []

    product_metrics = {}
    for product_id, metrics in engagements.items():
        product_uuid = UUIDType(product_id)
        popularity = (
            metrics["views"] * 0.2
            + metrics["clicks"] * 0.3
            + metrics["carts"] * 0.5
            + metrics["purchases"] * 1.2
        )

        fin = await catalog_client.get_financial_metrics(db, product_uuid)
        margin = fin.get("margin", Decimal("0"))
        stock = fin.get("stock_on_hand", 0)

        total_views = metrics["views"] or 1.0
        conversion = metrics["purchases"] / total_views
        profit_score_raw = float((margin or 0) * Decimal(conversion))

        cold_raw = (1 - min(1.0, popularity / (total_views + 1e-6))) + (stock / 50.0)

        product_metrics[product_id] = {
            "uuid": product_uuid,
            "popularity_raw": max(0.0, popularity),
            "profit_raw": max(0.0, profit_score_raw),
            "cold_raw": max(0.0, cold_raw),
            "freshness": metrics["freshness"],
        }
        popularity_values.append(product_metrics[product_id]["popularity_raw"])
        profit_values.append(product_metrics[product_id]["profit_raw"])
        cold_raw_values.append(product_metrics[product_id]["cold_raw"])

    max_popularity = max(popularity_values) or 1.0
    max_profit = max(profit_values) or 1.0
    max_cold = max(cold_raw_values) or 1.0

    updated = []
    now = datetime.now(timezone.utc)
    for product_id, values in product_metrics.items():
        product_uuid = values["uuid"]
        popularity_score = round(values["popularity_raw"] / max_popularity, 4)
        profit_score = round(values["profit_raw"] / max_profit, 4)
        cold_score = round(min(1.0, values["cold_raw"] / max_cold), 4)
        freshness_score = round(values["freshness"], 4)

        strategic_component = (cold_score + freshness_score) / 2
        exposure_score = round(
            max(0.0, min(1.0, POPULARITY_WEIGHT * popularity_score + STRATEGIC_WEIGHT * strategic_component)),
            4,
        )

        ranking = await db.get(ProductRanking, product_uuid)
        if not ranking:
            ranking = ProductRanking(product_id=product_uuid)
            db.add(ranking)

        ranking.popularity_score = Decimal(str(popularity_score))
        ranking.cold_score = Decimal(str(cold_score))
        ranking.profit_score = Decimal(str(profit_score))
        ranking.freshness_score = Decimal(str(freshness_score))
        ranking.exposure_score = Decimal(str(exposure_score))
        ranking.updated_at = now
        updated.append(str(product_uuid))

    await flush_async(db)
    return {"updated": updated, "count": len(updated), "window_days": window_days}


async def get_latest_rankings(db: AsyncSession, limit: int = 20):
    stmt = select(ProductRanking).order_by(ProductRanking.exposure_score.desc()).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()
