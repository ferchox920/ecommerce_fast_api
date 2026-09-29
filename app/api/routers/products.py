from uuid import UUID
from math import ceil
from typing import List

from fastapi import APIRouter, Depends, Query, Path, HTTPException, status, Security
from sqlalchemy.ext.asyncio import AsyncSession

# Se corrigen y unifican las importaciones
from app.api.deps import get_current_user
from app.db.operations import commit_async
from app.db.session_async import get_async_db
from app.models.user import User
from app.schemas.inventory import MovementCreate, MovementRead
from app.schemas.pagination import PaginatedProducts
from app.schemas.product import (
    ProductCreate,
    ProductImageCreate,
    ProductImageRead,
    ProductRead,
    ProductUpdate,
    ProductVariantCreate,
    ProductVariantRead,
    ProductVariantUpdate,
)
from app.services import product_service

router = APIRouter(prefix="/products", tags=["products"])

# ---------- Endpoints Públicos (sin seguridad) ----------
@router.get("", response_model=PaginatedProducts)
async def public_list(
    search: str | None = Query(None, description="texto a buscar"),
    category: str | None = Query(None, description="UUID de categoría"),
    brand: str | None = Query(None, description="UUID de marca"),
    min_price: float | None = Query(None, ge=0),
    max_price: float | None = Query(None, ge=0),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_async_db),
):
    items, total = await product_service.list_products_with_total(
        db=db,
        search=search,
        category=category,
        brand=brand,
        min_price=min_price,
        max_price=max_price,
        limit=limit,
        offset=offset,
    )
    page = (offset // limit) + 1
    pages = ceil(total / limit) if total else 1

    return {
        "total": total,
        "page": page,
        "pages": pages,
        "limit": limit,
        "items": items,
    }


@router.get("/{slug}", response_model=ProductRead)
async def public_get(slug: str, db: AsyncSession = Depends(get_async_db)):
    prod = await product_service.get_product_by_slug(db, slug)
    if not prod:
        # Compatibilidad: algunos flujos aún envían product_id en vez de slug.
        # Permitimos fallback por UUID manteniendo visibilidad pública solo para activos.
        try:
            UUID(slug)
        except ValueError:
            raise HTTPException(status_code=404, detail="Product not found")

        prod_by_id = await product_service.get_product_by_id(db, slug)
        if not prod_by_id or not getattr(prod_by_id, "active", False):
            raise HTTPException(status_code=404, detail="Product not found")
        return prod_by_id
    return prod


# ---------- Admin: Producto (requiere scope 'products:write') ----------
@router.post(
    "",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["products:write"]),
):
    product = await product_service.create_product(db, payload)
    await commit_async(db)
    return product


@router.put(
    "/{product_id}",
    response_model=ProductRead,
)
async def admin_update(
    product_id: UUID = Path(..., description="UUID del producto"),
    payload: ProductUpdate = ...,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["products:write"]),
):
    prod = await product_service.get_product_by_id(db, str(product_id))
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    updated = await product_service.update_product(db, prod, payload)
    await commit_async(db)
    return updated


# ---------- Admin: Variantes (requiere scope 'products:write') ----------
@router.post(
    "/{product_id}/variants",
    response_model=ProductVariantRead,
    status_code=status.HTTP_201_CREATED,
)
async def admin_add_variant(
    product_id: UUID = Path(..., description="UUID del producto"),
    payload: ProductVariantCreate = ...,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["products:write"]),
):
    prod = await product_service.get_product_by_id(db, str(product_id))
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    variant = await product_service.add_variant(db, str(product_id), payload)
    await commit_async(db)
    return variant


@router.put(
    "/variants/{variant_id}",
    response_model=ProductVariantRead,
)
async def admin_update_variant(
    variant_id: UUID = Path(..., description="UUID de la variante"),
    payload: ProductVariantUpdate = ...,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["products:write"]),
):
    var = await product_service.get_variant(db, str(variant_id))
    if not var:
        raise HTTPException(status_code=404, detail="Variant not found")
    updated = await product_service.update_variant(db, var, payload)
    await commit_async(db)
    return updated


@router.delete(
    "/variants/{variant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_delete_variant(
    variant_id: UUID = Path(..., description="UUID de la variante"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["products:write"]),
):
    var = await product_service.get_variant(db, str(variant_id))
    if not var:
        raise HTTPException(status_code=404, detail="Variant not found")
    await product_service.delete_variant(db, var)
    await commit_async(db)
    return


# ---------- Admin: Imágenes (requiere scope 'products:write') ----------
@router.post(
    "/{product_id}/images",
    response_model=ProductImageRead,
    status_code=status.HTTP_201_CREATED,
)
async def admin_add_image(
    product_id: UUID = Path(..., description="UUID del producto"),
    payload: ProductImageCreate = ...,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["products:write"]),
):
    prod = await product_service.get_product_by_id(db, str(product_id))
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    image = await product_service.add_image(db, str(product_id), payload)
    await commit_async(db)
    return image


