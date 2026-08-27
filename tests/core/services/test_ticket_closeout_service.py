"""Integration coverage for the canonical structured ticket-closeout workflow."""

from datetime import timedelta

import pytest

from core.exceptions import TicketNotCloseableError
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
    as_test_workspace,
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
    as_test_workspace,
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
    as_test_workspace,
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


def test_closeout_already_closed_raises_not_closeable(
    as_test_workspace,
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

    with pytest.raises(TicketNotCloseableError) as exc:
        closeout_service.closeout(payload)
    assert exc.value.code == "TICKET_NOT_CLOSEABLE"
    assert exc.value.http_status == 409


def test_get_for_ticket_returns_none_before_closeout(
    as_test_workspace,
    customer_service,
    address_service,
    catalog_service,
    ticket_service,
    closeout_service,
):
    ticket = _open_ticket(customer_service, address_service, catalog_service, ticket_service)
    assert closeout_service.get_for_ticket(ticket.id) is None


def test_get_for_ticket_returns_closeout_after(
    as_test_workspace,
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


def _closeout_payload(ticket_id):
    return CloseoutRequest(
        ticket_id=ticket_id,
        actual_duration_minutes=90,
        quoted_scope_status="completed",
        result_status="achieved",
        customer_capture=CustomerCapture(customer_response="no_concern_stated"),
        next_service=NextServiceDisposition(disposition="not_applicable"),
    )


def test_list_for_customer_returns_only_that_customer_newest_first(
    as_test_workspace, customer_service, address_service, catalog_service, ticket_service, closeout_service,
):
    """list_for_customer returns the customer's closeouts, newest first, limited to 5."""
    customer_a = customer_service.create(CustomerCreate(first_name="Portrait", last_name="A"))
    address_a = address_service.create(AddressCreate(
        customer_id=customer_a.id, street="1 Way", city="Austin", state="TX", zip="78701",
    ))
    # Two closeouts for customer A.
    from core.models import TicketCreate
    ta1 = ticket_service.create(TicketCreate(
        customer_id=customer_a.id, address_id=address_a.id,
        scheduled_at=now_utc() + timedelta(days=1), scheduled_duration_minutes=90,
    ))
    ta2 = ticket_service.create(TicketCreate(
        customer_id=customer_a.id, address_id=address_a.id,
        scheduled_at=now_utc() + timedelta(days=2), scheduled_duration_minutes=90,
    ))
    closeout_service.closeout(_closeout_payload(ta1.id))
    closeout_service.closeout(_closeout_payload(ta2.id))

    # A different customer's closeout must not appear.
    customer_b = customer_service.create(CustomerCreate(first_name="Other", last_name="B"))
    address_b = address_service.create(AddressCreate(
        customer_id=customer_b.id, street="2 Way", city="Austin", state="TX", zip="78701",
    ))
    tb = ticket_service.create(TicketCreate(
        customer_id=customer_b.id, address_id=address_b.id,
        scheduled_at=now_utc() + timedelta(days=1), scheduled_duration_minutes=90,
    ))
    closeout_service.closeout(_closeout_payload(tb.id))

    rows = closeout_service.list_for_customer(customer_a.id)
    assert [r.ticket_id for r in rows] == [ta2.id, ta1.id]  # newest first
    assert all(r.ticket_id != tb.id for r in rows)
