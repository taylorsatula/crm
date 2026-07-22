"""Typed contracts for immutable Square history imports."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class SquareCustomerImport(BaseModel):
    """Square customer data required by the CRM import boundary."""

    square_id: str = Field(..., min_length=1, max_length=192)
    first_name: str | None = Field(None, max_length=255)
    last_name: str | None = Field(None, max_length=255)
    business_name: str | None = Field(None, max_length=255)
    email: str | None = Field(None, max_length=320)
    phone: str | None = Field(None, max_length=50)
    address: str | None = Field(None, max_length=500)
    notes: str | None = Field(None, max_length=10000)


class SquareServiceImport(BaseModel):
    """Square catalog variation mapped to a CRM service."""

    square_id: str = Field(..., min_length=1, max_length=192)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    price_cents: int | None = Field(None, ge=0)


class SquareBookingSegmentImport(BaseModel):
    """One booked service segment."""

    square_service_id: str = Field(..., min_length=1, max_length=192)
    name: str = Field(..., min_length=1, max_length=255)
    # Zero is valid: Square records add-on services that extend the service
    # list without extending the appointment as 0-minute segments.
    duration_minutes: int = Field(..., ge=0)


class SquareBookingImport(BaseModel):
    """Square appointment imported as a historical CRM ticket."""

    square_id: str = Field(..., min_length=1, max_length=192)
    square_customer_id: str = Field(..., min_length=1, max_length=192)
    start_at: datetime
    duration_minutes: int = Field(..., ge=1)
    status: str = Field(..., pattern="^(completed|cancelled|scheduled)$")
    closed_at: datetime | None = None
    notes: str | None = Field(None, max_length=10000)
    location_type: str = Field(..., min_length=1, max_length=50)
    location_label: str | None = Field(None, max_length=255)
    location_address: dict[str, str] | None = None
    segments: list[SquareBookingSegmentImport] = Field(default_factory=list)
    matched_square_order_id: str | None = Field(None, max_length=192)
    match_method: str | None = Field(
        None, pattern="^(customer_service_sequence|manual_review)$"
    )


class SquareSaleLineImport(BaseModel):
    """One immutable line from a Square order."""

    square_uid: str = Field(..., min_length=1, max_length=192)
    square_catalog_object_id: str | None = Field(None, max_length=192)
    name: str = Field(..., min_length=1, max_length=500)
    quantity: Decimal = Field(..., gt=0)
    base_price_cents: int | None = Field(None, ge=0)
    total_price_cents: int = Field(..., ge=0)
    total_tax_cents: int = Field(0, ge=0)
    total_discount_cents: int = Field(0, ge=0)
    total_service_charge_cents: int = Field(0, ge=0)


class SquareSaleImport(BaseModel):
    """A verified Square order retained as customer financial history."""

    square_id: str = Field(..., min_length=1, max_length=192)
    square_customer_id: str | None = Field(None, max_length=192)
    occurred_at: datetime
    status: str = Field(..., min_length=1, max_length=50)
    currency: str = Field(..., min_length=3, max_length=3)
    subtotal_cents: int = Field(0, ge=0)
    tax_cents: int = Field(0, ge=0)
    discount_cents: int = Field(0, ge=0)
    tip_cents: int = Field(0, ge=0)
    service_charge_cents: int = Field(0, ge=0)
    total_cents: int = Field(0, ge=0)
    paid_cents: int = Field(0, ge=0)
    refunded_cents: int = Field(0, ge=0)
    receipt_url: str | None = Field(None, max_length=2048)
    matched_square_booking_id: str | None = Field(None, max_length=192)
    match_method: str | None = Field(
        None, pattern="^(customer_service_sequence|manual_review)$"
    )
    lines: list[SquareSaleLineImport] = Field(default_factory=list)


class SquareImportBatchRequest(BaseModel):
    """Idempotent chunk sent by CRM Mira to the private CRM service."""

    import_run_id: UUID
    customers: list[SquareCustomerImport] = Field(default_factory=list)
    services: list[SquareServiceImport] = Field(default_factory=list)
    bookings: list[SquareBookingImport] = Field(default_factory=list)
    sales: list[SquareSaleImport] = Field(default_factory=list)


class SquareImportBatchResult(BaseModel):
    """Counts returned after applying one idempotent import chunk."""

    customers_created: int = 0
    services_created: int = 0
    tickets_created: int = 0
    sales_created: int = 0
    existing_records: int = 0


class SquareSaleLine(BaseModel):
    """Persisted Square sale line."""

    id: UUID
    square_uid: str
    square_catalog_object_id: str | None
    name: str
    quantity: Decimal
    base_price_cents: int | None
    total_price_cents: int
    total_tax_cents: int
    total_discount_cents: int
    total_service_charge_cents: int

    model_config = {"from_attributes": True}


class SquareSale(BaseModel):
    """Persisted Square order with its immutable lines."""

    id: UUID
    workspace_id: UUID
    customer_id: UUID | None
    square_order_id: str
    occurred_at: datetime
    status: str
    currency: str
    subtotal_cents: int
    tax_cents: int
    discount_cents: int
    tip_cents: int
    service_charge_cents: int
    total_cents: int
    paid_cents: int
    refunded_cents: int
    receipt_url: str | None
    matched_ticket_id: UUID | None
    match_method: str | None
    created_at: datetime
    lines: list[SquareSaleLine] = Field(default_factory=list)

    model_config = {"from_attributes": True}
