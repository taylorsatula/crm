"""Customer (contact) domain models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, EmailStr, model_validator


class CustomerCreate(BaseModel):
    """Data required to create a customer."""

    first_name: str | None = Field(None, max_length=255)
    last_name: str | None = Field(None, max_length=255)
    business_name: str | None = Field(None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=50)
    address: str | None = Field(None, max_length=500)
    notes: str | None = Field(None, max_length=10000)
    preferred_contact_method: str | None = Field(None, pattern="^(email|phone|text)$")
    preferred_time_of_day: str | None = Field(None, pattern="^(morning|afternoon|evening|any)$")
    reference_id: str | None = Field(None, max_length=100)
    referred_by: UUID | None = None

    @model_validator(mode="after")
    def require_at_least_one_name(self) -> "CustomerCreate":
        """Ensure at least one name field is provided."""
        if not any([self.first_name, self.last_name, self.business_name]):
            raise ValueError("At least one of first_name, last_name, or business_name is required")
        return self


class CustomerUpdate(BaseModel):
    """Data that can be updated on a customer. All fields optional."""

    first_name: str | None = Field(None, max_length=255)
    last_name: str | None = Field(None, max_length=255)
    business_name: str | None = Field(None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=50)
    address: str | None = Field(None, max_length=500)
    notes: str | None = Field(None, max_length=10000)
    preferred_contact_method: str | None = Field(None, pattern="^(email|phone|text)$")
    preferred_time_of_day: str | None = Field(None, pattern="^(morning|afternoon|evening|any)$")
    reference_id: str | None = Field(None, max_length=100)
    referred_by: UUID | None = None


class Customer(BaseModel):
    """Full customer entity as stored."""

    id: UUID
    user_id: UUID
    first_name: str | None
    last_name: str | None
    business_name: str | None
    email: str | None
    phone: str | None
    address: str | None
    reference_id: str | None
    referred_by: UUID | None
    notes: str | None
    preferred_contact_method: str | None
    preferred_time_of_day: str | None
    stripe_customer_id: str | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    model_config = {"from_attributes": True}

    @property
    def display_name(self) -> str:
        """Human-readable name for display."""
        if self.business_name:
            return self.business_name
        parts = [p for p in [self.first_name, self.last_name] if p]
        return " ".join(parts) if parts else "Unnamed Customer"
