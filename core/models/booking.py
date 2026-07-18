"""Typed input and output contracts for canonical booking workflows."""

from datetime import datetime

from pydantic import BaseModel, Field

from core.models.address import Address
from core.models.customer import Customer, CustomerCreate
from core.models.line_item import LineItem, LineItemCreate
from core.models.ticket import Ticket


class BookingAddressCreate(BaseModel):
    """Service address fields for a customer created by the same workflow."""

    label: str | None = Field(None, max_length=100)
    street: str = Field(..., min_length=1, max_length=255)
    street2: str | None = Field(None, max_length=255)
    city: str = Field(..., min_length=1, max_length=100)
    state: str = Field(..., min_length=1, max_length=50)
    zip: str = Field(..., min_length=1, max_length=20)
    notes: str | None = None


class BookingTicketCreate(BaseModel):
    """Appointment fields whose customer and address are created by the workflow."""

    scheduled_at: datetime
    scheduled_duration_minutes: int | None = Field(None, ge=1)
    is_price_estimated: bool = False
    notes: str | None = None


class NewCustomerJobBookingCreate(BaseModel):
    """Create one new customer, address, ticket, and its initial job scope."""

    customer: CustomerCreate
    address: BookingAddressCreate
    ticket: BookingTicketCreate
    line_items: list[LineItemCreate] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="One or more catalog services to attach to the new ticket",
    )


class NewCustomerJobBooking(BaseModel):
    """All entities committed by a new-customer booking workflow."""

    customer: Customer
    address: Address
    ticket: Ticket
    line_items: list[LineItem]
