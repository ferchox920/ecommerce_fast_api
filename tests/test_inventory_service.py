# tests/test_inventory_service.py
import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

# No importamos más SessionLocal, usaremos la fixture de pytest
from app.models.product import Category, Brand, Product, ProductVariant
from app.services import inventory_service
from app.models.supplier import Supplier
# Importamos las nuevas excepciones para las pruebas
from app.services.exceptions import (
    InvalidQuantityError,
    InsufficientStockError,
)


# ---------- helpers (no necesitan cambios) ----------

async def _mk_variant(
    db: AsyncSession,
    *,
    on_hand=0,
    reserved=0,
    reorder_point=0,
    reorder_qty=0,
    primary_supplier_id=None,
) -> ProductVariant:
    cat = Category(name=f"Cat-{uuid.uuid4()}", slug=f"cat-{uuid.uuid4()}")
    brand = Brand(name=f"Brand-{uuid.uuid4()}", slug=f"brand-{uuid.uuid4()}")
    db.add_all([cat, brand])
    await db.flush()

    p = Product(
        title=f"Prod-{uuid.uuid4()}",
        slug=f"prod-{uuid.uuid4()}",
        price=100,
        currency="ARS",
        category_id=cat.id,
        brand_id=brand.id,
        active=True,
    )
    db.add(p)
    await db.flush()

    v = ProductVariant(
        product_id=p.id,
        sku=f"SKU-{uuid.uuid4()}",
        size_label="M",
        color_name="Black",
        stock_on_hand=on_hand,
        stock_reserved=reserved,
        reorder_point=reorder_point,
        reorder_qty=reorder_qty,
        primary_supplier_id=primary_supplier_id,
        active=True,
    )
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return v


# ---------- tests (Modificados para usar la fixture db_session) ----------

@pytest.mark.asyncio
async def test_receive_and_list_movements(async_db_session: AsyncSession):
    v = await _mk_variant(async_db_session, on_hand=0)
    await inventory_service.receive_stock(async_db_session, v, 5, reason="ingreso OC")
    await async_db_session.commit()
    await async_db_session.refresh(v)
    assert v.stock_on_hand == 5

    rows = await inventory_service.list_movements(async_db_session, v, limit=10, offset=0)
    assert len(rows) >= 1
    last = rows[0]
    assert last["type"] == "receive"
    assert last["quantity"] == 5
    assert last["reason"] == "ingreso OC"


@pytest.mark.asyncio
async def test_adjust_positive_and_negative_guards(async_db_session: AsyncSession):
    v = await _mk_variant(async_db_session, on_hand=10)
    # ajuste positivo
    await inventory_service.adjust_stock(async_db_session, v, +3, reason="ajuste +")
    await async_db_session.commit()
    await async_db_session.refresh(v)
    assert v.stock_on_hand == 13

    # ajuste negativo válido
    await inventory_service.adjust_stock(async_db_session, v, -3, reason="ajuste -")
    await async_db_session.commit()
    await async_db_session.refresh(v)
    assert v.stock_on_hand == 10

    # ajuste que dejaría negativo -> 400
    with pytest.raises(InsufficientStockError) as exc:
        await inventory_service.adjust_stock(async_db_session, v, -11, reason="negativo")
    assert "negativo" in exc.value.detail


@pytest.mark.asyncio
async def test_reserve_and_release_validation(async_db_session: AsyncSession):
    v = await _mk_variant(async_db_session, on_hand=5, reserved=0)

    # reservar más que on_hand -> 400
    with pytest.raises(InsufficientStockError):
        await inventory_service.reserve_stock(async_db_session, v, 6, reason="over")
    await async_db_session.refresh(v)
    assert v.stock_reserved == 0

    # reservar 3
    await inventory_service.reserve_stock(async_db_session, v, 3, reason="pedido")
    await async_db_session.commit()
    await async_db_session.refresh(v)
    assert v.stock_reserved == 3
    assert v.stock_on_hand == 5  # no cambia on_hand al reservar

    # release más de lo reservado -> 400
    with pytest.raises(Exception): # Puede ser InsufficientReservationError
            await inventory_service.release_stock(async_db_session, v, 4, reason="over-release")

    # release 2
    await inventory_service.release_stock(async_db_session, v, 2, reason="liberar")
    await async_db_session.commit()
    await async_db_session.refresh(v)
    assert v.stock_reserved == 1
    assert v.stock_on_hand == 5


