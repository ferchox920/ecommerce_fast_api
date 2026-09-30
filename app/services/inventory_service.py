from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import InventoryMovement, MovementKind
from app.models.product import ProductVariant
from app.models.purchase import PurchaseOrderLine
from app.schemas.inventory_replenishment import (
    ReplenishmentLine,
    ReplenishmentSuggestion,
    StockAlert,
)
from app.services.exceptions import (
    ConflictError,
    InsufficientReservationError,
    InsufficientStockError,
    InvalidQuantityError,
)

async def _locked_variant(db: AsyncSession, variant: ProductVariant) -> ProductVariant:
    """Reload the latest stock values while holding the row until transaction end."""
    current = await db.get(
        ProductVariant, variant.id, with_for_update=True, populate_existing=True
    )
    if current is None:
        raise InsufficientStockError("La variante ya no existe.")
    return current


async def _log_movement(
    db: AsyncSession,
    variant: ProductVariant,
    mtype: MovementKind,
    qty: int,
    reason: str | None,
    idempotency_key: str | None = None,
) -> None:
    movement = InventoryMovement(
        variant_id=variant.id,
        type=mtype,
        quantity=int(qty),
        reason=reason,
        idempotency_key=idempotency_key,
    )
    db.add(movement)
    await db.flush()


async def _log_and_add_movement(
    db: AsyncSession,
    variant: ProductVariant,
    mtype: MovementKind,
    qty: int,
    reason: str | None,
    idempotency_key: str | None = None,
) -> ProductVariant:
    """Helper para añadir la variante a la sesión y registrar el movimiento, sin commit."""
    db.add(variant)
    await db.flush([variant])
    await _log_movement(db, variant, mtype, qty, reason, idempotency_key)
    return variant


async def _already_applied(
    db: AsyncSession,
    variant: ProductVariant,
    kind: MovementKind,
    quantity: int,
    reason: str | None,
    idempotency_key: str | None,
) -> bool:
    if not idempotency_key:
        return False
    prior = await db.scalar(
        select(InventoryMovement).where(
            InventoryMovement.variant_id == variant.id,
            InventoryMovement.idempotency_key == idempotency_key,
        )
    )
    if prior is None:
        return False
    if prior.type != kind or prior.quantity != quantity or prior.reason != reason:
        raise ConflictError("Idempotency key was used for a different stock operation.")
    return True


async def _outstanding_order_reservation(
    db: AsyncSession, variant: ProductVariant, reason: str
) -> int:
    rows = await db.scalars(
        select(InventoryMovement).where(
            InventoryMovement.variant_id == variant.id,
            InventoryMovement.reason == reason,
            InventoryMovement.type.in_(
                [MovementKind.RESERVE, MovementKind.RELEASE, MovementKind.SALE]
            ),
        )
    )
    return sum(
        movement.quantity if movement.type == MovementKind.RESERVE else -movement.quantity
        for movement in rows
    )


