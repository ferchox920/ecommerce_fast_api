from uuid import UUID
from typing import List
from pydantic import BaseModel, Field, ConfigDict

class StockAlert(BaseModel):
    variant_id: UUID
    available: int
    reorder_point: int
    missing: int = Field(description="reorder_point - available, acotado a >= 0")

class ReplenishmentLine(BaseModel):
    variant_id: UUID
    suggested_qty: int
    reason: str
    last_unit_cost: float | None = None

class ReplenishmentSuggestion(BaseModel):
    supplier_id: UUID | None = None
    lines: List[ReplenishmentLine] = []
    model_config = ConfigDict(from_attributes=True)