@pytest.mark.asyncio
async def test_commit_sale_from_reserved_and_onhand(async_db_session: AsyncSession):
    v = await _mk_variant(async_db_session, on_hand=10, reserved=3)

    # La venta directa no consume reservas de pedidos.
    await inventory_service.commit_sale(async_db_session, v, 2, reason="venta-1")
    await async_db_session.commit()
    await async_db_session.refresh(v)
    assert v.stock_reserved == 3
    assert v.stock_on_hand == 8  # 10 - 2

    # Otra venta directa consume sólo stock disponible.
    await inventory_service.commit_sale(async_db_session, v, 2, reason="venta-2")
    await async_db_session.commit()
    await async_db_session.refresh(v)
    assert v.stock_reserved == 3
    assert v.stock_on_hand == 6  # 8 - 2

    # vender más que on_hand -> 400
    with pytest.raises(InsufficientStockError):
        await inventory_service.commit_sale(async_db_session, v, 999, reason="no-stock")


@pytest.mark.asyncio
async def test_alerts_and_replenishment_suggestion_without_supplier(async_db_session: AsyncSession):
    # available = 2-1 = 1 ; reorder_point=3 => alerta
    v = await _mk_variant(async_db_session, on_hand=2, reserved=1, reorder_point=3, reorder_qty=5)

    alerts = await inventory_service.compute_stock_alerts(async_db_session, supplier_id=None)
    hit = next((a for a in alerts if a.variant_id == v.id), None)
    assert hit is not None
    assert hit.available == 1
    assert hit.reorder_point == 3
    assert hit.missing == 2

    sugg = await inventory_service.compute_replenishment_suggestion(async_db_session, supplier_id=None)
    line = next((item for item in sugg.lines if item.variant_id == v.id), None)
    assert line is not None
    # regla: max(missing, reorder_qty) con mínimo 1
    assert line.suggested_qty == 5
    assert "available(1) <= reorder_point(3)" in line.reason


@pytest.mark.asyncio
async def test_alerts_and_replenishment_filtered_by_supplier(async_db_session: AsyncSession):
    supplier_id = uuid.uuid4()

    # crear fila en suppliers para respetar el FK
    unique_name = f"Test Supplier {uuid.uuid4()}"  # evitar UniqueViolation en ix_suppliers_name
    async_db_session.add(Supplier(id=supplier_id, name=unique_name))
    await async_db_session.commit()

    v1 = await _mk_variant(
        async_db_session,
        on_hand=1,
        reserved=1,          # available=0
        reorder_point=2,
        reorder_qty=4,
        primary_supplier_id=supplier_id,
    )
    # v2 sin supplier o distinto -> no debe aparecer en filtro
    v2 = await _mk_variant(
        async_db_session,
        on_hand=0,
        reserved=0,
        reorder_point=1,
        reorder_qty=2,
        primary_supplier_id=None,
    )

    alerts = await inventory_service.compute_stock_alerts(async_db_session, supplier_id=supplier_id)
    ids = {a.variant_id for a in alerts}
    assert v1.id in ids
    assert v2.id not in ids

    sugg = await inventory_service.compute_replenishment_suggestion(async_db_session, supplier_id=supplier_id)
    assert sugg.supplier_id == supplier_id
    line_ids = {item.variant_id for item in sugg.lines}
    assert v1.id in line_ids
    assert v2.id not in line_ids


@pytest.mark.asyncio
async def test_invalid_quantities_raise_400(async_db_session: AsyncSession):
    v = await _mk_variant(async_db_session, on_hand=5)

    with pytest.raises(InvalidQuantityError):
        await inventory_service.receive_stock(async_db_session, v, 0)

    with pytest.raises(InvalidQuantityError):
        await inventory_service.reserve_stock(async_db_session, v, -1)

    with pytest.raises(InvalidQuantityError):
        await inventory_service.release_stock(async_db_session, v, 0)

    with pytest.raises(InvalidQuantityError):
        await inventory_service.commit_sale(async_db_session, v, 0)
