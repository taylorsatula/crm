"""Unified API response format and error handling."""

from typing import Any
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from utils.timezone import now_utc


class APIError(BaseModel):
    """Error details in API response."""

    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error message")


class APIMeta(BaseModel):
    """Metadata included in every API response."""

    timestamp: datetime = Field(..., description="Response timestamp (UTC)")
    request_id: str = Field(..., description="Unique request identifier for tracing")


class APIResponse(BaseModel):
    """
    Unified response format for all API endpoints.

    Every endpoint returns this structure, making client parsing predictable.
    """

    success: bool
    data: Any | None = None
    error: APIError | None = None
    meta: APIMeta


def success_response(data: Any, request_id: str | None = None) -> APIResponse:
    """Create a success response."""
    return APIResponse(
        success=True,
        data=data,
        error=None,
        meta=APIMeta(
            timestamp=now_utc(),
            request_id=request_id or str(uuid4()),
        ),
    )


def error_response(
    code: str,
    message: str,
    request_id: str | None = None,
    data: Any | None = None,
) -> APIResponse:
    """Create an error response."""
    return APIResponse(
        success=False,
        data=data,
        error=APIError(code=code, message=message),
        meta=APIMeta(
            timestamp=now_utc(),
            request_id=request_id or str(uuid4()),
        ),
    )


class ErrorCodes:
    """
    Standard error codes for consistent error handling.

    Keep codes aligned with the private service contract.
    """

    # Internal service boundary
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"

    # Resource Errors
    NOT_FOUND = "NOT_FOUND"
    ALREADY_EXISTS = "ALREADY_EXISTS"

    # Validation Errors
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_REQUEST = "INVALID_REQUEST"

    # Ticket Lifecycle
    TICKET_IMMUTABLE = "TICKET_IMMUTABLE"
    TICKET_NOT_CLOCKABLE = "TICKET_NOT_CLOCKABLE"
    TICKET_NOT_CLOSEABLE = "TICKET_NOT_CLOSEABLE"
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"
    TICKET_SCHEDULE_UNAVAILABLE = "TICKET_SCHEDULE_UNAVAILABLE"
    TICKET_SCHEDULE_CONFLICT = "TICKET_SCHEDULE_CONFLICT"

    # Contact & Address
    CONTACT_HAS_DEPENDENCIES = "CONTACT_HAS_DEPENDENCIES"
    ADDRESS_IN_USE = "ADDRESS_IN_USE"

    # Invoice
    INVOICE_ALREADY_SENT = "INVOICE_ALREADY_SENT"
    INVOICE_ALREADY_PAID = "INVOICE_ALREADY_PAID"

    # Service Catalog
    SERVICE_IN_USE = "SERVICE_IN_USE"

    # Scheduled Message
    MESSAGE_ALREADY_SENT = "MESSAGE_ALREADY_SENT"
    MESSAGE_SEND_FAILED = "MESSAGE_SEND_FAILED"

    # Lead
    LEAD_NOT_FOUND = "LEAD_NOT_FOUND"
    LEAD_ALREADY_CONVERTED = "LEAD_ALREADY_CONVERTED"
    LEAD_ARCHIVED = "LEAD_ARCHIVED"
    LEAD_INVALID_TRANSITION = "LEAD_INVALID_TRANSITION"

    # Quote
    QUOTE_NOT_FOUND = "QUOTE_NOT_FOUND"
    QUOTE_DRAFT_ONLY = "QUOTE_DRAFT_ONLY"
    QUOTE_ALREADY_TERMINAL = "QUOTE_ALREADY_TERMINAL"
    QUOTE_INVALID_TRANSITION = "QUOTE_INVALID_TRANSITION"

    # Model Authorization
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    AUTHORIZATION_PENDING = "AUTHORIZATION_PENDING"

    # Infrastructure
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
