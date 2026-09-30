import pytest
from urllib.parse import urlparse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from uuid import uuid4

from app.models.inventory import InventoryMovement
from app.models.product import Product
from app.models.product_question import ProductQuestion
from app.models.promotion import Promotion, PromotionProduct, PromotionStatus
from app.models.supplier import Supplier
from app.models.user import User
from app.models.wish import Wish
from app.services.product_service.utils import slugify
from scripts import normalize_products, seed_dev_products, seed_dev_users, seed_product_relationships


@pytest.mark.asyncio
async def test_seed_dev_users_populates_expected_users(async_db_session):
    await seed_dev_users.seed_dev_users()

    total_users = (
        await async_db_session.execute(select(func.count(User.id)))
    ).scalar_one()
    assert total_users == len(seed_dev_users.DEV_USERS)

    admin_seed = next(user for user in seed_dev_users.DEV_USERS if user.is_superuser)
    admin = (
        await async_db_session.execute(select(User).where(User.email == admin_seed.email))
    ).scalar_one()
    assert admin.is_superuser is True
    assert admin.email_verified is True
    assert admin.hashed_password != admin_seed.password

    manager_seed = next(user for user in seed_dev_users.DEV_USERS if not user.is_superuser)
    manager = (
        await async_db_session.execute(select(User).where(User.email == manager_seed.email))
    ).scalar_one()
    assert manager.is_superuser is False

    await seed_dev_users.seed_dev_users()
    total_after_second_run = (
        await async_db_session.execute(select(func.count(User.id)))
    ).scalar_one()
    assert total_after_second_run == total_users


@pytest.mark.asyncio
async def test_seed_dev_products_populates_catalog(async_db_session):
    await seed_dev_products.seed_dev_products()

    total_products = (
        await async_db_session.execute(select(func.count(Product.id)))
    ).scalar_one()
    assert total_products == len(seed_dev_products.PRODUCTS)

    campera = (
        await async_db_session.execute(
            select(Product)
            .where(Product.slug == "campera-denim-classic")
            .options(
                selectinload(Product.variants),
                selectinload(Product.images),
                selectinload(Product.category),
                selectinload(Product.brand),
            )
        )
    ).scalar_one()
    assert campera.category is not None
    assert campera.brand is not None
    assert len(campera.variants) == 2
    sku_variant = next(variant for variant in campera.variants if variant.sku == "DENIM-JACKET-BLU-M")
    assert sku_variant.primary_supplier_id is not None

    mochila = (
        await async_db_session.execute(
            select(Product)
            .where(Product.slug == "mochila-urbana-impermeable")
            .options(selectinload(Product.variants))
        )
    ).scalar_one()
    assert mochila.variants[0].allow_backorder is True

    remera = (
        await async_db_session.execute(
            select(Product)
            .where(Product.slug == "remera-basica-organica")
            .options(selectinload(Product.variants))
        )
    ).scalar_one()
    assert remera.category_id is None
    assert remera.brand_id is None
    assert len(remera.variants) == 2

    suppliers_total = (
        await async_db_session.execute(select(func.count(Supplier.id)))
    ).scalar_one()
    assert suppliers_total == len(seed_dev_products.SUPPLIERS)

    await seed_dev_products.seed_dev_products()
    total_products_second_run = (
        await async_db_session.execute(select(func.count(Product.id)))
    ).scalar_one()
    assert total_products_second_run == total_products


@pytest.mark.asyncio
async def test_seed_dev_products_images_have_valid_urls():
    url_pairs: list[tuple[str, str]] = []
    for seed in seed_dev_products.PRODUCTS:
        slug = seed.slug or slugify(seed.title)
        assert seed.images, f"{slug} is missing dev seed images"
        for image in seed.images:
            url_pairs.append((slug, image.url))

    assert len({url for _, url in url_pairs}) == len(url_pairs)
    for slug, url in url_pairs:
        parsed = urlparse(url)
        assert parsed.scheme == "https", slug
        assert parsed.hostname == "images.unsplash.com", slug
        assert parsed.path.startswith("/photo-"), slug


@pytest.mark.asyncio
async def test_seed_product_relationships(async_db_session):
    await seed_product_relationships.seed_product_relationships()

    question_row = (
        await async_db_session.execute(
            select(ProductQuestion, Product.slug)
            .join(Product, Product.id == ProductQuestion.product_id)
            .where(ProductQuestion.content == "La campera trae forro desmontable?")
        )
    ).one()
    assert question_row[1] == "campera-denim-classic"

    wish_user = (
        await async_db_session.execute(
            select(User).where(User.email == "user2.dev@example.com")
        )
    ).scalar_one()
    wish_product = (
        await async_db_session.execute(
            select(Product).where(Product.slug == "campera-denim-classic")
        )
    ).scalar_one()
    wish = (
        await async_db_session.execute(
            select(Wish).where(
                Wish.user_id == str(wish_user.id),
                Wish.product_id == wish_product.id,
            )
        )
    ).scalar_one()
    assert str(wish.desired_price) == "44999.00"

    movement = (
        await async_db_session.execute(
            select(InventoryMovement).where(InventoryMovement.reason == "DEV_SEED_RESTOCK_DENIM")
        )
    ).scalar_one()
    assert movement.quantity == 5

    promo = (
        await async_db_session.execute(
            select(Promotion).where(Promotion.name == "Winter Denim 10 OFF")
        )
    ).scalar_one()
    assert promo.status == PromotionStatus.active

    promo_product = (
        await async_db_session.execute(
            select(PromotionProduct)
            .join(Product, PromotionProduct.product_id == Product.id)
            .where(Product.slug == "campera-denim-classic", PromotionProduct.promotion_id == promo.id)
        )
    ).scalar_one_or_none()
    assert promo_product is not None

    counts_before = {
        "questions": (
            await async_db_session.execute(select(func.count(ProductQuestion.id)))
        ).scalar_one(),
        "wishes": (
            await async_db_session.execute(select(func.count(Wish.id)))
        ).scalar_one(),
        "movements": (
            await async_db_session.execute(select(func.count(InventoryMovement.id)))
        ).scalar_one(),
        "promotions": (
            await async_db_session.execute(select(func.count(Promotion.id)))
        ).scalar_one(),
    }

    await seed_product_relationships.seed_product_relationships()

    counts_after = {
        "questions": (
            await async_db_session.execute(select(func.count(ProductQuestion.id)))
        ).scalar_one(),
        "wishes": (
            await async_db_session.execute(select(func.count(Wish.id)))
        ).scalar_one(),
        "movements": (
            await async_db_session.execute(select(func.count(InventoryMovement.id)))
        ).scalar_one(),
        "promotions": (
            await async_db_session.execute(select(func.count(Promotion.id)))
        ).scalar_one(),
    }

    assert counts_after == counts_before


@pytest.mark.asyncio
async def test_normalize_products_removes_non_seed_records(async_db_session):
    await seed_dev_products.seed_dev_products()

    extra = Product(
        id=uuid4(),
        title="Producto Temporal",
        slug="producto-temporal",
        price=1000.0,
        currency="ARS",
        active=True,
    )
    async_db_session.add(extra)
    await async_db_session.commit()

    await normalize_products.normalize_products()

    slugs_after = {
        row[0]
        for row in (
            await async_db_session.execute(select(Product.slug))
        )
    }
    expected_slugs = {
        seed.slug or slugify(seed.title)
        for seed in seed_dev_products.PRODUCTS
    }
    expected_slugs.update(seed.product_slug for seed in seed_product_relationships.RELATION_SEEDS)

    assert slugs_after == expected_slugs
