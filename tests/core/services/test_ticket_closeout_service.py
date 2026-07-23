"""Integration coverage for the canonical structured ticket-closeout workflow."""

from datetime import timedelta

import pytest

from core.models import (
    AddressCreate,
    CloseoutRequest,
    CustomerCapture,
    CustomerCreate,
    NextServiceDisposition,
    ServiceCreate,
    TicketCreate,
)
from utils.timezone import now_utc


def _open_ticket(customer_service, address_service, catalog_service, ticket_service):
    customer = customer_service.create(CustomerCreate(first_name="Closeout", last_name="Customer"))
    address = address_service.create(AddressCreate(
        customer_id=customer.id,
        street="1 Reconcile Way",
        city="Austin",
        state="TX",
        zip="78701",
    ))
    ticket = ticket_service.create(TicketCreate(
        customer_id=customer.id,
        address_id=address.id,
        scheduled_at=now_utc() + timedelta(days=1),
        scheduled_duration_minutes=90,
    ))
    return ticket


def test_closeout_persists_aggregate_and_closes_ticket(
    customer_service,
    address_service,
    catalog_service,
    ticket_service,
    closeout_service,
):
    ticket = _open_ticket(customer_service, address_service, catalog_service, ticket_service)

    result = closeout_service.closeout(CloseoutRequest(
        ticket_id=ticket.id,
        actual_duration_minutes=90,
        quoted_scope_status="completed",
        result_status="achieved",
        customer_capture=CustomerCapture(customer_response="no_concern_stated"),
        next_service=NextServiceDisposition(disposition="not_applicable"),
    ))

    assert result["ticket"]["status"] == "completed"
    assert result["ticket"]["actual_duration_minutes"] == 90
    assert result["closeout"]["quoted_scope_status"] == "completed"
    assert result["closeout"]["result_status"] == "achieved"
    assert result["closeout"]["customer_response"] == "no_concern_stated"
    assert result["closeout"]["next_service_disposition"] == "not_applicable"


def test_closeout_records_next_service_booked(
    customer_service,
    address_service,
    catalog_service,
    ticket_service,
    closeout_service,
):
    ticket = _open_ticket(customer_service, address_service, catalog_service, ticket_service)

    result = closeout_service.closeout(CloseoutRequest(
        ticket_id=ticket.id,
        actual_duration_minutes=60,
        quoted_scope_status="completed",
        result_status="achieved",
        customer_capture=CustomerCapture(customer_response="positive_feedback"),
        next_service=NextServiceDisposition(
            disposition="book",
            note="Same scope next spring",
        ),
    ))

    assert result["closeout"]["next_service_disposition"] == "book"
    assert result["closeout"]["next_service_note"] == "Same scope next spring"


def test_closeout_partially_completed_scope(
    customer_service,
    address_service,
    catalog_service,
    ticket_service,
    closeout_service,
):
    ticket = _open_ticket(customer_service, address_service, catalog_service, ticket_service)

    result = closeout_service.closeout(CloseoutRequest(
        ticket_id=ticket.id,
        actual_duration_minutes=45,
        quoted_scope_status="partially_completed",
        result_status="achieved_with_limitations",
        customer_capture=CustomerCapture(customer_response="no_concern_stated"),
        next_service=NextServiceDisposition(disposition="undecided"),
        technician_summary="Interior windows inaccessible due to furniture; exterior completed.",
    ))

    assert result["closeout"]["quoted_scope_status"] == "partially_completed"
    assert result["closeout"]["result_status"] == "achieved_with_limitations"
    assert result["closeout"]["technician_summary"] is not None


def test_closeout_already_closed_returns_400(
    customer_service,
    address_service,
    catalog_service,
    ticket_service,
    closeout_service,
):
    ticket = _open_ticket(customer_service, address_service, catalog_service, ticket_service)
    payload = CloseoutRequest(
        ticket_id=ticket.id,
        actual_duration_minutes=90,
        quoted_scope_status="completed",
        result_status="achieved",
        customer_capture=CustomerCapture(customer_response="unknown"),
        next_service=NextServiceDisposition(disposition="not_applicable"),
    )

    first = closeout_service.closeout(payload)
    assert first["ticket"]["status"] == "completed"

    with pytest.raises(Exception):
        closeout_service.closeout(payload)


def test_get_for_ticket_returns_none_before_closeout(
    customer_service,
    address_service,
    catalog_service,
    ticket_service,
    closeout_service,
):
    ticket = _open_ticket(customer_service, address_service, catalog_service, ticket_service)
    assert closeout_service.get_for_ticket(ticket.id) is None


def test_get_for_ticket_returns_closeout_after(
    customer_service,
    address_service,
    catalog_service,
    ticket_service,
    closeout_service,
):
    ticket = _open_ticket(customer_service, address_service, catalog_service, ticket_service)
    closeout_service.closeout(CloseoutRequest(
        ticket_id=ticket.id,
        actual_duration_minutes=90,
        quoted_scope_status="completed",
        result_status="achieved",
        customer_capture=CustomerCapture(customer_response="no_concern_stated"),
        next_service=NextServiceDisposition(disposition="remind", note="Six-month checkup"),
    ))
    closeout = closeout_service.get_for_ticket(ticket.id)
    assert closeout is not None
    assert closeout.ticket_id == ticket.id
    assert closeout.next_service_disposition == "remind"
