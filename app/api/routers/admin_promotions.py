from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Security, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session_async import get_async_db
from app.models.promotion import PromotionStatus
from app.models.user import User
from app.schemas.promotion import PromotionCreate, PromotionUpdate, PromotionRead
from app.services import promotion_service

router = APIRouter(prefix="/admin/promotions", tags=["admin-promotions"])


@router.post("", response_model=PromotionRead, status_code=status.HTTP_201_CREATED)
async def create_promotion(
    payload: PromotionCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["admin"]),
):
    promotion = await promotion_service.create_promotion(db, payload)
    await db.commit()
    await db.refresh(promotion)
    return PromotionRead.model_validate(promotion, from_attributes=True)


@router.get("", response_model=list[PromotionRead])
async def list_promotions(
    status_filter: Optional[PromotionStatus] = None,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["admin"]),
):
    promotions = await promotion_service.list_promotions(db, status_filter)
    return [PromotionRead.model_validate(promo, from_attributes=True) for promo in promotions]


@router.patch("/{promotion_id}", response_model=PromotionRead)
async def update_promotion(
    promotion_id: UUID,
    payload: PromotionUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["admin"]),
):
    promotion = await promotion_service.update_promotion(db, promotion_id, payload)
    await db.commit()
    await db.refresh(promotion)
    return PromotionRead.model_validate(promotion, from_attributes=True)


@router.post("/{promotion_id}/activate", response_model=PromotionRead)
async def activate_promotion(
    promotion_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["admin"]),
):
    promotion = await promotion_service.activate_promotion(db, promotion_id)
    await db.commit()
    await db.refresh(promotion)
    return PromotionRead.model_validate(promotion, from_attributes=True)


@router.post("/{promotion_id}/deactivate", response_model=PromotionRead)
async def deactivate_promotion(
    promotion_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["admin"]),
):
    promotion = await promotion_service.deactivate_promotion(db, promotion_id)
    await db.commit()
    await db.refresh(promotion)
    return PromotionRead.model_validate(promotion, from_attributes=True)
