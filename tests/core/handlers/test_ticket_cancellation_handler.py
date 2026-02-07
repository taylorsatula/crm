"""Tests for ticket cancellation handler.

On TicketCancelled: cancel all pending messages for the ticket.

Uses real MessageService against the DB — no mocks.
"""

from datetime import timedelta

import pytest

from core.events import TicketCancelled
from core.handlers.ticket_cancellation_handler import handle_ticket_cancelled
from core.models import (
    CustomerCreate, TicketCreate,
    ScheduledMessageCreate, MessageType, MessageStatus,
)
from utils.timezone import now_utc


@pytest.fixture
def message_service(db):
    from core.services.message_service import MessageService
    from core.audit import AuditLogger
    return MessageService(db, AuditLogger(db))


@pytest.fixture
def customer_service(db, event_bus):
    from core.services.customer_service import CustomerService
    from core.audit import AuditLogger
    return CustomerService(db, AuditLogger(db), event_bus)


@pytest.fixture
def ticket_service(db, event_bus):
    from core.services.ticket_service import TicketService
    from core.audit import AuditLogger
    return TicketService(db, AuditLogger(db), event_bus)


@pytest.fixture
def address_service(db):
    from core.services.address_service import AddressService
    from core.audit import AuditLogger
    return AddressService(db, AuditLogger(db))


@pytest.fixture
def test_customer(as_test_user, customer_service):
    return customer_service.create(CustomerCreate(first_name="Cancel", last_name="Test"))


@pytest.fixture
def test_address(as_test_user, address_service, test_customer):
    from core.models import AddressCreate
    return address_service.create(AddressCreate(
        customer_id=test_customer.id,
        street="200 Cancel Ave", city="Austin", state="TX", zip="78702"
    ))


@pytest.fixture
def test_ticket(as_test_user, ticket_service, test_customer, test_address):
    return ticket_service.create(TicketCreate(
        customer_id=test_customer.id,
        address_id=test_address.id,
        scheduled_at=now_utc() + timedelta(days=7)
    ))


@pytest.fixture
def handler(message_service):
    return handle_ticket_cancelled(message_service)


class TestTicketCancellationHandler:

    def test_cancels_all_pending_messages_for_ticket(
        self, db, as_test_user, handler, message_service, test_customer, test_ticket
    ):
        msg_1 = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            ticket_id=test_ticket.id,
            message_type=MessageType.APPOINTMENT_REMINDER,
            body="Reminder 1",
            scheduled_for=now_utc() + timedelta(days=1),
        ))
        msg_2 = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            ticket_id=test_ticket.id,
            message_type=MessageType.APPOINTMENT_CONFIRMATION,
            body="Confirmation",
            scheduled_for=now_utc() + timedelta(days=2),
        ))

        event = TicketCancelled(ticket=test_ticket)
        handler(event)

        assert message_service.get_by_id(msg_1.id).status == MessageStatus.CANCELLED
        assert message_service.get_by_id(msg_2.id).status == MessageStatus.CANCELLED

    def test_does_not_cancel_already_sent_messages(
        self, db, as_test_user, handler, message_service, test_customer, test_ticket
    ):
        sent_msg = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            ticket_id=test_ticket.id,
            message_type=MessageType.APPOINTMENT_REMINDER,
            body="Already sent",
            scheduled_for=now_utc() - timedelta(minutes=5),
        ))
        message_service.mark_sent(sent_msg.id)

        pending_msg = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            ticket_id=test_ticket.id,
            message_type=MessageType.APPOINTMENT_REMINDER,
            body="Still pending",
            scheduled_for=now_utc() + timedelta(days=1),
        ))

        event = TicketCancelled(ticket=test_ticket)
        handler(event)

        # Sent message unchanged
        assert message_service.get_by_id(sent_msg.id).status == MessageStatus.SENT
        # Pending message cancelled
        assert message_service.get_by_id(pending_msg.id).status == MessageStatus.CANCELLED

    def test_no_pending_messages_is_noop(
        self, db, as_test_user, handler, message_service, test_ticket
    ):
        """No error when ticket has zero pending messages."""
        event = TicketCancelled(ticket=test_ticket)
        handler(event)
        # No assertion needed — just verifying it doesn't raise

    def test_does_not_cancel_messages_for_other_tickets(
        self, db, as_test_user, handler, message_service,
        test_customer, test_ticket, ticket_service, test_address
    ):
        other_ticket = ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=test_address.id,
            scheduled_at=now_utc() + timedelta(days=14),
        ))

        other_msg = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            ticket_id=other_ticket.id,
            message_type=MessageType.APPOINTMENT_REMINDER,
            body="Other ticket reminder",
            scheduled_for=now_utc() + timedelta(days=1),
        ))

        event = TicketCancelled(ticket=test_ticket)
        handler(event)

        # Other ticket's message untouched
        assert message_service.get_by_id(other_msg.id).status == MessageStatus.PENDING
