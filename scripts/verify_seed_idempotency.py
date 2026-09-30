"""Run the documented development seeds twice against a migrated PostgreSQL database."""

from __future__ import annotations

import asyncio
import logging
import socket
from unittest.mock import patch

from sqlalchemy import text

from app.db.session_async import AsyncSessionLocal, async_engine
from scripts import seed_dev_products, seed_dev_users, seed_product_relationships


TABLES = (
    "users", "categories", "brands", "suppliers", "products",
    "product_variants", "product_images", "product_questions", "wishes",
    "inventory_movements", "promotions", "promotion_products",
)

RELATIONS = (
    ("product_variants", "product_id", "products"),
    ("product_images", "product_id", "products"),
    ("product_questions", "product_id", "products"),
    ("wishes", "product_id", "products"),
    ("wishes", "user_id", "users"),
    ("inventory_movements", "variant_id", "product_variants"),
    ("promotion_products", "promotion_id", "promotions"),
    ("promotion_products", "product_id", "products"),
)


def _local_only_connect(original):
    def checked(sock, address):
        host = address[0] if isinstance(address, tuple) else ""
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise AssertionError("Seed attempted an external connection")
        return original(sock, address)

    return checked


async def _counts():
    async with AsyncSessionLocal() as session:
        # Names are constants in this file, never user input.
        return {
            table: await session.scalar(text(f"SELECT count(*) FROM {table}"))
            for table in TABLES
        }


async def _check_integrity():
    async with AsyncSessionLocal() as session:
        for child, column, parent in RELATIONS:
            missing = await session.scalar(text(
                f"SELECT count(*) FROM {child} c LEFT JOIN {parent} p "
                f"ON c.{column} = p.id WHERE c.{column} IS NOT NULL AND p.id IS NULL"
            ))
            assert missing == 0, f"Broken seed relation: {child}.{column}"
        for table, column in (("users", "email"), ("products", "slug"), ("product_variants", "sku")):
            duplicates = await session.scalar(text(
                f"SELECT count(*) - count(DISTINCT {column}) FROM {table}"
            ))
            assert duplicates == 0, f"Duplicate seed key: {table}.{column}"


async def main():
    assert async_engine.url.get_backend_name() == "postgresql", "PostgreSQL is required"
    before = await _counts()
    original_connect = socket.socket.connect
    with patch.object(socket.socket, "connect", _local_only_connect(original_connect)):
        for run in (1, 2):
            await seed_dev_users.seed_dev_users()
            await seed_dev_products.seed_dev_products()
            await seed_product_relationships.seed_product_relationships()
            counts = await _counts()
            await _check_integrity()
            print(f"seed run {run}: {counts}")
            if run == 1:
                first = counts
            else:
                assert counts == first, "Seed counts changed on the second run"
    assert first["users"] == len(seed_dev_users.DEV_USERS)
    assert first["products"] == len(seed_dev_products.PRODUCTS)
    assert first["product_variants"] > 0 and first["promotion_products"] > 0
    print(f"seed verification passed; initial counts: {before}; external connections: 0")
    await async_engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    asyncio.run(main())
