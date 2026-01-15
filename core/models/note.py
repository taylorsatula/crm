"""Note domain models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class NoteCreate(BaseModel):
    """Data required to create a note."""

    content: str = Field(..., min_length=1, max_length=50000)
    customer_id: UUID | None = None
    ticket_id: UUID | None = None

    @model_validator(mode="after")
    def require_parent(self) -> "NoteCreate":
        """Ensure exactly one parent is specified."""
        has_customer = self.customer_id is not None
        has_ticket = self.ticket_id is not None

        if has_customer == has_ticket:  # Both or neither
            raise ValueError("Exactly one of customer_id or ticket_id must be provided")
        return self


class Note(BaseModel):
    """Full note entity as stored."""

    id: UUID
    user_id: UUID
    customer_id: UUID | None
    ticket_id: UUID | None
    content: str
    processed_at: datetime | None
    created_at: datetime
    deleted_at: datetime | None = None

    model_config = {"from_attributes": True}
