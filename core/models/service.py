"""Service catalog domain models.

All prices are stored in cents (integer) to avoid floating point issues.
$10.00 = 1000 cents.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class PricingType(str, Enum):
    """How a service is priced."""

    FIXED = "fixed"        # Set price regardless of scope
    FLEXIBLE = "flexible"  # Price determined at ticket creation
    PER_UNIT = "per_unit"  # Quantity x unit price


class ServiceCreate(BaseModel):
    """Data required to create a service."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    pricing_type: PricingType
    default_price_cents: int | None = Field(None, ge=0)
    unit_price_cents: int | None = Field(None, ge=0)
    unit_label: str | None = Field(None, max_length=50)
    is_active: bool = True
    display_order: int = 0

    @model_validator(mode="after")
    def validate_pricing(self) -> "ServiceCreate":
        """Ensure pricing fields match pricing type."""
        if self.pricing_type == PricingType.FIXED and self.default_price_cents is None:
            raise ValueError("Fixed pricing requires default_price_cents")
        if self.pricing_type == PricingType.PER_UNIT and self.unit_price_cents is None:
            raise ValueError("Per-unit pricing requires unit_price_cents")
        return self


class ServiceUpdate(BaseModel):
    """Data that can be updated on a service. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    pricing_type: PricingType | None = None
    default_price_cents: int | None = Field(None, ge=0)
    unit_price_cents: int | None = Field(None, ge=0)
    unit_label: str | None = Field(None, max_length=50)
    is_active: bool | None = None
    display_order: int | None = None


class Service(BaseModel):
    """Full service entity as stored."""

    id: UUID
    user_id: UUID
    name: str
    description: str | None
    pricing_type: PricingType
    default_price_cents: int | None
    unit_price_cents: int | None
    unit_label: str | None
    is_active: bool
    display_order: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    model_config = {"from_attributes": True}

    @property
    def default_price_dollars(self) -> float | None:
        """Default price in dollars for display."""
        if self.default_price_cents is None:
            return None
        return self.default_price_cents / 100

    @property
    def unit_price_dollars(self) -> float | None:
        """Unit price in dollars for display."""
        if self.unit_price_cents is None:
            return None
        return self.unit_price_cents / 100
