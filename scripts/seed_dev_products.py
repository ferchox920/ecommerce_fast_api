"""Seed script for populating development product data."""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

# Ensure SQLAlchemy relationships are fully registered before using services.
import app.models.inventory  # noqa: F401

from app.core.config import settings
from app.db.session_async import AsyncSessionLocal
from app.models.product import Brand, Category, Product, ProductImage, ProductVariant
from app.models.supplier import Supplier
from app.schemas.brand import BrandCreate
from app.schemas.category import CategoryCreate as ProductCategoryCreate
from app.schemas.product import (
    ProductCreate,
    ProductImageCreate,
    ProductVariantCreate,
)
from app.schemas.supplier import SupplierCreate
from app.services import brand_service, category_service, product_service, purchase_service
from app.services.product_service.utils import slugify


@dataclass(frozen=True, slots=True)
class CategorySeed:
    name: str
    slug: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class BrandSeed:
    name: str
    slug: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class SupplierSeed:
    name: str
    email: str | None = None
    phone: str | None = None


@dataclass(frozen=True, slots=True)
class VariantSeed:
    sku: str
    size_label: str
    color_name: str
    color_hex: str | None = None
    stock_on_hand: int = 0
    reorder_point: int = 0
    reorder_qty: int = 0
    primary_supplier_key: str | None = None
    allow_backorder: bool = False
    allow_preorder: bool = False


@dataclass(frozen=True, slots=True)
class ImageSeed:
    url: str
    alt_text: str | None = None
    is_primary: bool = False
    sort_order: int = 0


@dataclass(frozen=True, slots=True)
class ProductSeed:
    title: str
    price: float
    currency: str = "ARS"
    slug: str | None = None
    description: str | None = None
    material: str | None = None
    care: str | None = None
    category_key: str | None = None
    brand_key: str | None = None
    variants: Sequence[VariantSeed] = field(default_factory=tuple)
    images: Sequence[ImageSeed] = field(default_factory=tuple)
    gender: str | None = None
    season: str | None = None
    fit: str | None = None


CATEGORIES: dict[str, CategorySeed] = {
    "menswear": CategorySeed(
        name="Ropa Hombre",
        slug="menswear",
        description="Coleccion urbana para hombre.",
    ),
    "accessories": CategorySeed(
        name="Accesorios",
        slug="accessories",
        description="Complementos, bolsos y mas.",
    ),
}

BRANDS: dict[str, BrandSeed] = {
    "norte": BrandSeed(
        name="Norte Denim",
        slug="norte-denim",
        description="Marca local enfocada en denim sostenible.",
    ),
    "andina": BrandSeed(
        name="Andina Outdoor",
        slug="andina-outdoor",
        description="Equipamiento y prendas para actividades outdoor.",
    ),
}

SUPPLIERS: dict[str, SupplierSeed] = {
    "main-factory": SupplierSeed(
        name="Main Factory SA",
        email="compras@mainfactory.test",
        phone="+54 11 5555-1111",
    ),
    "accesorios-sur": SupplierSeed(
        name="Accesorios del Sur",
        email="ventas@suraccess.test",
        phone="+54 11 5555-2222",
    ),
}

