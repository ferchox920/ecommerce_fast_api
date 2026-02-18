from fastapi import APIRouter, Depends, Security
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session_async import get_async_db
from app.models.user import User
from app.services import analytics_service

router = APIRouter(prefix="/admin/analytics", tags=["analytics"])


@router.get("/overview")
async def overview(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["admin"]),
):
    return await analytics_service.overview(db)


@router.get("/dashboard")
async def dashboard(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Security(get_current_user, scopes=["admin"]),
):
    return await analytics_service.dashboard(db)
