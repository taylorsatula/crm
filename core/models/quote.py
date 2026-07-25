"""Quote (price proposal) domain models."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class QuoteStatus(str, Enum):
    """Quote lifecycle status."""

    DRAFT = "draft"
    SENT = "sent"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ARCHIVED = "archived"


# Valid status transitions: source → {targets}
QUOTE_VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"sent", "archived"},
    "sent": {"accepted", "rejected", "expired", "archived"},
    "expired": {"sent", "archived"},
    "accepted": set(),  # terminal
    "rejected": {"archived"},
    "archived": set(),  # terminal
}


class QuoteCreate(BaseModel):
    """Data required to create a quote."""

    customer_id: UUID
    lead_id: UUID | None = None
    title: str | None = Field(None, max_length=500)
    notes: str | None = Field(None, max_length=10000)
    expires_at: datetime | None = None


class QuoteUpdate(BaseModel):
    """Data that can be updated on a draft quote. All fields optional."""

    title: str | None = Field(None, max_length=500)
    notes: str | None = Field(None, max_length=10000)
    expires_at: datetime | None = None


class Quote(BaseModel):
    """Full quote entity as stored."""

    id: UUID
    workspace_id: UUID
    customer_id: UUID
    status: QuoteStatus
    title: str | None
    notes: str | None
    expires_at: datetime | None
    sent_at: datetime | None
    accepted_at: datetime | None
    rejected_at: datetime | None
    archived_at: datetime | None
    created_ticket_id: UUID | None
    lead_id: UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    model_config = {"from_attributes": True}

    @property
    def is_terminal(self) -> bool:
        """Whether quote is in a terminal state (accepted or archived)."""
        return self.status in (QuoteStatus.ACCEPTED, QuoteStatus.ARCHIVED)


class QuoteLineItemCreate(BaseModel):
    """Data required to create a quote line item."""

    service_id: UUID | None = None
    description: str | None = Field(None, max_length=500)
    quantity: int = Field(1, ge=1)
    unit_price_cents: int | None = Field(None, ge=0)
    total_price_cents: int | None = Field(None, ge=0)
    duration_minutes: int | None = Field(None, ge=0)
    notes: str | None = Field(None, max_length=1000)

    @model_validator(mode="after")
    def compute_total_if_missing(self) -> "QuoteLineItemCreate":
        """Compute total_price_cents from quantity * unit_price_cents if not provided."""
        if self.total_price_cents is None and self.unit_price_cents is not None:
            self.total_price_cents = self.quantity * self.unit_price_cents
        return self


class QuoteLineItemUpdate(BaseModel):
    """Data that can be updated on a quote line item. All fields optional."""

    service_id: UUID | None = None
    description: str | None = Field(None, max_length=500)
    quantity: int | None = Field(None, ge=1)
    unit_price_cents: int | None = Field(None, ge=0)
    total_price_cents: int | None = Field(None, ge=0)
    duration_minutes: int | None = Field(None, ge=0)
    notes: str | None = Field(None, max_length=1000)


class QuoteLineItem(BaseModel):
    """Full quote line item entity as stored."""

    id: UUID
    workspace_id: UUID
    quote_id: UUID
    service_id: UUID | None
    description: str | None
    quantity: int
    unit_price_cents: int | None
    total_price_cents: int | None
    duration_minutes: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    model_config = {"from_attributes": True}
