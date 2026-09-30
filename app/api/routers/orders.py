from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Response, Security, status
from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_user
from app.db.operations import commit_async
from app.db.session_async import get_async_db
from app.models.user import User
from app.schemas.order import OrderCreate, OrderLineCreate, OrderRead, ShipmentCreate
from app.models.cart import Cart, CartStatus
from app.models.order import Order, OrderStatus, PaymentStatus, ShippingStatus
from app.services import cart_service, order_service
from app.services.exceptions import ServiceError


class OrderFromCartPayload(BaseModel):
    guest_token: Optional[str] = None
    promotion_id: UUID | None = None


router = APIRouter(prefix="/orders", tags=["orders"])


def _require_owner(order, current_user: User) -> None:
    if not current_user.is_superuser and str(order.user_id) != str(current_user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")


@router.get("", response_model=List[OrderRead])
async def list_orders(
    status_filter: Optional[OrderStatus] = Query(default=None, alias="status"),
    payment_status: Optional[PaymentStatus] = Query(default=None),
    shipping_status: Optional[ShippingStatus] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["orders:read"]),
):
    if not current_user.is_superuser:
        if user_id and user_id != str(current_user.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to list another user's orders")
        user_id = str(current_user.id)
    return await order_service.list_orders(
        db,
        status_filter=status_filter,
        payment_status=payment_status,
        shipping_status=shipping_status,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=120),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["orders:write"]),
):
    if current_user.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin users cannot create customer orders")
    try:
        order, created = await order_service.create_order(
            db, current_user_id=current_user.id, payload=payload,
            idempotency_key=idempotency_key,
        )
        if not created:
            response.status_code = status.HTTP_200_OK
        await commit_async(db)
    except ServiceError:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise
    return order


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["orders:read"]),
):
    order = await order_service.get_order(db, str(order_id))
    _require_owner(order, current_user)
    return order


@router.post("/from-cart", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def create_order_from_cart(
    payload: OrderFromCartPayload,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    if current_user and current_user.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin users cannot create customer orders")
    cart = await cart_service.get_active_cart(
        db,
        user_id=current_user.id if current_user else None,
        guest_token=payload.guest_token,
    )
    if not cart:
        if not current_user and not payload.guest_token:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Cart not found")
        converted = (
            select(Order)
            .join(Cart, Order.source_cart_id == Cart.id)
            .where(Cart.status == CartStatus.converted)
            .order_by(Cart.created_at.desc())
            .limit(1)
        )
        if current_user:
            converted = converted.where(Cart.user_id == current_user.id)
        else:
            converted = converted.where(Cart.guest_token == payload.guest_token)
        previous = await db.scalar(converted)
        if previous is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Cart not found")
        if previous.applied_promotion_id != payload.promotion_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "Checkout parameters changed on retry")
        response.status_code = status.HTTP_200_OK
        return await order_service.get_order(db, str(previous.id))
    try:
        order = await order_service.create_order_from_cart(db, cart, promotion_id=payload.promotion_id)
        await commit_async(db)
    except ServiceError:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise
    return order


@router.post("/{order_id}/lines", response_model=OrderRead)
async def add_line(
    order_id: UUID,
    payload: OrderLineCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["orders:write"]),
):
    order = await order_service.get_order(db, str(order_id))
    _require_owner(order, current_user)
    try:
        updated = await order_service.add_line(db, order, payload)
        await commit_async(db)
    except ServiceError:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise
    return updated


@router.post("/{order_id}/pay", response_model=OrderRead)
async def pay_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["orders:write"]),
):
    if not current_user.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Manual payment confirmation is admin only")
    order = await order_service.get_order(db, str(order_id))
    _require_owner(order, current_user)
    try:
        updated = await order_service.set_status_paid(db, order)
        await commit_async(db)
    except ServiceError:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise
    return updated


@router.post("/{order_id}/cancel", response_model=OrderRead)
async def cancel_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["orders:write"]),
):
    order = await order_service.get_order(db, str(order_id))
    _require_owner(order, current_user)
    try:
        updated = await order_service.cancel_order(db, order)
        await commit_async(db)
    except ServiceError:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise
    return updated


@router.post("/{order_id}/fulfill", response_model=OrderRead)
async def fulfill_order(
    order_id: UUID,
    payload: Optional[ShipmentCreate] = Body(default=None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["orders:write"]),
):
    order = await order_service.get_order(db, str(order_id))
    if not current_user.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    try:
        updated = await order_service.fulfill_order(db, order, payload)
        await commit_async(db)
    except ServiceError:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise
    return updated
