from __future__ import annotations

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


class QuestionCreate(BaseModel):
    product_id: UUID | None = None
    content: str = Field(..., min_length=3, max_length=2000)


class AnswerCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)


class AnswerRead(BaseModel):
    id: UUID
    question_id: UUID
    admin_id: Optional[UUID]
    content: str
    is_visible: bool
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class QuestionRead(BaseModel):
    id: UUID
    product_id: UUID
    user_id: Optional[UUID]
    content: str
    status: str
    is_visible: bool
    is_blocked: bool
    created_at: datetime
    updated_at: Optional[datetime]
    answers: List[AnswerRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class QuestionUpdateVisibility(BaseModel):
    is_visible: bool


class QuestionBlockPayload(BaseModel):
    is_blocked: bool
