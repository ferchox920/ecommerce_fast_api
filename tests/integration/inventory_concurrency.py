"""Inventory invariants exercised through independent PostgreSQL sessions."""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.inventory import InventoryMovement
from app.models.product import Brand, Category, Product, ProductVariant
from app.models.order import Order
from app.schemas.order import OrderCreate, OrderLineCreate
from app.services import inventory_service, order_service
from app.services.exceptions import InsufficientReservationError, InsufficientStockError
from app.services.exceptions import ConflictError, ResourceNotFoundError


async def _variant(session, *, stock_on_hand: int) -> uuid.UUID:
    category = Category(name=f"Cat-{uuid.uuid4()}", slug=f"cat-{uuid.uuid4()}")
    brand = Brand(name=f"Brand-{uuid.uuid4()}", slug=f"brand-{uuid.uuid4()}")
    session.add_all([category, brand])
    await session.flush()
    product = Product(
        title=f"Prod-{uuid.uuid4()}",
        slug=f"prod-{uuid.uuid4()}",
        price=100,
        currency="ARS",
        category_id=category.id,
        brand_id=brand.id,
        active=True,
    )
    session.add(product)
    await session.flush()
    variant = ProductVariant(
        product_id=product.id,
        sku=f"SKU-{uuid.uuid4()}",
        size_label="M",
        color_name="Black",
        stock_on_hand=stock_on_hand,
        stock_reserved=0,
        active=True,
    )
    session.add(variant)
    await session.commit()
    return variant.id


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["reserve", "sale"])
async def test_last_unit_cannot_be_claimed_twice(operation):
    import os

    engine = create_async_engine(os.environ["ASYNC_DATABASE_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as setup:
            variant_id = await _variant(setup, stock_on_hand=1)

        barrier = asyncio.Barrier(2)

        async def claim() -> str:
            async with sessions() as session:
                variant = await session.get(ProductVariant, variant_id)
                await barrier.wait()
                try:
                    if operation == "reserve":
                        await inventory_service.reserve_stock(
                            session, variant, 1, reason=f"order:{uuid.uuid4()}"
                        )
                    else:
                        await inventory_service.commit_sale(
                            session, variant, 1, reason=f"sale:{uuid.uuid4()}"
                        )
                    await session.commit()
                    return "claimed"
                except InsufficientStockError:
                    await session.rollback()
                    return "rejected"

        results = await asyncio.gather(claim(), claim())
        assert sorted(results) == ["claimed", "rejected"]
        async with sessions() as verify:
            variant = await verify.get(ProductVariant, variant_id)
            if operation == "reserve":
                assert variant.stock_on_hand == 1
                assert variant.stock_reserved == 1
            else:
                assert variant.stock_on_hand == 0
                assert variant.stock_reserved == 0
            count = await verify.scalar(
                select(func.count(InventoryMovement.id)).where(
                    InventoryMovement.variant_id == variant_id
                )
            )
            assert count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_repeated_stock_key_is_one_movement_and_conflicting_reuse_fails():
    import os

    engine = create_async_engine(os.environ["ASYNC_DATABASE_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as setup:
            variant_id = await _variant(setup, stock_on_hand=2)

        async def reserve(quantity: int):
            async with sessions() as session:
                variant = await session.get(ProductVariant, variant_id)
                await inventory_service.reserve_stock(
                    session, variant, quantity, reason="order:retry", idempotency_key="request-1"
                )
                await session.commit()

        await asyncio.gather(reserve(1), reserve(1))
        with pytest.raises(ConflictError):
            await reserve(2)
        async with sessions() as verify:
            variant = await verify.get(ProductVariant, variant_id)
            assert variant.stock_reserved == 1
            assert await verify.scalar(
                select(func.count(InventoryMovement.id)).where(
                    InventoryMovement.variant_id == variant_id
                )
            ) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reservation_and_audit_roll_back_together():
    import os

    engine = create_async_engine(os.environ["ASYNC_DATABASE_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as setup:
            variant_id = await _variant(setup, stock_on_hand=2)
        async with sessions() as session:
            variant = await session.get(ProductVariant, variant_id)
            await inventory_service.reserve_stock(session, variant, 1, reason="failed-order")
            await session.rollback()
        async with sessions() as verify:
            variant = await verify.get(ProductVariant, variant_id)
            assert variant.stock_reserved == 0
            assert await verify.scalar(
                select(func.count(InventoryMovement.id)).where(
                    InventoryMovement.variant_id == variant_id
                )
            ) == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_one_order_cannot_consume_another_orders_reservation():
    import os

    engine = create_async_engine(os.environ["ASYNC_DATABASE_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as setup:
            variant_id = await _variant(setup, stock_on_hand=2)
        async with sessions() as session:
            variant = await session.get(ProductVariant, variant_id)
            await inventory_service.reserve_stock(session, variant, 1, reason="order:first")
            await session.commit()
        async with sessions() as session:
            variant = await session.get(ProductVariant, variant_id)
            with pytest.raises(InsufficientReservationError):
                await inventory_service.release_stock(
                    session, variant, 1, reason="order:second"
                )
            with pytest.raises(InsufficientReservationError):
                await inventory_service.commit_sale(
                    session, variant, 1, reason="order:second"
                )
            with pytest.raises(InsufficientStockError):
                await inventory_service.commit_sale(session, variant, 2, reason="direct")
            await session.rollback()
        async with sessions() as session:
            variant = await session.get(ProductVariant, variant_id)
            await inventory_service.commit_sale(session, variant, 1, reason="order:first")
            await session.commit()
        async with sessions() as verify:
            variant = await verify.get(ProductVariant, variant_id)
            assert (variant.stock_on_hand, variant.stock_reserved) == (1, 0)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_second_order_line_rolls_back_first_reservation():
    import os

    engine = create_async_engine(os.environ["ASYNC_DATABASE_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as setup:
            variant_id = await _variant(setup, stock_on_hand=2)
        async with sessions() as session:
            before = await session.scalar(select(func.count(Order.id)))
        async with sessions() as session:
            payload = OrderCreate(
                currency="ARS",
                lines=[
                    OrderLineCreate(variant_id=variant_id, quantity=1),
                    OrderLineCreate(variant_id=uuid.uuid4(), quantity=1),
                ],
            )
            with pytest.raises(ResourceNotFoundError):
                await order_service.create_order(session, None, payload)
            await session.rollback()
        async with sessions() as verify:
            variant = await verify.get(ProductVariant, variant_id)
            assert variant.stock_reserved == 0
            assert await verify.scalar(select(func.count(Order.id))) == before
            assert await verify.scalar(
                select(func.count(InventoryMovement.id)).where(
                    InventoryMovement.variant_id == variant_id
                )
            ) == 0
    finally:
        await engine.dispose()
