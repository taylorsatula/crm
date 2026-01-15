"""Invoice domain models.

All amounts are stored in cents (integer) to avoid floating point issues.
$10.00 = 1000 cents. Tax rate is basis points (10000 = 100%).
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class InvoiceStatus(str, Enum):
    """Invoice lifecycle status."""

    DRAFT = "draft"
    SENT = "sent"
    PARTIAL = "partial"
    PAID = "paid"
    VOID = "void"


class InvoiceCreate(BaseModel):
    """Data required to create an invoice (always from a ticket)."""

    ticket_id: UUID
    customer_id: UUID
    subtotal_cents: int = Field(..., ge=0)
    tax_rate_bps: int = Field(0, ge=0)  # Basis points: 1000 = 10%
    tax_amount_cents: int = Field(0, ge=0)
    total_amount_cents: int = Field(..., ge=0)
    notes: str | None = Field(None, max_length=2000)
    due_at: datetime | None = None


class Invoice(BaseModel):
    """Full invoice entity as stored."""

    id: UUID
    user_id: UUID
    customer_id: UUID
    ticket_id: UUID
    invoice_number: str
    status: InvoiceStatus
    subtotal_cents: int
    tax_rate_bps: int
    tax_amount_cents: int
    total_amount_cents: int
    amount_paid_cents: int
    issued_at: datetime | None
    due_at: datetime | None
    sent_at: datetime | None
    paid_at: datetime | None
    voided_at: datetime | None
    stripe_checkout_session_id: str | None
    stripe_payment_intent_id: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    model_config = {"from_attributes": True}

    @property
    def balance_due_cents(self) -> int:
        """Remaining amount to be paid in cents."""
        return self.total_amount_cents - self.amount_paid_cents

    @property
    def total_amount_dollars(self) -> float:
        """Total amount in dollars for display."""
        return self.total_amount_cents / 100

    @property
    def is_paid(self) -> bool:
        """Whether invoice is fully paid."""
        return self.status == InvoiceStatus.PAID
