"""Address (service location) domain models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AddressCreate(BaseModel):
    """Data required to create an address."""

    customer_id: UUID
    label: str | None = Field(None, max_length=100)
    street: str = Field(..., min_length=1, max_length=255)
    street2: str | None = Field(None, max_length=255)
    city: str = Field(..., min_length=1, max_length=100)
    state: str = Field(..., min_length=1, max_length=50)
    zip: str = Field(..., min_length=1, max_length=20)
    notes: str | None = None
    is_primary: bool = False


class AddressUpdate(BaseModel):
    """Data that can be updated on an address. All fields optional."""

    label: str | None = Field(None, max_length=100)
    street: str | None = Field(None, min_length=1, max_length=255)
    street2: str | None = Field(None, max_length=255)
    city: str | None = Field(None, min_length=1, max_length=100)
    state: str | None = Field(None, min_length=1, max_length=50)
    zip: str | None = Field(None, min_length=1, max_length=20)
    notes: str | None = None
    is_primary: bool | None = None


class Address(BaseModel):
    """Full address entity as stored."""

    id: UUID
    user_id: UUID
    customer_id: UUID
    label: str | None
    street: str
    street2: str | None
    city: str
    state: str
    zip: str
    notes: str | None
    is_primary: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @property
    def one_line(self) -> str:
        """Single-line address for display."""
        parts = [self.street]
        if self.street2:
            parts.append(self.street2)
        parts.append(f"{self.city}, {self.state} {self.zip}")
        return ", ".join(parts)
