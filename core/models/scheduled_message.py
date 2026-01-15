"""Scheduled message domain models."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class MessageStatus(str, Enum):
    """Message delivery status."""

    PENDING = "pending"
    SENT = "sent"
    CANCELLED = "cancelled"
    FAILED = "failed"  # Gateway error - attempted but failed
    SKIPPED = "skipped"  # Precondition failed - no email, etc.


class MessageType(str, Enum):
    """Type of scheduled message."""

    SERVICE_REMINDER = "service_reminder"
    APPOINTMENT_CONFIRMATION = "appointment_confirmation"
    APPOINTMENT_REMINDER = "appointment_reminder"
    CUSTOM = "custom"


class ScheduledMessageCreate(BaseModel):
    """Data required to create a scheduled message."""

    customer_id: UUID
    ticket_id: UUID | None = None
    message_type: MessageType
    template_name: str | None = Field(None, max_length=100)
    subject: str | None = Field(None, max_length=255)
    body: str | None = Field(None, max_length=10000)
    scheduled_for: datetime


class ScheduledMessage(BaseModel):
    """Full scheduled message entity as stored."""

    id: UUID
    user_id: UUID
    customer_id: UUID
    ticket_id: UUID | None
    message_type: MessageType
    template_name: str | None
    subject: str | None
    body: str | None
    scheduled_for: datetime
    status: MessageStatus
    created_at: datetime

    model_config = {"from_attributes": True}
