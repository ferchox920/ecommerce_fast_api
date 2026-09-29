# app/schemas/inventory.py
from typing import Literal
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict

MovementType = Literal["receive", "adjust", "reserve", "release", "sale"]


class MovementCreate(BaseModel):
    type: MovementType
    quantity: int = Field(gt=0)  # la API siempre manda positivo
    reason: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=120)


class MovementRead(BaseModel):
    id: UUID
    type: MovementType
    quantity: int
    reason: str | None
    created_at: datetime

    # Pydantic v2: reemplaza el viejo Config y permite from_orm
    model_config = ConfigDict(from_attributes=True)