@router.post(
    "/{product_id}/images/{image_id}/primary",
    response_model=ProductRead,
)
async def admin_set_primary_image(
    product_id: UUID = Path(..., description="UUID del producto"),
    image_id: UUID = Path(..., description="UUID de la imagen"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["products:write"]),
):
    prod = await product_service.get_product_by_id(db, str(product_id))
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    updated = await product_service.set_primary_image(db, prod, str(image_id))
    await commit_async(db)
    return updated


# ---------- Admin: Movimientos de Inventario (requiere scope 'products:write') ----------
@router.patch(
    "/variants/{variant_id}/stock",
    response_model=ProductVariantRead,
)
async def admin_set_stock(
    variant_id: UUID = Path(..., description="UUID de la variante"),
    on_hand: int | None = Query(None, ge=0),
    reserved: int | None = Query(None, ge=0),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["products:write"]),
):
    var = await product_service.get_variant(db, str(variant_id))
    if not var:
        raise HTTPException(status_code=404, detail="Variant not found")
    updated = await product_service.set_stock(db, var, on_hand, reserved)
    await commit_async(db)
    return updated

# ... (El resto de los endpoints de movimientos de stock siguen el mismo patrón)

@router.post(
    "/variants/{variant_id}/stock/receive",
    response_model=ProductVariantRead,
)
async def admin_receive_stock(
    variant_id: UUID = Path(..., description="UUID de la variante"),
    payload: MovementCreate = ...,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["products:write"]),
):
    var = await product_service.get_variant(db, str(variant_id))
    if not var:
        raise HTTPException(status_code=404, detail="Variant not found")
    if payload.type != "receive":
        raise HTTPException(status_code=400, detail="type debe ser 'receive'")
    updated = await product_service.receive_stock(db, var, payload.quantity, payload.reason, payload.idempotency_key)
    await commit_async(db)
    return updated

@router.post(
    "/variants/{variant_id}/stock/reserve",
    response_model=ProductVariantRead,
)
async def admin_reserve_stock(
    variant_id: UUID = Path(..., description="UUID de la variante"),
    payload: MovementCreate = ...,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["products:write"]),
):
    var = await product_service.get_variant(db, str(variant_id))
    if not var:
        raise HTTPException(status_code=404, detail="Variant not found")
    if payload.type != "reserve":
        raise HTTPException(status_code=400, detail="type debe ser 'reserve'")
    updated = await product_service.reserve_stock(db, var, payload.quantity, payload.reason, payload.idempotency_key)
    await commit_async(db)
    return updated

@router.post(
    "/variants/{variant_id}/stock/release",
    response_model=ProductVariantRead,
)
async def admin_release_stock(
    variant_id: UUID = Path(..., description="UUID de la variante"),
    payload: MovementCreate = ...,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["products:write"]),
):
    var = await product_service.get_variant(db, str(variant_id))
    if not var:
        raise HTTPException(status_code=404, detail="Variant not found")
    if payload.type != "release":
        raise HTTPException(status_code=400, detail="type debe ser 'release'")
    updated = await product_service.release_stock(db, var, payload.quantity, payload.reason, payload.idempotency_key)
    await commit_async(db)
    return updated

@router.post(
    "/variants/{variant_id}/stock/sale",
    response_model=ProductVariantRead,
)
async def admin_commit_sale(
    variant_id: UUID = Path(..., description="UUID de la variante"),
    payload: MovementCreate = ...,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["products:write"]),
):
    var = await product_service.get_variant(db, str(variant_id))
    if not var:
        raise HTTPException(status_code=404, detail="Variant not found")
    if payload.type != "sale":
        raise HTTPException(status_code=400, detail="type debe ser 'sale'")
    updated = await product_service.commit_sale(db, var, payload.quantity, payload.reason, payload.idempotency_key)
    await commit_async(db)
    return updated

@router.post(
    "/variants/{variant_id}/stock/adjust",
    response_model=ProductVariantRead,
)
async def admin_adjust_stock(
    variant_id: UUID = Path(..., description="UUID de la variante"),
    delta: int = Query(...),
    reason: str | None = Query(None),
    idempotency_key: str | None = Query(None, max_length=120),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["products:write"]),
):
    var = await product_service.get_variant(db, str(variant_id))
    if not var:
        raise HTTPException(status_code=404, detail="Variant not found")
    updated = await product_service.adjust_stock(db, var, delta, reason, idempotency_key)
    await commit_async(db)
    return updated


# ---------- Admin: Lectura de Datos (requiere scope 'products:read') ----------
@router.get(
    "/variants/{variant_id}/stock/movements",
    response_model=List[MovementRead],
)
async def admin_list_movements(
    variant_id: UUID = Path(..., description="UUID de la variante"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["products:read"]),
):
    var = await product_service.get_variant(db, str(variant_id))
    if not var:
        raise HTTPException(status_code=404, detail="Variant not found")
    return await product_service.list_movements(db, var, limit, offset)


@router.get(
    "/{product_id}/quality",
    response_model=dict,
)
async def admin_product_quality(
    product_id: UUID = Path(..., description="UUID del producto"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["products:read"]),
):
    prod = await product_service.get_product_by_id(db, str(product_id))
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    return await product_service.compute_product_quality(db, prod)
