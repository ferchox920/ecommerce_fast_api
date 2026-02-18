from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.config import settings
from app.core.rate_limiter import rate_limit
from app.db.operations import commit_async
from app.db.session_async import get_async_db
from app.models.user import User as UserModel
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.user_service import create_user, get_by_email, update_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def read_me(current_user: UserModel = Depends(get_current_active_user)):
    return current_user


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(
            rate_limit(
                limit=settings.RATE_LIMIT_REGISTRATION_PER_MINUTE,
                period_seconds=settings.RATE_LIMIT_REGISTRATION_WINDOW_SECONDS,
                scope="users:register",
            )
        )
    ],
)
async def register_user(
    data: UserCreate,
    db: AsyncSession = Depends(get_async_db),
):
    existing = await get_by_email(db, data.email)

    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = await create_user(db, data)
    await commit_async(db)
    return user



@router.put("/me", response_model=UserRead)
async def update_me(
    payload: UserUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: UserModel = Depends(get_current_active_user),
):
    user = await update_user(db, current_user, payload)
    await commit_async(db)
    return user