PRODUCTS: tuple[ProductSeed, ...] = (
    ProductSeed(
        title="Campera Denim Classic",
        slug="campera-denim-classic",
        description="Campera denim clasica con acabado stone washed.",
        material="100% algodon",
        care="Lavar con agua fria y colores similares.",
        price=45999.0,
        gender="men",
        season="winter",
        fit="regular",
        category_key="menswear",
        brand_key="norte",
        variants=(
            VariantSeed(
                sku="DENIM-JACKET-BLU-M",
                size_label="M",
                color_name="Azul Oscuro",
                color_hex="#1B3B6F",
                stock_on_hand=15,
                reorder_point=5,
                reorder_qty=10,
                primary_supplier_key="main-factory",
            ),
            VariantSeed(
                sku="DENIM-JACKET-BLU-L",
                size_label="L",
                color_name="Azul Oscuro",
                color_hex="#1B3B6F",
                stock_on_hand=8,
                reorder_point=4,
                reorder_qty=10,
                primary_supplier_key="main-factory",
            ),
        ),
        images=(
            ImageSeed(
                url="https://images.unsplash.com/photo-1495105787522-5334e3ffa0ef?auto=format&fit=crop&w=1200&q=80",
                alt_text="Campera denim clasica frente",
                is_primary=True,
                sort_order=0,
            ),
            ImageSeed(
                url="https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?auto=format&fit=crop&w=1200&q=80",
                alt_text="Detalle espalda campera denim",
                sort_order=1,
            ),
        ),
    ),
    ProductSeed(
        title="Mochila Urbana Impermeable",
        slug="mochila-urbana-impermeable",
        description="Mochila de 25L con bolsillos ocultos y tejido impermeable.",
        price=28999.0,
        category_key="accessories",
        brand_key="andina",
        variants=(
            VariantSeed(
                sku="BACKPACK-GRY-UNI",
                size_label="Unica",
                color_name="Gris Carbon",
                color_hex="#2F2F2F",
                stock_on_hand=20,
                reorder_point=6,
                reorder_qty=12,
                primary_supplier_key="accesorios-sur",
                allow_backorder=True,
            ),
        ),
        images=(
            ImageSeed(
                url="https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=1200&q=80",
                alt_text="Mochila impermeable gris",
                is_primary=True,
                sort_order=0,
            ),
            ImageSeed(
                url="https://images.unsplash.com/photo-1512436991641-6745cdb1723f?auto=format&fit=crop&w=1200&q=80",
                alt_text="Detalle de bolsillos mochila impermeable gris",
                sort_order=1,
            ),
        ),
    ),
    ProductSeed(
        title="Remera Basica Organica",
        slug="remera-basica-organica",
        description="Remera unisex, algodon organico certificado GOTS.",
        material="Algodon organico",
        care="Lavar a mano o a maquina en ciclo delicado.",
        price=11999.0,
        gender="unisex",
        season="summer",
        fit="relaxed",
        category_key=None,
        brand_key=None,
        variants=(
            VariantSeed(
                sku="TEE-WHT-S",
                size_label="S",
                color_name="Blanco",
                color_hex="#FFFFFF",
                stock_on_hand=12,
                reorder_point=3,
                reorder_qty=8,
                primary_supplier_key=None,
            ),
            VariantSeed(
                sku="TEE-WHT-M",
                size_label="M",
                color_name="Blanco",
                color_hex="#FFFFFF",
                stock_on_hand=18,
                reorder_point=6,
                reorder_qty=10,
                primary_supplier_key=None,
                allow_preorder=True,
            ),
        ),
        images=(
            ImageSeed(
                url="https://images.unsplash.com/photo-1524504388940-b1c1722653e1?auto=format&fit=crop&w=1200&q=80",
                alt_text="Remera basica organica frente",
                is_primary=True,
                sort_order=0,
            ),
            ImageSeed(
                url="https://images.unsplash.com/photo-1489987707025-afc232f7ea0f?auto=format&fit=crop&w=1200&q=80",
                alt_text="Detalle tejido remera basica organica",
                sort_order=1,
            ),
        ),
    ),
)


async def _ensure_category(db, seed: CategorySeed) -> Category:
    target_slug = seed.slug or slugify(seed.name)
    stmt = select(Category).where(Category.slug == target_slug).limit(1)
    existing = (await db.execute(stmt)).scalars().first()
    if existing:
        return existing
    payload = ProductCategoryCreate(name=seed.name, slug=seed.slug)
    category = await category_service.create_category(db, payload)
    if seed.description:
        category.description = seed.description
        db.add(category)
        await db.flush()
        await db.refresh(category)
    return category


async def _ensure_brand(db, seed: BrandSeed) -> Brand:
    target_slug = seed.slug or slugify(seed.name)
    stmt = select(Brand).where(Brand.slug == target_slug).limit(1)
    existing = (await db.execute(stmt)).scalars().first()
    if existing:
        return existing
    payload = BrandCreate(
        name=seed.name,
        slug=seed.slug,
        description=seed.description,
    )
    return await brand_service.create_brand(db, payload)


async def _ensure_supplier(db, seed: SupplierSeed) -> Supplier:
    stmt = select(Supplier).where(Supplier.name == seed.name).limit(1)
    existing = (await db.execute(stmt)).scalars().first()
    if existing:
        return existing
    payload = SupplierCreate(name=seed.name, email=seed.email, phone=seed.phone)
    return await purchase_service.create_supplier(db, payload)


