from __future__ import annotations

import uuid
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.operations import flush_async, refresh_async
from app.models.product import Product
from app.models.user import User
from app.models.product_question import ProductQuestion, ProductAnswer, QuestionStatus
from app.schemas.product_question import (
    QuestionCreate,
    AnswerCreate,
    QuestionUpdateVisibility,
    QuestionBlockPayload,
)
from app.services import notification_service
from app.schemas.admin_product_question import AdminPendingQuestionSummary


def _as_uuid(value: str | uuid.UUID, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except Exception:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid UUID for {field}")


async def list_questions(
    db: AsyncSession, product_id: uuid.UUID | None = None, include_hidden: bool = False
):
    stmt = (
        select(ProductQuestion)
        .options(selectinload(ProductQuestion.answers))
        .order_by(ProductQuestion.created_at.desc())
    )
    if product_id:
        # IMPORTANTE: comparar con UUID, no con str
        stmt = stmt.where(ProductQuestion.product_id == _as_uuid(product_id, "product_id"))
    if not include_hidden:
        stmt = stmt.where(
            ProductQuestion.is_visible == True,  # noqa: E712
            ProductQuestion.is_blocked == False,  # noqa: E712
        )
    result = await db.execute(stmt)
    return result.scalars().all()


async def list_pending_questions_for_admin(db: AsyncSession, *, limit: int = 5):
    stmt = (
        select(
            ProductQuestion.id,
            ProductQuestion.product_id,
            ProductQuestion.content.label("body"),
            ProductQuestion.created_at,
            Product.title.label("product_title"),
            User.full_name.label("author_full_name"),
            User.email.label("author_email"),
        )
        .join(Product, Product.id == ProductQuestion.product_id)
        .outerjoin(User, User.id == ProductQuestion.user_id)
        .where(
            ProductQuestion.status == QuestionStatus.pending,
            ProductQuestion.is_blocked == False,  # noqa: E712
        )
        .order_by(ProductQuestion.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    summaries: list[AdminPendingQuestionSummary] = []
    for row in result.all():
        author_name = row.author_full_name or row.author_email
        summaries.append(
            AdminPendingQuestionSummary(
                id=row.id,
                product_id=row.product_id,
                body=row.body,
                created_at=row.created_at,
                product_title=row.product_title,
                author_name=author_name,
            )
        )
    return summaries


async def _load_question(db: AsyncSession, question_id: uuid.UUID) -> ProductQuestion:
    stmt = (
        select(ProductQuestion)
        .options(selectinload(ProductQuestion.answers))
        .where(ProductQuestion.id == question_id)
    )
    result = await db.execute(stmt)
    question = result.scalar_one_or_none()
    if question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    return question


async def create_question(
    db: AsyncSession, *, payload: QuestionCreate, user: User | None
) -> ProductQuestion:
    product = await db.get(Product, _as_uuid(payload.product_id, "product_id"))
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")

    question = ProductQuestion(
        product_id=product.id,                 # UUID OK
        user_id=str(user.id) if user else None,  # user_id es texto en tu modelo
        content=payload.content,
    )
    db.add(question)
    await flush_async(db, question)
    await refresh_async(db, question)

    await notification_service.notify_admin_new_question(db, question)
    return await _load_question(db, question.id)


async def create_answer(
    db: AsyncSession, *, question_id: str, payload: AnswerCreate, admin: User
) -> ProductQuestion:
    question_uuid = _as_uuid(question_id, "question_id")
    question = await db.get(ProductQuestion, question_uuid)
    if not question:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    if question.is_blocked:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Question is blocked")

    answer = ProductAnswer(
        question=question,
        admin_id=str(admin.id),  # admin_id es texto en tu modelo
        content=payload.content,
    )
    db.add(answer)
    question.status = QuestionStatus.answered
    question.is_visible = True
    db.add(question)
    await flush_async(db, answer, question)

    loaded_question = await _load_question(db, question_uuid)
    synced_answer = next((ans for ans in loaded_question.answers if ans.id == answer.id), answer)
    await notification_service.notify_question_answer(db, loaded_question, synced_answer)
    return loaded_question


async def set_visibility(
    db: AsyncSession, *, question_id: str, payload: QuestionUpdateVisibility
) -> ProductQuestion:
    question_uuid = _as_uuid(question_id, "question_id")
    question = await db.get(ProductQuestion, question_uuid)
    if not question:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    question.is_visible = payload.is_visible
    if not payload.is_visible:
        question.status = QuestionStatus.hidden
    elif question.status == QuestionStatus.hidden:
        question.status = QuestionStatus.pending
    db.add(question)
    await flush_async(db, question)
    return await _load_question(db, question_uuid)


async def set_block(
    db: AsyncSession, *, question_id: str, payload: QuestionBlockPayload
) -> ProductQuestion:
    question_uuid = _as_uuid(question_id, "question_id")
    question = await db.get(ProductQuestion, question_uuid)
    if not question:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    question.is_blocked = payload.is_blocked
    if payload.is_blocked:
        question.status = QuestionStatus.blocked
        question.is_visible = False
    db.add(question)
    await flush_async(db, question)
    return await _load_question(db, question_uuid)
