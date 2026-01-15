"""Tests for MessageService."""

import pytest
from uuid import uuid4
from datetime import timedelta
from unittest.mock import Mock, patch

from utils.timezone import now_utc


@pytest.fixture
def message_service(db):
    """MessageService with real DB."""
    from core.services.message_service import MessageService
    from core.audit import AuditLogger

    audit = AuditLogger(db)
    return MessageService(db, audit)


@pytest.fixture
def customer_service(db):
    """CustomerService for test setup."""
    from core.services.customer_service import CustomerService
    from core.audit import AuditLogger

    return CustomerService(db, AuditLogger(db))


@pytest.fixture
def ticket_service(db):
    """TicketService for test setup."""
    from core.services.ticket_service import TicketService
    from core.audit import AuditLogger

    return TicketService(db, AuditLogger(db))


@pytest.fixture
def address_service(db):
    """AddressService for test setup."""
    from core.services.address_service import AddressService
    from core.audit import AuditLogger

    return AddressService(db, AuditLogger(db))


@pytest.fixture
def test_customer(as_test_user, customer_service):
    """Create a test customer."""
    from core.models import CustomerCreate

    customer = customer_service.create(CustomerCreate(
        first_name="Message",
        last_name="Test",
        email="message@example.com"
    ))
    yield customer
    customer_service.delete(customer.id)


@pytest.fixture
def test_address(as_test_user, address_service, test_customer):
    """Create a test address."""
    from core.models import AddressCreate

    return address_service.create(AddressCreate(
        customer_id=test_customer.id,
        street="999 Message Blvd",
        city="Austin",
        state="TX",
        zip="78705"
    ))


@pytest.fixture
def test_ticket(as_test_user, ticket_service, test_customer, test_address):
    """Create a test ticket."""
    from core.models import TicketCreate

    ticket = ticket_service.create(TicketCreate(
        customer_id=test_customer.id,
        address_id=test_address.id,
        scheduled_at=now_utc() + timedelta(days=7)
    ))
    yield ticket
    ticket_service.delete(ticket.id)


class TestMessageSchedule:
    """Tests for MessageService.schedule."""

    def test_schedules_message_with_all_fields(self, db, as_test_user, message_service, test_customer):
        """Schedules a message and verifies all fields are persisted correctly."""
        from core.models import ScheduledMessageCreate, MessageType, MessageStatus

        scheduled_for = now_utc() + timedelta(days=1)
        data = ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            subject="Your appointment reminder",
            body="Don't forget your appointment tomorrow at 9am!",
            scheduled_for=scheduled_for
        )

        message = message_service.schedule(data)

        # Verify all fields
        assert message.id is not None
        assert message.customer_id == test_customer.id
        assert message.ticket_id is None
        assert message.message_type == MessageType.CUSTOM
        assert message.subject == "Your appointment reminder"
        assert message.body == "Don't forget your appointment tomorrow at 9am!"
        assert message.status == MessageStatus.PENDING
        assert message.scheduled_for == scheduled_for
        assert message.created_at is not None

    def test_schedules_ticket_linked_message(self, db, as_test_user, message_service, test_customer, test_ticket):
        """Schedules message linked to ticket for appointment tracking."""
        from core.models import ScheduledMessageCreate, MessageType

        data = ScheduledMessageCreate(
            customer_id=test_customer.id,
            ticket_id=test_ticket.id,
            message_type=MessageType.APPOINTMENT_REMINDER,
            template_name="appointment_reminder_24h",
            scheduled_for=now_utc() + timedelta(hours=24)
        )

        message = message_service.schedule(data)

        assert message.ticket_id == test_ticket.id
        assert message.message_type == MessageType.APPOINTMENT_REMINDER
        assert message.template_name == "appointment_reminder_24h"


