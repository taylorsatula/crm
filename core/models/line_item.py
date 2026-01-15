"""Line item domain models.

All prices are stored in cents (integer) to avoid floating point issues.
$10.00 = 1000 cents.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class LineItemCreate(BaseModel):
    """Data required to create a line item."""

    service_id: UUID
    description: str | None = Field(None, max_length=500)
    quantity: int = Field(1, ge=1)
    unit_price_cents: int | None = Field(None, ge=0)
    total_price_cents: int | None = Field(None, ge=0)
    duration_minutes: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def compute_total_if_missing(self) -> "LineItemCreate":
        """Compute total_price_cents from quantity * unit_price_cents if not provided."""
        if self.total_price_cents is None and self.unit_price_cents is not None:
            self.total_price_cents = self.quantity * self.unit_price_cents
        return self


class LineItemUpdate(BaseModel):
    """Data that can be updated on a line item. All fields optional."""

    description: str | None = Field(None, max_length=500)
    quantity: int | None = Field(None, ge=1)
    unit_price_cents: int | None = Field(None, ge=0)
    total_price_cents: int | None = Field(None, ge=0)
    duration_minutes: int | None = Field(None, ge=0)


class LineItem(BaseModel):
    """Full line item entity as stored."""

    id: UUID
    user_id: UUID
    ticket_id: UUID
    service_id: UUID
    description: str | None
    quantity: int
    unit_price_cents: int | None
    total_price_cents: int
    duration_minutes: int | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    model_config = {"from_attributes": True}

    @property
    def total_price_dollars(self) -> float:
        """Total price in dollars for display."""
        return self.total_price_cents / 100
