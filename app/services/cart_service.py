from __future__ import annotations

import uuid
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.cart import Cart, CartItem, CartStatus
from app.models.product import ProductVariant
from app.schemas.cart import CartCreate, CartItemCreate, CartItemUpdate
from app.services.pricing import get_variant_effective_price


def _as_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except Exception as exc:
        raise HTTPException(422, f"Invalid UUID for {field}") from exc


def _recompute_totals(cart: Cart) -> None:
    subtotal = sum(float(item.line_total) for item in cart.items)
    cart.subtotal_amount = subtotal
    cart.total_amount = subtotal - float(cart.discount_amount or 0)


async def _refresh_cart(db: AsyncSession, cart: Cart) -> None:
    await db.refresh(cart)
    await db.refresh(cart, attribute_names=["items"])


async def get_active_cart(
    db: AsyncSession,
    *,
    user_id: str | None = None,
    guest_token: str | None = None,
) -> Cart | None:
    stmt = select(Cart).options(selectinload(Cart.items)).where(Cart.status == CartStatus.active)
    if user_id:
        stmt = stmt.where(Cart.user_id == user_id)
    elif guest_token:
        stmt = stmt.where(Cart.guest_token == guest_token)
    else:
        return None

    stmt = stmt.order_by(Cart.created_at.desc()).limit(1)
    result = await db.execute(stmt)
    cart = result.scalars().first()
    if cart:
        await _refresh_cart(db, cart)
    return cart


async def create_cart(
    db: AsyncSession,
    *,
    payload: CartCreate,
    user_id: str | None = None,
) -> Cart:
    # Authenticated users should never reuse the guest token field to avoid UNIQUE conflicts.
    guest_token = None if user_id else payload.guest_token

    if not user_id and not guest_token:
        guest_token = str(uuid.uuid4())

    cart = Cart(
        user_id=user_id,
        guest_token=guest_token,
        currency=payload.currency,
        status=CartStatus.active,
        subtotal_amount=0,
        discount_amount=0,
        total_amount=0,
    )
    db.add(cart)
    await db.flush()
    await _refresh_cart(db, cart)
    return cart


def _get_item(cart: Cart, item_id: uuid.UUID) -> CartItem | None:
    for item in cart.items:
        if item.id == item_id:
            return item
    return None


async def _ensure_cart_loaded(db: AsyncSession, cart: Cart) -> None:
    await _refresh_cart(db, cart)


async def add_item(
    db: AsyncSession,
    *,
    cart: Cart,
    item_payload: CartItemCreate,
) -> Cart:
    await _ensure_cart_loaded(db, cart)

    variant = await db.get(ProductVariant, _as_uuid(item_payload.variant_id, "variant_id"))
    if not variant:
        raise HTTPException(404, "Variant not found")

    unit_price = await get_variant_effective_price(db, variant)

    existing = next((i for i in cart.items if i.variant_id == variant.id), None)
    if existing:
        existing.quantity += item_payload.quantity
        existing.line_total = float(existing.unit_price) * existing.quantity
    else:
        new_item = CartItem(
            cart=cart,
            variant_id=variant.id,
            quantity=item_payload.quantity,
            unit_price=unit_price,
            line_total=unit_price * item_payload.quantity,
        )
        db.add(new_item)

    _recompute_totals(cart)
    db.add(cart)
    await db.flush()
    await _refresh_cart(db, cart)
    return cart


async def update_item(
    db: AsyncSession,
    *,
    cart: Cart,
    item_id: str,
    payload: CartItemUpdate,
) -> Cart:
    await _ensure_cart_loaded(db, cart)

    item_uuid = _as_uuid(item_id, "item_id")
    item = _get_item(cart, item_uuid)
    if not item:
        raise HTTPException(404, "Cart item not found")

    item.quantity = payload.quantity
    item.line_total = float(item.unit_price) * item.quantity

    _recompute_totals(cart)
    db.add(cart)
    await db.flush()
    await _refresh_cart(db, cart)
    return cart


async def remove_item(
    db: AsyncSession,
    *,
    cart: Cart,
    item_id: str,
) -> Cart:
    await _ensure_cart_loaded(db, cart)

    item_uuid = _as_uuid(item_id, "item_id")
    item = _get_item(cart, item_uuid)
    if not item:
        raise HTTPException(404, "Cart item not found")

    cart.items.remove(item)
    await db.flush()
    _recompute_totals(cart)

    db.add(cart)
    await db.flush()
    await _refresh_cart(db, cart)
    return cart