class TestMessageStatusTransitions:
    """Tests for message status lifecycle transitions."""

    def test_pending_to_sent_transition(self, db, as_test_user, message_service, test_customer):
        """Verifies pending -> sent transition updates status correctly."""
        from core.models import ScheduledMessageCreate, MessageType, MessageStatus

        message = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="Test body",
            scheduled_for=now_utc() - timedelta(minutes=5)
        ))

        assert message.status == MessageStatus.PENDING

        sent = message_service.mark_sent(message.id)

        assert sent.status == MessageStatus.SENT
        # Verify in database too
        refetched = message_service.get_by_id(message.id)
        assert refetched.status == MessageStatus.SENT

    def test_pending_to_failed_transition(self, db, as_test_user, message_service, test_customer):
        """Verifies pending -> failed transition when gateway error occurs."""
        from core.models import ScheduledMessageCreate, MessageType, MessageStatus

        message = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="Will fail",
            scheduled_for=now_utc() - timedelta(minutes=5)
        ))

        failed = message_service.mark_failed(message.id)

        assert failed.status == MessageStatus.FAILED
        refetched = message_service.get_by_id(message.id)
        assert refetched.status == MessageStatus.FAILED

    def test_pending_to_skipped_transition(self, db, as_test_user, message_service, test_customer):
        """Verifies pending -> skipped when message cannot be delivered (no email, etc.)."""
        from core.models import ScheduledMessageCreate, MessageType, MessageStatus

        message = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="Will skip",
            scheduled_for=now_utc() - timedelta(minutes=5)
        ))

        skipped = message_service.mark_skipped(message.id, reason="Customer has no email")

        assert skipped.status == MessageStatus.SKIPPED
        refetched = message_service.get_by_id(message.id)
        assert refetched.status == MessageStatus.SKIPPED

    def test_pending_to_cancelled_transition(self, db, as_test_user, message_service, test_customer):
        """Verifies pending -> cancelled transition."""
        from core.models import ScheduledMessageCreate, MessageType, MessageStatus

        message = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="Cancel me",
            scheduled_for=now_utc() + timedelta(days=1)
        ))

        cancelled = message_service.cancel(message.id)

        assert cancelled.status == MessageStatus.CANCELLED

    def test_cannot_cancel_sent_message(self, db, as_test_user, message_service, test_customer):
        """Cannot transition from sent back to cancelled."""
        from core.models import ScheduledMessageCreate, MessageType

        message = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="Already sent",
            scheduled_for=now_utc()
        ))
        message_service.mark_sent(message.id)

        with pytest.raises(ValueError, match="not pending"):
            message_service.cancel(message.id)

    def test_cannot_cancel_failed_message(self, db, as_test_user, message_service, test_customer):
        """Cannot transition from failed to cancelled."""
        from core.models import ScheduledMessageCreate, MessageType

        message = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="Already failed",
            scheduled_for=now_utc()
        ))
        message_service.mark_failed(message.id)

        with pytest.raises(ValueError, match="not pending"):
            message_service.cancel(message.id)


class TestPendingMessageRetrieval:
    """Tests for retrieving messages ready to be sent."""

    def test_list_pending_due_returns_only_due_messages(self, db, as_test_user, message_service, test_customer):
        """list_pending_due returns messages where scheduled_for <= now."""
        from core.models import ScheduledMessageCreate, MessageType

        # Message due 5 minutes ago
        past_msg = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="Due in past",
            scheduled_for=now_utc() - timedelta(minutes=5)
        ))

        # Message due right now
        now_msg = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="Due now",
            scheduled_for=now_utc()
        ))

        # Message due tomorrow - should NOT be returned
        future_msg = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="Due tomorrow",
            scheduled_for=now_utc() + timedelta(days=1)
        ))

        pending = message_service.list_pending_due()
        pending_ids = {m.id for m in pending}

        assert past_msg.id in pending_ids
        assert now_msg.id in pending_ids
        assert future_msg.id not in pending_ids

    def test_list_pending_due_excludes_non_pending_statuses(self, db, as_test_user, message_service, test_customer):
        """Only pending messages are returned, not sent/failed/skipped/cancelled."""
        from core.models import ScheduledMessageCreate, MessageType

        base_time = now_utc() - timedelta(minutes=5)

        sent = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="Sent",
            scheduled_for=base_time
        ))
        message_service.mark_sent(sent.id)

        failed = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="Failed",
            scheduled_for=base_time
        ))
        message_service.mark_failed(failed.id)

        skipped = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="Skipped",
            scheduled_for=base_time
        ))
        message_service.mark_skipped(skipped.id, "No email")

        cancelled = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="Cancelled",
            scheduled_for=base_time
        ))
        message_service.cancel(cancelled.id)

        pending = message_service.list_pending_due()
        pending_ids = {m.id for m in pending}

        assert sent.id not in pending_ids
        assert failed.id not in pending_ids
        assert skipped.id not in pending_ids
        assert cancelled.id not in pending_ids


