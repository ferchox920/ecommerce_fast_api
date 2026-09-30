from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, Security, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.operations import commit_async
from app.db.session_async import get_async_db
from app.models.user import User
from app.schemas.order import PaymentAuditRead, PaymentRead, PaymentRefundCreate
from app.services import order_service, payment_service

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/orders/{order_id}", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
async def create_payment_for_order(
    order_id: UUID,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["orders:write"]),
):
    if current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin users cannot create customer payments",
        )

    order = await order_service.get_order(db, str(order_id))
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if not order.user_id or str(order.user_id) != str(current_user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to pay this order")

    payment, created = await payment_service.create_payment_preference(
        db,
        order,
        idempotency_key=idempotency_key,
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    await commit_async(db)
    await db.refresh(payment)
    return payment


@router.post("/mercado-pago/webhook", status_code=status.HTTP_200_OK)
async def mercado_pago_webhook(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    payload = await request.json()
    try:
        result = await payment_service.handle_mercado_pago_webhook(
            db,
            payload,
            signature_header=request.headers.get("x-signature"),
            request_id=request.headers.get("x-request-id"),
            resource_id=request.query_params.get("data.id"),
        )
        await commit_async(db)
    except Exception:
        await db.rollback()
        raise
    return result


@router.post("/{payment_id}/refund", response_model=PaymentRead)
async def refund_payment(
    payment_id: UUID,
    payload: PaymentRefundCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=120),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["admin"]),
):
    payment = await payment_service.get_payment(db, str(payment_id))
    refunded = await payment_service.refund_payment(
        db,
        payment,
        amount=payload.amount,
        reason=payload.reason,
        restock_items=payload.restock_items,
        idempotency_key=idempotency_key,
    )
    await commit_async(db)
    await db.refresh(refunded)
    return refunded


@router.get("/{payment_id}/audit", response_model=PaymentAuditRead)
async def payment_audit(
    payment_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["admin"]),
):
    payment = await payment_service.get_payment(db, str(payment_id))
    return await payment_service.get_payment_audit(db, payment)
