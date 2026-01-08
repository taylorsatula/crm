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


def success_response(data: Any) -> APIResponse:
    """Create a success response."""
    return APIResponse(
        success=True,
        data=data,
        error=None,
        meta=APIMeta(
            timestamp=now_utc(),
            request_id=str(uuid4()),
        ),
    )


def error_response(code: str, message: str) -> APIResponse:
    """Create an error response."""
    return APIResponse(
        success=False,
        data=None,
        error=APIError(code=code, message=message),
        meta=APIMeta(
            timestamp=now_utc(),
            request_id=str(uuid4()),
        ),
    )


class ErrorCodes:
    """
    Standard error codes for consistent error handling.

    See docs/ERROR_CODES.md for complete documentation including
    when to use each code and client handling guidance.
    """

    # Authentication & Authorization
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    INVALID_TOKEN = "INVALID_TOKEN"
    RATE_LIMITED = "RATE_LIMITED"

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

    # Model Authorization
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    AUTHORIZATION_PENDING = "AUTHORIZATION_PENDING"

    # Infrastructure
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