async def _seed_products(db, logger: logging.Logger) -> tuple[int, int, int]:
    category_map: dict[str, Category] = {}
    for key, value in CATEGORIES.items():
        category_map[key] = await _ensure_category(db, value)

    brand_map: dict[str, Brand] = {}
    for key, value in BRANDS.items():
        brand_map[key] = await _ensure_brand(db, value)

    supplier_map: dict[str, Supplier] = {}
    for key, value in SUPPLIERS.items():
        supplier_map[key] = await _ensure_supplier(db, value)

    created = 0
    updated = 0
    skipped = 0

    for seed in PRODUCTS:
        target_slug = seed.slug or slugify(seed.title)
        stmt = (
            select(Product)
            .options(
                selectinload(Product.variants),
                selectinload(Product.images),
            )
            .where(Product.slug == target_slug)
            .limit(1)
        )
        existing = (await db.execute(stmt)).scalars().first()
        category = category_map.get(seed.category_key) if seed.category_key else None
        brand = brand_map.get(seed.brand_key) if seed.brand_key else None

        category_id_str = str(category.id) if category else None
        brand_id_str = str(brand.id) if brand else None

        if existing:
            existing.title = seed.title
            existing.description = seed.description
            existing.material = seed.material
            existing.care = seed.care
            existing.gender = seed.gender
            existing.season = seed.season
            existing.fit = seed.fit
            existing.price = seed.price
            existing.currency = seed.currency
            existing.category_id = category.id if category else None
            existing.brand_id = brand.id if brand else None
            existing.active = True

            existing_variants = {variant.sku: variant for variant in existing.variants}
            expected_skus = set()
            for variant_seed in seed.variants:
                expected_skus.add(variant_seed.sku)
                supplier_id = None
                if variant_seed.primary_supplier_key:
                    supplier = supplier_map.get(variant_seed.primary_supplier_key)
                    if supplier:
                        supplier_id = supplier.id
                    else:
                        logger.warning(
                            "Supplier key %s not found for variant %s",
                            variant_seed.primary_supplier_key,
                            variant_seed.sku,
                        )
                variant = existing_variants.get(variant_seed.sku)
                if variant:
                    variant.size_label = variant_seed.size_label
                    variant.color_name = variant_seed.color_name
                    variant.color_hex = variant_seed.color_hex
                    variant.stock_on_hand = variant_seed.stock_on_hand
                    variant.reorder_point = variant_seed.reorder_point
                    variant.reorder_qty = variant_seed.reorder_qty
                    variant.primary_supplier_id = supplier_id
                    variant.allow_backorder = variant_seed.allow_backorder
                    variant.allow_preorder = variant_seed.allow_preorder
                    variant.active = True
                    variant.price_override = None
                    variant.barcode = None
                    db.add(variant)
                else:
                    new_variant = ProductVariant(
                        product_id=existing.id,
                        sku=variant_seed.sku,
                        size_label=variant_seed.size_label,
                        color_name=variant_seed.color_name,
                        color_hex=variant_seed.color_hex,
                        stock_on_hand=variant_seed.stock_on_hand,
                        stock_reserved=0,
                        reorder_point=variant_seed.reorder_point,
                        reorder_qty=variant_seed.reorder_qty,
                        primary_supplier_id=supplier_id,
                        allow_backorder=variant_seed.allow_backorder,
                        allow_preorder=variant_seed.allow_preorder,
                    )
                    db.add(new_variant)

            for sku, variant in existing_variants.items():
                if sku not in expected_skus:
                    variant.active = False
                    db.add(variant)

            existing_images = {image.sort_order: image for image in existing.images}
            for image_seed in seed.images:
                image = existing_images.get(image_seed.sort_order)
                if image:
                    image.url = image_seed.url
                    image.alt_text = image_seed.alt_text
                    image.is_primary = image_seed.is_primary
                    db.add(image)
                else:
                    new_image = ProductImage(
                        product_id=existing.id,
                        url=image_seed.url,
                        alt_text=image_seed.alt_text,
                        is_primary=image_seed.is_primary,
                        sort_order=image_seed.sort_order,
                    )
                    db.add(new_image)

            db.add(existing)
            updated += 1
            continue

        if seed.category_key and category is None:
            logger.warning("Category key %s not found for product %s", seed.category_key, seed.title)
        if seed.brand_key and brand is None:
            logger.warning("Brand key %s not found for product %s", seed.brand_key, seed.title)

        variant_payloads = []
        for variant_seed in seed.variants:
            supplier_id = None
            if variant_seed.primary_supplier_key:
                supplier = supplier_map.get(variant_seed.primary_supplier_key)
                if supplier:
                    supplier_id = str(supplier.id)
                else:
                    logger.warning(
                        "Supplier key %s not found for variant %s",
                        variant_seed.primary_supplier_key,
                        variant_seed.sku,
                    )
            variant_payloads.append(
                ProductVariantCreate(
                    sku=variant_seed.sku,
                    size_label=variant_seed.size_label,
                    color_name=variant_seed.color_name,
                    color_hex=variant_seed.color_hex,
                    stock_on_hand=variant_seed.stock_on_hand,
                    reorder_point=variant_seed.reorder_point,
                    reorder_qty=variant_seed.reorder_qty,
                    primary_supplier_id=supplier_id,
                    allow_backorder=variant_seed.allow_backorder,
                    allow_preorder=variant_seed.allow_preorder,
                )
            )

        image_payloads = [
            ProductImageCreate(
                url=image_seed.url,
                alt_text=image_seed.alt_text,
                is_primary=image_seed.is_primary,
                sort_order=image_seed.sort_order,
            )
            for image_seed in seed.images
        ]

        payload = ProductCreate(
            title=seed.title,
            slug=seed.slug,
            description=seed.description,
            material=seed.material,
            care=seed.care,
            gender=seed.gender,
            season=seed.season,
            fit=seed.fit,
            price=seed.price,
            currency=seed.currency,
            category_id=category_id_str,
            brand_id=brand_id_str,
            variants=list(variant_payloads),
            images=image_payloads,
        )

        await product_service.create_product(db, payload)
        created += 1
        logger.debug("Created product %s", payload.title)

    return created, updated, skipped


async def seed_dev_products() -> None:
    logger = logging.getLogger("seed_dev_products")
    logger.info("Seeding development products into %s", settings.ASYNC_DATABASE_URL)
    async with AsyncSessionLocal() as session:
        created, updated, skipped = await _seed_products(session, logger)
        await session.commit()
    logger.info("Seed completed: %s created, %s updated, %s skipped", created, updated, skipped)


async def main() -> None:
    await seed_dev_products()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
