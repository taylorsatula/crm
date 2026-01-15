"""Lead domain models."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, EmailStr


class LeadStatus(str, Enum):
    """Lead lifecycle status."""

    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    CONVERTED = "converted"
    ARCHIVED = "archived"


class LeadSource(str, Enum):
    """How the lead was acquired."""

    COLD_CALL = "cold_call"
    REFERRAL = "referral"
    WEBSITE = "website"
    OTHER = "other"


class LeadUrgency(str, Enum):
    """How urgent the lead's need is."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LeadCreate(BaseModel):
    """Data required to create a lead."""

    raw_notes: str = Field(..., min_length=1, max_length=50000)
    name: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    email: EmailStr | None = None
    address: str | None = Field(None, max_length=500)
    service_interest: str | None = Field(None, max_length=500)
    lead_source: LeadSource | None = None
    urgency: LeadUrgency | None = None
    property_details: str | None = Field(None, max_length=2000)
    reminder_at: datetime | None = None
    reminder_note: str | None = Field(None, max_length=1000)


class LeadUpdate(BaseModel):
    """Data that can be updated on a lead. All fields optional."""

    raw_notes: str | None = Field(None, min_length=1, max_length=50000)
    name: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    email: EmailStr | None = None
    address: str | None = Field(None, max_length=500)
    service_interest: str | None = Field(None, max_length=500)
    lead_source: LeadSource | None = None
    urgency: LeadUrgency | None = None
    property_details: str | None = Field(None, max_length=2000)
    reminder_at: datetime | None = None
    reminder_note: str | None = Field(None, max_length=1000)
    status: LeadStatus | None = None


class Lead(BaseModel):
    """Full lead entity as stored."""

    id: UUID
    user_id: UUID
    status: LeadStatus
    raw_notes: str
    extracted_data: dict[str, Any] | None
    extracted_at: datetime | None
    name: str | None
    phone: str | None
    email: str | None
    address: str | None
    service_interest: str | None
    lead_source: LeadSource | None
    urgency: LeadUrgency | None
    property_details: str | None
    reminder_at: datetime | None
    reminder_note: str | None
    converted_at: datetime | None
    converted_customer_id: UUID | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    model_config = {"from_attributes": True}

    @property
    def is_converted(self) -> bool:
        """Whether lead has been converted to customer."""
        return self.status == LeadStatus.CONVERTED
