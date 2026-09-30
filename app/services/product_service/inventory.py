# app/services/product_service/inventory.py
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.operations import refresh_async
from app.models.product import ProductVariant
from app.services import inventory_service
from app.services.exceptions import ServiceError


async def _run_inventory_action(
    db: AsyncSession,
    variant: ProductVariant,
    action: Callable[..., Awaitable[ProductVariant]],
    *args,
    idempotency_key: str | None = None,
) -> ProductVariant:
    try:
        await action(db, variant, *args, idempotency_key=idempotency_key)
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.detail) from exc

    await refresh_async(db, variant)
    return variant


async def receive_stock(db: AsyncSession, variant: ProductVariant, quantity: int, reason: str | None = None, idempotency_key: str | None = None) -> ProductVariant:
    return await _run_inventory_action(db, variant, inventory_service.receive_stock, quantity, reason, idempotency_key=idempotency_key)


async def adjust_stock(db: AsyncSession, variant: ProductVariant, quantity: int, reason: str | None = None, idempotency_key: str | None = None) -> ProductVariant:
    return await _run_inventory_action(db, variant, inventory_service.adjust_stock, quantity, reason, idempotency_key=idempotency_key)


async def reserve_stock(db: AsyncSession, variant: ProductVariant, quantity: int, reason: str | None = None, idempotency_key: str | None = None) -> ProductVariant:
    return await _run_inventory_action(db, variant, inventory_service.reserve_stock, quantity, reason, idempotency_key=idempotency_key)


async def release_stock(db: AsyncSession, variant: ProductVariant, quantity: int, reason: str | None = None, idempotency_key: str | None = None) -> ProductVariant:
    return await _run_inventory_action(db, variant, inventory_service.release_stock, quantity, reason, idempotency_key=idempotency_key)


async def commit_sale(db: AsyncSession, variant: ProductVariant, quantity: int, reason: str | None = None, idempotency_key: str | None = None) -> ProductVariant:
    return await _run_inventory_action(db, variant, inventory_service.commit_sale, quantity, reason, idempotency_key=idempotency_key)


async def list_movements(db: AsyncSession, variant: ProductVariant, limit: int = 50, offset: int = 0):
    return await inventory_service.list_movements(db, variant, limit, offset)
