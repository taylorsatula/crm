"""Structured ticket closeout contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CloseoutModel(BaseModel):
    """Strict base model for the closeout protocol."""

    model_config = ConfigDict(extra="forbid")


class CustomerCapture(CloseoutModel):
    """How the customer received the finished work."""

    customer_response: Literal[
        "positive_feedback",
        "no_concern_stated",
        "concern_stated",
        "not_reviewed",
        "contact_unavailable",
        "unknown",
    ]


class NextServiceDisposition(CloseoutModel):
    """Resolved future-service decision."""

    disposition: Literal["book", "remind", "declined", "undecided", "not_applicable"]
    note: str | None = Field(None, max_length=1000)


class CloseoutRequest(CloseoutModel):
    """Command for closing a service appointment ticket."""

    ticket_id: UUID
    actual_duration_minutes: int = Field(
        ...,
        ge=1,
        description="Actual elapsed appointment duration in minutes.",
    )
    quoted_scope_status: Literal["completed", "partially_completed", "not_completed"] = Field(
        ..., description="Whether the quoted scope was fulfilled.",
    )
    result_status: Literal[
        "achieved",
        "achieved_with_limitations",
        "not_achieved",
        "not_assessed",
    ] = Field(..., description="Quality of the service result.")
    customer_capture: CustomerCapture = Field(
        ..., description="Required customer-response pass.",
    )
    next_service: NextServiceDisposition = Field(
        ..., description="Resolved booking, reminder, decline, pending, or not-applicable.",
    )
    technician_summary: str | None = Field(
        None,
        max_length=10000,
        description="Residual context not represented by structured fields.",
    )


class TicketCloseout(CloseoutModel):
    """Persisted structured closeout aggregate."""

    id: UUID
    workspace_id: UUID
    ticket_id: UUID
    actual_duration_minutes: int
    quoted_scope_status: str
    result_status: str
    customer_response: str
    next_service_disposition: str
    next_service_note: str | None
    technician_summary: str | None
    created_at: datetime

    model_config = ConfigDict(extra="forbid", from_attributes=True)
