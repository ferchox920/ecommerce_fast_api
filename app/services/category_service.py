from __future__ import annotations

from typing import Sequence
import re
import unicodedata
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.operations import flush_async, refresh_async
from app.models.product import Category
from app.schemas.category import CategoryCreate, CategoryUpdate


# ---------------- Utils ----------------
def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    return text.lower()


def _as_uuid(value: str | uuid.UUID | None, field: str) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=422, detail=f"Invalid UUID for {field}") from exc


async def _name_exists(db: AsyncSession, name: str) -> bool:
    stmt = select(Category.id).where(Category.name == name).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def _slug_exists(db: AsyncSession, slug: str) -> bool:
    stmt = select(Category.id).where(Category.slug == slug).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


# ---------------- Lectura pública ----------------
async def list_active_categories(db: AsyncSession) -> Sequence[Category]:
    stmt = (
        select(Category)
        .where(Category.active.is_(True))
        .order_by(Category.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def list_all_categories(db: AsyncSession) -> Sequence[Category]:
    stmt = select(Category).order_by(Category.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_category_by_id(db: AsyncSession, category_id: str) -> Category | None:
    return await db.get(Category, _as_uuid(category_id, "category_id"))


async def get_category_by_slug(db: AsyncSession, slug: str) -> Category | None:
    stmt = (
        select(Category)
        .where(Category.slug == slug)
        .where(Category.active.is_(True))
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


# ---------------- Admin CRUD ----------------
async def create_category(db: AsyncSession, payload: CategoryCreate) -> Category:
    data = payload.model_dump()

    raw_slug = (data.get("slug") or "").strip()
    slug = _slugify(raw_slug or data["name"])

    if await _name_exists(db, data["name"]):
        raise HTTPException(status_code=400, detail="Category name already exists")
    if await _slug_exists(db, slug):
        raise HTTPException(status_code=400, detail="Category slug already exists")

    category = Category(
        name=data["name"],
        slug=slug,
        description=data.get("description"),
        active=data.get("active", True),
    )
    db.add(category)
    await flush_async(db, category)
    await refresh_async(db, category)
    return category


async def update_category(db: AsyncSession, category: Category, payload: CategoryUpdate) -> Category:
    changes = payload.model_dump(exclude_unset=True)

    if "name" in changes and changes["name"] != category.name:
        if await _name_exists(db, changes["name"]):
            raise HTTPException(status_code=400, detail="Category name already exists")

    if "slug" in changes:
        target = changes["slug"] or changes.get("name", category.name)
        new_slug = _slugify(target)
        if new_slug != category.slug and await _slug_exists(db, new_slug):
            raise HTTPException(status_code=400, detail="Category slug already exists")
        changes["slug"] = new_slug

    for field, value in changes.items():
        setattr(category, field, value)

    db.add(category)
    await flush_async(db, category)
    await refresh_async(db, category)
    return category


async def delete_category(db: AsyncSession, category: Category) -> None:
    await db.delete(category)
