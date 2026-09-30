# app/api/routers/purchases.py
from fastapi import (
    APIRouter,
    Depends,
    Query,
    Security,
    status,
    Path,
)
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from uuid import UUID
from pydantic import BaseModel

from app.db.operations import commit_async, rollback_async
from app.db.session_async import get_async_db
from app.api.deps import get_current_user
from app.models.user import User

from app.schemas.supplier import SupplierCreate, SupplierRead
from app.schemas.purchase import POCreate, PORead, POLineCreate, POReceivePayload
from app.services import purchase_service
from app.services.exceptions import ServiceError

from app.schemas.inventory_replenishment import ReplenishmentSuggestion, StockAlert
from app.services import inventory_service


class POCreateFromSuggestionPayload(BaseModel):
    supplier_id: UUID


router = APIRouter(prefix="/purchases", tags=["purchases"])


@router.post(
    "/suppliers",
    response_model=SupplierRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_supplier(
    payload: SupplierCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["purchases:write"]),
):
    try:
        supplier = await purchase_service.create_supplier(db, payload)
        await commit_async(db)
    except ServiceError:
        await rollback_async(db)
        raise
    except Exception:
        await rollback_async(db)
        raise
    return supplier


@router.get(
    "/suppliers",
    response_model=list[SupplierRead],
)
async def list_suppliers(
    q: Optional[str] = Query(None, description="Texto de búsqueda"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["purchases:read"]),
):
    return await purchase_service.list_suppliers(db, q, limit, offset)


@router.post(
    "/orders",
    response_model=PORead,
    status_code=status.HTTP_201_CREATED,
)
async def create_po(
    payload: POCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["purchases:write"]),
):
    try:
        po = await purchase_service.create_po(db, payload)
        await commit_async(db)
    except ServiceError:
        await rollback_async(db)
        raise
    except Exception:
        await rollback_async(db)
        raise
    return po


@router.get(
    "/orders/{po_id}",
    response_model=PORead,
)
async def get_po(
    po_id: UUID = Path(..., description="ID de la orden de compra"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["purchases:read"]),
):
    return await purchase_service.get_po(db, str(po_id))


@router.post(
    "/orders/{po_id}/lines",
    response_model=PORead,
)
async def add_line(
    po_id: UUID = Path(..., description="ID de la orden de compra"),
    payload: POLineCreate = ...,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["purchases:write"]),
):
    po = await purchase_service.get_po(db, str(po_id))
    try:
        updated = await purchase_service.add_line(db, po, payload)
        await commit_async(db)
    except ServiceError:
        await rollback_async(db)
        raise
    except Exception:
        await rollback_async(db)
        raise
    return updated


@router.post(
    "/orders/{po_id}/place",
    response_model=PORead,
)
async def place_po(
    po_id: UUID = Path(..., description="ID de la orden de compra"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["purchases:write"]),
):
    po = await purchase_service.get_po(db, str(po_id))
    try:
        updated = await purchase_service.place_po(db, po)
        await commit_async(db)
    except ServiceError:
        await rollback_async(db)
        raise
    except Exception:
        await rollback_async(db)
        raise
    return updated


@router.post(
    "/orders/{po_id}/receive",
    response_model=PORead,
)
async def receive_po(
    po_id: UUID = Path(..., description="ID de la orden de compra"),
    payload: POReceivePayload = ...,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["purchases:write"]),
):
    po = await purchase_service.get_po(db, str(po_id))
    try:
        updated = await purchase_service.receive_po(db, po, payload)
        await commit_async(db)
    except ServiceError:
        await rollback_async(db)
        raise
    except Exception:
        await rollback_async(db)
        raise
    return updated


@router.post(
    "/orders/{po_id}/cancel",
    response_model=PORead,
)
async def cancel_po(
    po_id: UUID = Path(..., description="ID de la orden de compra"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["purchases:write"]),
):
    po = await purchase_service.get_po(db, str(po_id))
    try:
        updated = await purchase_service.cancel_po(db, po)
        await commit_async(db)
    except ServiceError:
        await rollback_async(db)
        raise
    except Exception:
        await rollback_async(db)
        raise
    return updated


@router.post(
    "/orders/from-suggestions",
    response_model=PORead,
    status_code=status.HTTP_201_CREATED,
    summary="Create PO from replenishment suggestions",
)
async def create_po_from_suggestions_endpoint(
    payload: POCreateFromSuggestionPayload,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["purchases:write"]),
):
    try:
        po = await purchase_service.create_po_from_suggestions(db, str(payload.supplier_id))
        await commit_async(db)
    except ServiceError:
        await rollback_async(db)
        raise
    except Exception:
        await rollback_async(db)
        raise
    return po


@router.get(
    "/replenishment/alerts",
    response_model=list[StockAlert],
)
async def replenishment_alerts(
    supplier_id: Optional[UUID] = Query(None, description="Filtra por proveedor"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["purchases:read"]),
):
    return await inventory_service.compute_stock_alerts(db, supplier_id)


@router.get(
    "/replenishment/suggestions",
    response_model=ReplenishmentSuggestion,
)
async def replenishment_suggestions(
    supplier_id: Optional[UUID] = Query(None, description="Filtra por proveedor"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["purchases:read"]),
):
    return await inventory_service.compute_replenishment_suggestion(db, supplier_id)