class TestProcessPendingMessages:
    """Tests for the process_pending method that sends messages."""

    def test_process_pending_sends_due_messages(self, db, as_test_user, message_service, test_customer):
        """process_pending sends all due messages through email gateway."""
        from core.models import ScheduledMessageCreate, MessageType, MessageStatus

        # Create due message
        message = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            subject="Test Subject",
            body="Test body content",
            scheduled_for=now_utc() - timedelta(minutes=1)
        ))

        # Mock the email client
        mock_email_client = Mock()
        mock_email_client.send.return_value = True

        # Process with mocked email client
        results = message_service.process_pending(
            email_client=mock_email_client,
            customer_email_lookup=lambda cid: "message@example.com"
        )

        # Verify email client was called with correct params
        mock_email_client.send.assert_called_once()
        call_args = mock_email_client.send.call_args
        assert call_args.kwargs["to"] == "message@example.com"
        assert call_args.kwargs["subject"] == "Test Subject"
        assert call_args.kwargs["body"] == "Test body content"

        # Verify message is now sent
        updated = message_service.get_by_id(message.id)
        assert updated.status == MessageStatus.SENT

        # Verify results
        assert results["sent"] == 1
        assert results["failed"] == 0
        assert results["skipped"] == 0

    def test_process_pending_marks_failed_on_gateway_error(self, db, as_test_user, message_service, test_customer):
        """process_pending marks message as FAILED when gateway throws exception."""
        from core.models import ScheduledMessageCreate, MessageType, MessageStatus

        message = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            subject="Will fail",
            body="This will fail to send",
            scheduled_for=now_utc() - timedelta(minutes=1)
        ))

        # Mock email client that fails
        mock_email_client = Mock()
        mock_email_client.send.side_effect = Exception("Gateway unavailable")

        results = message_service.process_pending(
            email_client=mock_email_client,
            customer_email_lookup=lambda cid: "message@example.com"
        )

        # Verify message is marked as failed (gateway error, not skip)
        updated = message_service.get_by_id(message.id)
        assert updated.status == MessageStatus.FAILED

        # Verify results
        assert results["sent"] == 0
        assert results["failed"] == 1
        assert results["skipped"] == 0

    def test_process_pending_marks_skipped_when_no_email(self, db, as_test_user, message_service, customer_service):
        """process_pending marks SKIPPED (not failed) when customer has no email."""
        from core.models import ScheduledMessageCreate, MessageType, MessageStatus, CustomerCreate

        # Create customer without email
        customer_no_email = customer_service.create(CustomerCreate(
            first_name="No",
            last_name="Email"
        ))

        message = message_service.schedule(ScheduledMessageCreate(
            customer_id=customer_no_email.id,
            message_type=MessageType.CUSTOM,
            body="Can't send - no email",
            scheduled_for=now_utc() - timedelta(minutes=1)
        ))

        mock_email_client = Mock()

        results = message_service.process_pending(
            email_client=mock_email_client,
            customer_email_lookup=lambda cid: None  # Simulates no email
        )

        # Email client should NOT be called - we know before trying that we can't send
        mock_email_client.send.assert_not_called()

        # Message should be SKIPPED (precondition failed), not FAILED (gateway error)
        updated = message_service.get_by_id(message.id)
        assert updated.status == MessageStatus.SKIPPED

        # Verify results differentiate skipped from failed
        assert results["sent"] == 0
        assert results["failed"] == 0
        assert results["skipped"] == 1

        customer_service.delete(customer_no_email.id)

    def test_process_pending_mixed_results(self, db, as_test_user, message_service, customer_service):
        """process_pending correctly categorizes sent/failed/skipped."""
        from core.models import ScheduledMessageCreate, MessageType, MessageStatus, CustomerCreate

        # Customer with email - will succeed
        good_customer = customer_service.create(CustomerCreate(
            first_name="Good",
            last_name="Customer",
            email="good@example.com"
        ))

        # Customer without email - will skip
        no_email_customer = customer_service.create(CustomerCreate(
            first_name="No",
            last_name="Email"
        ))

        # Customer with email but gateway fails
        fail_customer = customer_service.create(CustomerCreate(
            first_name="Fail",
            last_name="Customer",
            email="fail@example.com"
        ))

        msg_success = message_service.schedule(ScheduledMessageCreate(
            customer_id=good_customer.id,
            message_type=MessageType.CUSTOM,
            body="Will succeed",
            scheduled_for=now_utc() - timedelta(minutes=1)
        ))

        msg_skip = message_service.schedule(ScheduledMessageCreate(
            customer_id=no_email_customer.id,
            message_type=MessageType.CUSTOM,
            body="Will skip",
            scheduled_for=now_utc() - timedelta(minutes=1)
        ))

        msg_fail = message_service.schedule(ScheduledMessageCreate(
            customer_id=fail_customer.id,
            message_type=MessageType.CUSTOM,
            body="Will fail",
            scheduled_for=now_utc() - timedelta(minutes=1)
        ))

        # Mock email client: succeed for good, fail for fail
        mock_email_client = Mock()
        def send_side_effect(**kwargs):
            if kwargs["to"] == "fail@example.com":
                raise Exception("Gateway error")
            return True
        mock_email_client.send.side_effect = send_side_effect

        def email_lookup(cid):
            if cid == good_customer.id:
                return "good@example.com"
            elif cid == fail_customer.id:
                return "fail@example.com"
            return None

        results = message_service.process_pending(
            email_client=mock_email_client,
            customer_email_lookup=email_lookup
        )

        # Verify statuses
        assert message_service.get_by_id(msg_success.id).status == MessageStatus.SENT
        assert message_service.get_by_id(msg_skip.id).status == MessageStatus.SKIPPED
        assert message_service.get_by_id(msg_fail.id).status == MessageStatus.FAILED

        # Verify counts
        assert results["sent"] == 1
        assert results["skipped"] == 1
        assert results["failed"] == 1

        # Cleanup
        customer_service.delete(good_customer.id)
        customer_service.delete(no_email_customer.id)
        customer_service.delete(fail_customer.id)


