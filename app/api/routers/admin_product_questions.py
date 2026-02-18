from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query, Security
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session_async import get_async_db
from app.models.user import User
from app.schemas.admin_product_question import AdminPendingQuestionSummary
from app.services import product_question_service

router = APIRouter(prefix="/admin/product-questions", tags=["admin-product-questions"])


@router.get("", response_model=List[AdminPendingQuestionSummary])
async def list_pending_product_questions(
    limit: int = Query(5, ge=1, le=50),
    db: AsyncSession = Depends(get_async_db),
    _: User = Security(get_current_user, scopes=["admin"]),
):
    return await product_question_service.list_pending_questions_for_admin(db, limit=limit)
