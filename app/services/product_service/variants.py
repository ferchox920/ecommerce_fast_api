# app/services/product_service/variants.py
from typing import Union

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.operations import flush_async, refresh_async, rollback_async
from app.models.product import Product, ProductVariant
from app.services import inventory_service
from app.services.exceptions import ServiceError
from app.schemas.product import ProductVariantCreate, ProductVariantUpdate
from app.schemas.variant import VariantCreate, VariantUpdate
from .utils import as_uuid


async def list_variants_for_product(db: AsyncSession, product: Product) -> list[ProductVariant]:
    result = await db.execute(
        select(ProductVariant)
        .where(ProductVariant.product_id == product.id)
        .order_by(ProductVariant.size_label, ProductVariant.color_name)
    )
    return result.scalars().all()


async def add_variant(
    db: AsyncSession,
    product_id: str,
    data: Union[ProductVariantCreate, VariantCreate],
) -> ProductVariant:
    if isinstance(data, VariantCreate):
        payload_data = data.model_dump()
        data = ProductVariantCreate(**payload_data)

    if (
        data.stock_reserved is not None
        and data.stock_on_hand is not None
        and data.stock_reserved > data.stock_on_hand
    ):
        raise HTTPException(status_code=400, detail="stock_reserved no puede exceder stock_on_hand")

    payload = data.model_dump()
    initial_on_hand = payload.pop("stock_on_hand", 0) or 0
    initial_reserved = payload.pop("stock_reserved", 0) or 0
    payload["sku"] = payload["sku"].strip()
    if payload.get("barcode"):
        payload["barcode"] = payload["barcode"].strip()
    payload["size_label"] = payload["size_label"].strip()
    payload["color_name"] = payload["color_name"].strip()
    if payload.get("color_hex"):
        payload["color_hex"] = payload["color_hex"].strip()

    variant = ProductVariant(product_id=as_uuid(product_id, "product_id"), **payload)
    db.add(variant)
    try:
        await flush_async(db, variant)
        if initial_on_hand:
            await inventory_service.receive_stock(
                db, variant, initial_on_hand, reason="variant:initial"
            )
        if initial_reserved:
            await inventory_service.reserve_stock(
                db, variant, initial_reserved, reason="variant:initial"
            )
    except IntegrityError:
        await rollback_async(db)
        raise HTTPException(status_code=400, detail="SKU ya existe")

    await refresh_async(db, variant)
    return variant


async def update_variant(
    db: AsyncSession,
    variant: ProductVariant,
    changes: Union[ProductVariantUpdate, VariantUpdate],
) -> ProductVariant:
    if isinstance(changes, VariantUpdate):
        changes = ProductVariantUpdate(**changes.model_dump(exclude_unset=True))

    payload = changes.model_dump(exclude_unset=True)
    requested_on_hand = payload.pop("stock_on_hand", None)
    requested_reserved = payload.pop("stock_reserved", None)

    if requested_reserved is not None and requested_reserved != variant.stock_reserved:
        raise HTTPException(status_code=400, detail="Use stock reserve/release endpoints")
    if requested_on_hand is not None:
        await set_stock(db, variant, requested_on_hand, None)

    new_on_hand = variant.stock_on_hand
    new_reserved = variant.stock_reserved

    if new_on_hand is not None and new_on_hand < 0:
        raise HTTPException(status_code=400, detail="Stock no puede ser negativo")
    if new_reserved is not None and new_reserved < 0:
        raise HTTPException(status_code=400, detail="Stock no puede ser negativo")
    if new_reserved > new_on_hand:
        raise HTTPException(status_code=400, detail="stock_reserved no puede exceder stock_on_hand")

    for field, value in payload.items():
        setattr(variant, field, value)

    db.add(variant)
    try:
        await flush_async(db, variant)
    except IntegrityError:
        await rollback_async(db)
        raise HTTPException(status_code=400, detail="Violacion de integridad")

    await refresh_async(db, variant)
    return variant


async def get_variant(db: AsyncSession, variant_id: str) -> ProductVariant | None:
    return await db.get(ProductVariant, as_uuid(variant_id, "variant_id"))


async def delete_variant(db: AsyncSession, variant: ProductVariant) -> None:
    await db.delete(variant)
    await flush_async(db)


async def set_stock(
    db: AsyncSession,
    variant: ProductVariant,
    on_hand: int | None = None,
    reserved: int | None = None,
) -> ProductVariant:
    variant = await db.get(
        ProductVariant, variant.id, with_for_update=True, populate_existing=True
    )
    if reserved is not None and reserved != variant.stock_reserved:
        raise HTTPException(status_code=400, detail="Use stock reserve/release endpoints")
    if on_hand is not None:
        if on_hand < 0:
            raise HTTPException(status_code=400, detail="Stock no puede ser negativo")
        try:
            delta = on_hand - variant.stock_on_hand
            if delta:
                await inventory_service.adjust_stock(
                    db, variant, delta, reason="admin:set_stock"
                )
        except ServiceError as exc:
            raise HTTPException(status_code=400, detail=exc.detail) from exc

    db.add(variant)
    await flush_async(db, variant)
    await refresh_async(db, variant)
    return variant


async def create_variant(db: AsyncSession, product: Product, data: VariantCreate) -> ProductVariant:
    return await add_variant(db, str(product.id), data)