class TestMessageList:
    """Tests for listing messages."""

    def test_list_for_customer_returns_all_statuses(self, db, as_test_user, message_service, test_customer):
        """list_for_customer returns messages regardless of status."""
        from core.models import ScheduledMessageCreate, MessageType

        pending = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="Pending",
            scheduled_for=now_utc() + timedelta(days=1)
        ))

        sent = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="Sent",
            scheduled_for=now_utc()
        ))
        message_service.mark_sent(sent.id)

        cancelled = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="Cancelled",
            scheduled_for=now_utc() + timedelta(days=2)
        ))
        message_service.cancel(cancelled.id)

        messages = message_service.list_for_customer(test_customer.id)
        message_ids = {m.id for m in messages}

        assert pending.id in message_ids
        assert sent.id in message_ids
        assert cancelled.id in message_ids

    def test_list_for_customer_ordered_by_scheduled_for_desc(self, db, as_test_user, message_service, test_customer):
        """Messages are ordered by scheduled_for descending (newest first)."""
        from core.models import ScheduledMessageCreate, MessageType

        first = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="First",
            scheduled_for=now_utc() + timedelta(days=1)
        ))

        second = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="Second",
            scheduled_for=now_utc() + timedelta(days=3)
        ))

        third = message_service.schedule(ScheduledMessageCreate(
            customer_id=test_customer.id,
            message_type=MessageType.CUSTOM,
            body="Third",
            scheduled_for=now_utc() + timedelta(days=2)
        ))

        messages = message_service.list_for_customer(test_customer.id)

        # Should be ordered: second (day 3), third (day 2), first (day 1)
        assert messages[0].id == second.id
        assert messages[1].id == third.id
        assert messages[2].id == first.id
