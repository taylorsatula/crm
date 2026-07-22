"""Ticket (appointment/job) domain models."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class TicketStatus(str, Enum):
    """Ticket lifecycle status."""

    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ConfirmationStatus(str, Enum):
    """Customer confirmation status."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    RESCHEDULE_REQUESTED = "reschedule_requested"


class TicketCreate(BaseModel):
    """Data required to create a ticket."""

    customer_id: UUID
    address_id: UUID | None = None
    scheduled_at: datetime
    scheduled_duration_minutes: int | None = Field(None, ge=1)
    is_price_estimated: bool = False
    notes: str | None = None
    override_schedule_validation: bool = False


class TicketUpdate(BaseModel):
    """Data that can be updated on a ticket. All fields optional."""

    address_id: UUID | None = None
    scheduled_at: datetime | None = None
    scheduled_duration_minutes: int | None = Field(None, ge=1)
    is_price_estimated: bool | None = None
    notes: str | None = None
    confirmation_status: ConfirmationStatus | None = None
    override_schedule_validation: bool = False


class Ticket(BaseModel):
    """Full ticket entity as stored."""

    id: UUID
    workspace_id: UUID
    customer_id: UUID
    address_id: UUID | None
    status: TicketStatus
    scheduled_at: datetime
    scheduled_duration_minutes: int | None
    confirmation_status: ConfirmationStatus
    confirmation_sent_at: datetime | None
    confirmed_at: datetime | None
    clock_in_at: datetime | None
    clock_out_at: datetime | None
    actual_duration_minutes: int | None
    notes: str | None
    closed_at: datetime | None
    is_price_estimated: bool
    location_type: str = "customer_address"
    location_label: str | None = None
    location_address: dict[str, str] | None = None
    source_system: str | None = None
    source_record_id: str | None = None
    financial_match_method: str | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    model_config = {"from_attributes": True}

    @property
    def is_closed(self) -> bool:
        """Whether ticket is closed (immutable)."""
        return self.closed_at is not None

    @property
    def is_in_progress(self) -> bool:
        """Whether technician is currently on-site."""
        return self.clock_in_at is not None and self.clock_out_at is None
