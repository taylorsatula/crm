"""Tests for EventBus."""

import logging
from uuid import uuid4
from datetime import timedelta

import pytest

from core.event_bus import EventBus
from core.events import TicketCreated, TicketCompleted, CustomerCreated
from core.models import (
    Ticket, TicketStatus, ConfirmationStatus,
    Customer,
)
from utils.timezone import now_utc


# =============================================================================
# FIXTURES — lightweight in-memory stubs, no DB needed
# =============================================================================


@pytest.fixture
def _customer():
    now = now_utc()
    return Customer(
        id=uuid4(), user_id=uuid4(),
        first_name="Test", last_name="Customer",
        business_name=None, email=None, phone=None,
        address=None, reference_id=None, notes=None,
        preferred_contact_method=None, preferred_time_of_day=None,
        referred_by=None, stripe_customer_id=None,
        created_at=now, updated_at=now, deleted_at=None,
    )


@pytest.fixture
def _ticket(_customer):
    now = now_utc()
    return Ticket(
        id=uuid4(), user_id=_customer.user_id,
        customer_id=_customer.id, address_id=uuid4(),
        status=TicketStatus.SCHEDULED,
        scheduled_at=now + timedelta(hours=1),
        scheduled_duration_minutes=60,
        confirmation_status=ConfirmationStatus.PENDING,
        confirmation_sent_at=None, confirmed_at=None,
        clock_in_at=None, clock_out_at=None,
        actual_duration_minutes=None,
        notes=None, closed_at=None, is_price_estimated=False,
        created_at=now, updated_at=now, deleted_at=None,
    )


# =============================================================================
# SUBSCRIBE AND PUBLISH
# =============================================================================


class TestSubscribeAndPublish:

    def test_single_handler_receives_the_exact_event_object(self, _ticket, as_test_user):
        bus = EventBus()
        received = []
        bus.subscribe("TicketCreated", received.append)

        event = TicketCreated.create(ticket=_ticket)
        bus.publish(event)

        assert len(received) == 1
        assert received[0] is event

    def test_handler_can_read_payload_fields(self, _ticket, as_test_user):
        bus = EventBus()
        ticket_ids = []
        bus.subscribe("TicketCreated", lambda e: ticket_ids.append(e.ticket.id))

        event = TicketCreated.create(ticket=_ticket)
        bus.publish(event)

        assert ticket_ids == [_ticket.id]

    def test_multiple_handlers_called_in_subscription_order(self, _ticket, as_test_user):
        bus = EventBus()
        order = []
        bus.subscribe("TicketCreated", lambda e: order.append("A"))
        bus.subscribe("TicketCreated", lambda e: order.append("B"))
        bus.subscribe("TicketCreated", lambda e: order.append("C"))

        bus.publish(TicketCreated.create(ticket=_ticket))

        assert order == ["A", "B", "C"]

    def test_type_isolation_only_matching_subscribers_called(self, _ticket, _customer, as_test_user):
        bus = EventBus()
        ticket_calls = []
        customer_calls = []
        bus.subscribe("TicketCreated", ticket_calls.append)
        bus.subscribe("CustomerCreated", customer_calls.append)

        bus.publish(TicketCreated.create(ticket=_ticket))

        assert len(ticket_calls) == 1
        assert customer_calls == []

    def test_no_subscribers_does_not_raise(self, _ticket, as_test_user):
        bus = EventBus()
        bus.publish(TicketCreated.create(ticket=_ticket))

    def test_two_publishes_deliver_two_distinct_events(self, _ticket, as_test_user):
        bus = EventBus()
        received = []
        bus.subscribe("TicketCreated", received.append)

        event_1 = TicketCreated.create(ticket=_ticket)
        event_2 = TicketCreated.create(ticket=_ticket)
        bus.publish(event_1)
        bus.publish(event_2)

        assert len(received) == 2
        assert received[0] is event_1
        assert received[1] is event_2
        assert received[0].event_id != received[1].event_id


# =============================================================================
# HANDLER ERROR ISOLATION
# =============================================================================


class TestHandlerErrorIsolation:

    def test_handler_exception_does_not_propagate(self, _ticket, as_test_user):
        bus = EventBus()
        bus.subscribe("TicketCreated", lambda e: (_ for _ in ()).throw(RuntimeError("boom")))

        # Must not raise
        bus.publish(TicketCreated.create(ticket=_ticket))

    def test_handler_exception_is_logged_with_event_type_and_event_id(self, _ticket, caplog, as_test_user):
        bus = EventBus()

        def failing_handler(event):
            raise ValueError("extraction failed")

        bus.subscribe("TicketCreated", failing_handler)

        with caplog.at_level(logging.ERROR, logger="core.event_bus"):
            event = TicketCreated.create(ticket=_ticket)
            bus.publish(event)

        assert "extraction failed" in caplog.text
        assert "TicketCreated" in caplog.text
        assert event.event_id in caplog.text

    def test_second_handler_runs_after_first_handler_raises(self, _ticket, as_test_user):
        bus = EventBus()
        second_handler_ticket_ids = []

        def failing_handler(event):
            raise RuntimeError("fail")

        bus.subscribe("TicketCreated", failing_handler)
        bus.subscribe("TicketCreated", lambda e: second_handler_ticket_ids.append(e.ticket.id))

        bus.publish(TicketCreated.create(ticket=_ticket))

        assert second_handler_ticket_ids == [_ticket.id]

    def test_all_handlers_run_even_if_multiple_fail(self, _ticket, as_test_user):
        bus = EventBus()
        results = []

        bus.subscribe("TicketCompleted", lambda e: (_ for _ in ()).throw(RuntimeError("fail 1")))
        bus.subscribe("TicketCompleted", lambda e: results.append("survived_1"))
        bus.subscribe("TicketCompleted", lambda e: (_ for _ in ()).throw(RuntimeError("fail 2")))
        bus.subscribe("TicketCompleted", lambda e: results.append("survived_2"))

        bus.publish(TicketCompleted.create(ticket=_ticket))

        assert results == ["survived_1", "survived_2"]