async def receive_stock(
    db: AsyncSession,
    variant: ProductVariant,
    quantity: int,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> ProductVariant:
    if quantity <= 0:
        raise InvalidQuantityError("La cantidad debe ser mayor que 0.")
    variant = await _locked_variant(db, variant)
    if await _already_applied(db, variant, MovementKind.RECEIVE, quantity, reason, idempotency_key):
        return variant
    variant.stock_on_hand += quantity
    return await _log_and_add_movement(db, variant, MovementKind.RECEIVE, quantity, reason, idempotency_key)


async def adjust_stock(
    db: AsyncSession,
    variant: ProductVariant,
    quantity: int,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> ProductVariant:
    variant = await _locked_variant(db, variant)
    if await _already_applied(db, variant, MovementKind.ADJUST, quantity, reason, idempotency_key):
        return variant
    new_on_hand = variant.stock_on_hand + quantity
    if new_on_hand < 0:
        raise InsufficientStockError("El stock no puede quedar en negativo.")
    if new_on_hand < variant.stock_reserved:
        raise InsufficientStockError("El ajuste no puede consumir stock reservado.")
    variant.stock_on_hand = new_on_hand
    return await _log_and_add_movement(db, variant, MovementKind.ADJUST, quantity, reason, idempotency_key)


async def reserve_stock(
    db: AsyncSession,
    variant: ProductVariant,
    quantity: int,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> ProductVariant:
    if quantity <= 0:
        raise InvalidQuantityError("La cantidad debe ser mayor que 0.")
    variant = await _locked_variant(db, variant)
    if await _already_applied(db, variant, MovementKind.RESERVE, quantity, reason, idempotency_key):
        return variant
    if variant.stock_reserved + quantity > variant.stock_on_hand:
        raise InsufficientStockError("No hay stock disponible suficiente para reservar la cantidad solicitada.")
    variant.stock_reserved += quantity
    return await _log_and_add_movement(db, variant, MovementKind.RESERVE, quantity, reason, idempotency_key)


async def release_stock(
    db: AsyncSession,
    variant: ProductVariant,
    quantity: int,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> ProductVariant:
    if quantity <= 0:
        raise InvalidQuantityError("La cantidad debe ser mayor que 0.")
    variant = await _locked_variant(db, variant)
    if await _already_applied(db, variant, MovementKind.RELEASE, quantity, reason, idempotency_key):
        return variant
    if reason and reason.startswith("order:"):
        if quantity > await _outstanding_order_reservation(db, variant, reason):
            raise InsufficientReservationError("Order does not own this reservation.")
    if quantity > variant.stock_reserved:
        raise InsufficientReservationError("No se puede liberar más stock del que está reservado.")
    variant.stock_reserved -= quantity
    return await _log_and_add_movement(db, variant, MovementKind.RELEASE, quantity, reason, idempotency_key)


async def commit_sale(
    db: AsyncSession,
    variant: ProductVariant,
    quantity: int,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> ProductVariant:
    if quantity <= 0:
        raise InvalidQuantityError("La cantidad debe ser mayor que 0.")
    variant = await _locked_variant(db, variant)
    if await _already_applied(db, variant, MovementKind.SALE, quantity, reason, idempotency_key):
        return variant

    if quantity > variant.stock_on_hand:
        raise InsufficientStockError("No hay stock disponible suficiente para la venta.")

    if reason and reason.startswith("order:"):
        if quantity > await _outstanding_order_reservation(db, variant, reason):
            raise InsufficientReservationError("Order does not own this reservation.")
        consume_reserved = quantity
    else:
        if quantity > variant.stock_on_hand - variant.stock_reserved:
            raise InsufficientStockError("Reserved stock is not available for a direct sale.")
        consume_reserved = 0
    variant.stock_reserved -= consume_reserved
    variant.stock_on_hand -= quantity

    if variant.stock_on_hand < 0:
        raise InsufficientStockError("El stock no puede quedar en negativo.")

    return await _log_and_add_movement(db, variant, MovementKind.SALE, quantity, reason, idempotency_key)


async def list_movements(
    db: AsyncSession,
    variant: ProductVariant,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    stmt = (
        select(InventoryMovement)
        .where(InventoryMovement.variant_id == variant.id)
        .order_by(InventoryMovement.created_at.desc())
        .offset(int(offset))
        .limit(int(limit))
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "id": str(row.id),
            "type": row.type.value,
            "quantity": int(row.quantity),
            "reason": row.reason,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def _available(variant: ProductVariant) -> int:
    return int(variant.stock_on_hand) - int(variant.stock_reserved)


async def compute_stock_alerts(
    db: AsyncSession,
    supplier_id: uuid.UUID | str | None = None,
) -> list[StockAlert]:
    stmt = select(ProductVariant)
    if supplier_id:
        sid = uuid.UUID(str(supplier_id))
        stmt = stmt.where(ProductVariant.primary_supplier_id == sid)
    variants = (await db.execute(stmt)).scalars().all()

    alerts: list[StockAlert] = []
    for variant in variants:
        avail = _available(variant)
        if avail <= int(variant.reorder_point):
            missing = max(0, int(variant.reorder_point) - avail)
            alerts.append(
                StockAlert(
                    variant_id=variant.id,
                    available=avail,
                    reorder_point=int(variant.reorder_point),
                    missing=missing,
                )
            )
    return alerts


async def _get_last_unit_cost(db: AsyncSession, variant_id: uuid.UUID) -> float | None:
    stmt = (
        select(PurchaseOrderLine.unit_cost)
        .where(PurchaseOrderLine.variant_id == variant_id)
        .order_by(PurchaseOrderLine.id.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    return float(row[0]) if row else None


async def compute_replenishment_suggestion(
    db: AsyncSession,
    supplier_id: uuid.UUID | str | None = None,
) -> ReplenishmentSuggestion:
    alerts = await compute_stock_alerts(db, supplier_id)
    lines: list[ReplenishmentLine] = []

    for alert in alerts:
        variant = await db.get(ProductVariant, alert.variant_id)
        if not variant:
            continue
        suggested = max(1, max(alert.missing, int(variant.reorder_qty or 0)))
        last_cost = await _get_last_unit_cost(db, alert.variant_id)

        lines.append(
            ReplenishmentLine(
                variant_id=alert.variant_id,
                suggested_qty=suggested,
                reason=f"available({alert.available}) <= reorder_point({alert.reorder_point})",
                last_unit_cost=last_cost,
            )
        )

    return ReplenishmentSuggestion(
        supplier_id=uuid.UUID(str(supplier_id)) if supplier_id else None,
        lines=sorted(lines, key=lambda line: str(line.variant_id)),
    )
