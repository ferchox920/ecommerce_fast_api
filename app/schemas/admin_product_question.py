from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AdminPendingQuestionSummary(BaseModel):
    id: UUID
    product_id: UUID
    body: str
    product_title: Optional[str] = None
    created_at: Optional[datetime] = None
    author_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
