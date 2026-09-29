from typing import Optional

from fastapi import APIRouter, Depends, Query, Security, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session_async import get_async_db
from app.models.user import User
from app.schemas.loyalty import LoyaltyProfileRead, LoyaltyAdjustPayload, LoyaltyRedeemPayload
from app.services import loyalty_service

router = APIRouter(prefix="/loyalty", tags=["loyalty"])


@router.get("/profile", response_model=LoyaltyProfileRead)
async def get_profile(
    user_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["users:me"]),
):
    target_user = user_id or str(current_user.id)
    if str(target_user) != str(current_user.id) and not current_user.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to access another user's profile")
    profile = await loyalty_service.get_profile(db, target_user)
    return LoyaltyProfileRead.model_validate(profile)


@router.post("/adjust", response_model=LoyaltyProfileRead)
async def adjust_profile(
    payload: LoyaltyAdjustPayload,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["admin"]),
):
    profile = await loyalty_service.apply_adjustment(db, payload)
    return LoyaltyProfileRead.model_validate(profile)


@router.post("/redeem", response_model=LoyaltyProfileRead)
async def redeem_reward(
    payload: LoyaltyRedeemPayload,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["users:me"]),
):
    target_user = payload.user_id or str(current_user.id)
    if str(target_user) != str(current_user.id) and not current_user.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to redeem for another user")
    redeem_payload = LoyaltyRedeemPayload(
        user_id=target_user,
        points=payload.points,
        reward_code=payload.reward_code,
        metadata=payload.metadata,
    )
    try:
        profile = await loyalty_service.redeem_reward(db, redeem_payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return LoyaltyProfileRead.model_validate(profile)


@router.get("/levels")
async def list_levels(db: AsyncSession = Depends(get_async_db)):
    levels = await loyalty_service.list_levels(db)
    return [
        {
            "level": level.level,
            "min_points": level.min_points,
            "perks_json": level.perks_json,
        }
        for level in levels
    ]
