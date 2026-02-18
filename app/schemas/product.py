from uuid import UUID
from typing import Optional, List
from pydantic import BaseModel, Field, HttpUrl, ConfigDict
from datetime import datetime  # <-- NUEVO

from app.schemas.brand import BrandRead
from app.schemas.category import CategoryRead

# --- Images ---
class ProductImageCreate(BaseModel):
    url: HttpUrl
    alt_text: str | None = None
    is_primary: bool = False
    sort_order: int = 0

class ProductImageRead(ProductImageCreate):
    id: UUID
    model_config = ConfigDict(from_attributes=True)

# --- Variants ---
class ProductVariantBase(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    size_label: str = Field(min_length=1, max_length=24)
    color_name: str = Field(min_length=1, max_length=32)
    color_hex: str | None = Field(default=None, pattern=r"^#([0-9a-fA-F]{6})$")

    stock_on_hand: int = Field(ge=0, default=0)
    stock_reserved: int = Field(ge=0, default=0)
    price_override: float | None = Field(default=None, ge=0)

    barcode: str | None = Field(default=None, max_length=64)
    active: bool = True

    # --- Backorders / Preorders (NUEVO) ---
    allow_backorder: bool = False
    allow_preorder: bool = False
    release_at: datetime | None = None

class ProductVariantCreate(ProductVariantBase):
    # Reposición
    reorder_point: int = Field(default=0, ge=0)
    reorder_qty:   int = Field(default=0, ge=0)
    primary_supplier_id: UUID | None = None

class ProductVariantUpdate(BaseModel):
    size_label: str | None = None
    color_name: str | None = None
    color_hex: str | None = Field(default=None, pattern=r"^#([0-9a-fA-F]{6})$")

    stock_on_hand: int | None = Field(default=None, ge=0)
    stock_reserved: int | None = Field(default=None, ge=0)
    price_override: float | None = Field(default=None, ge=0)

    barcode: str | None = None
    active: bool | None = None

    # Reposición
    reorder_point: int | None = Field(default=None, ge=0)
    reorder_qty:   int | None = Field(default=None, ge=0)
    primary_supplier_id: UUID | None = None

    # --- Backorders / Preorders (NUEVO) ---
    allow_backorder: bool | None = None
    allow_preorder: bool | None = None
    release_at: datetime | None = None
    

class ProductVariantRead(ProductVariantBase):
    id: UUID
    reorder_point: int = 0
    reorder_qty:   int = 0
    primary_supplier_id: UUID | None = None

    model_config = ConfigDict(from_attributes=True)

# --- Product ---
class ProductBase(BaseModel):
    title: str
    slug: str | None = None
    description: str | None = None
    material: str | None = None
    care: str | None = None
    gender: str | None = Field(default=None, description='men|women|unisex|kids')
    season: str | None = None
    fit: str | None = None
    price: float = Field(ge=0)
    currency: str = Field(default="ARS", min_length=3, max_length=3)
    # En Create/Update aceptamos string; en Read redefinimos como UUID
    category_id: str | None = None
    brand_id: str | None = None
    active: bool = True

class ProductCreate(ProductBase):
    variants: List[ProductVariantCreate] = Field(default_factory=list)
    images:   List[ProductImageCreate]   = Field(default_factory=list)

class ProductUpdate(BaseModel):
    title: str | None = None
    slug: str | None = None
    description: str | None = None
    material: str | None = None
    care: str | None = None
    gender: str | None = None
    season: str | None = None
    fit: str | None = None
    price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    category_id: str | None = None
    brand_id: str | None = None
    active: bool | None = None

class ProductRead(ProductBase):
    id: UUID
    # IDs como UUID para validar con el ORM
    category_id: Optional[UUID] = None
    brand_id: Optional[UUID] = None
    # Relaciones anidadas
    category: CategoryRead | None = None
    brand: BrandRead | None = None

    variants: List[ProductVariantRead] = []
    images:   List[ProductImageRead]   = []
    model_config = ConfigDict(from_attributes=True)
