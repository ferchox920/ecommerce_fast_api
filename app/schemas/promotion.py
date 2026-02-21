from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


class PromotionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    type: str
    scope: Optional[str] = None
    criteria: dict = Field(default_factory=dict)
    benefits: dict = Field(default_factory=dict)
    start_at: datetime
    end_at: datetime


class PromotionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    scope: Optional[str] = None
    criteria: Optional[dict] = None
    benefits: Optional[dict] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    status: Optional[str] = None


class PromotionRead(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    type: str
    scope: str
    criteria_json: dict
    benefits_json: dict
    start_at: datetime
    end_at: datetime
    status: str

    model_config = ConfigDict(from_attributes=True)


class PromotionEligibilityResponse(BaseModel):
    promotion_id: UUID
    eligible: bool
    reasons: list[str] = Field(default_factory=list)
