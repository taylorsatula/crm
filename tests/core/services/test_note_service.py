"""Tests for NoteService."""

import pytest
from uuid import uuid4
from datetime import timedelta

from utils.timezone import now_utc


@pytest.fixture
def note_service(db, event_bus):
    """NoteService with real DB."""
    from core.services.note_service import NoteService
    from core.audit import AuditLogger

    audit = AuditLogger(db)
    return NoteService(db, audit, event_bus)


@pytest.fixture
def customer_service(db, event_bus):
    """CustomerService for test setup."""
    from core.services.customer_service import CustomerService
    from core.audit import AuditLogger

    return CustomerService(db, AuditLogger(db), event_bus)


@pytest.fixture
def ticket_service(db, event_bus):
    """TicketService for test setup."""
    from core.services.ticket_service import TicketService
    from core.audit import AuditLogger

    return TicketService(db, AuditLogger(db), event_bus)


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

    customer = customer_service.create(CustomerCreate(first_name="Note", last_name="Test"))
    yield customer
    customer_service.delete(customer.id)


@pytest.fixture
def test_address(as_test_user, address_service, test_customer):
    """Create a test address."""
    from core.models import AddressCreate

    return address_service.create(AddressCreate(
        customer_id=test_customer.id,
        street="789 Note Ave",
        city="Austin",
        state="TX",
        zip="78703"
    ))


@pytest.fixture
def test_ticket(as_test_user, ticket_service, test_customer, test_address):
    """Create a test ticket."""
    from core.models import TicketCreate

    ticket = ticket_service.create(TicketCreate(
        customer_id=test_customer.id,
        address_id=test_address.id,
        scheduled_at=now_utc() + timedelta(days=1)
    ))
    yield ticket
    ticket_service.delete(ticket.id)


class TestNoteCreate:
    """Tests for NoteService.create."""

    def test_creates_customer_note(self, db, as_test_user, note_service, test_customer):
        """Creates note attached to customer."""
        from core.models import NoteCreate

        data = NoteCreate(
            customer_id=test_customer.id,
            content="Customer prefers morning appointments."
        )

        note = note_service.create(data)

        assert note.customer_id == test_customer.id
        assert note.ticket_id is None
        assert note.content == "Customer prefers morning appointments."
        assert note.processed_at is None

    def test_creates_ticket_note(self, db, as_test_user, note_service, test_ticket):
        """Creates note attached to ticket."""
        from core.models import NoteCreate

        data = NoteCreate(
            ticket_id=test_ticket.id,
            content="Used extra squeegee for stubborn spots."
        )

        note = note_service.create(data)

        assert note.ticket_id == test_ticket.id
        assert note.customer_id is None
        assert note.content == "Used extra squeegee for stubborn spots."

    def test_rejects_no_parent(self, db, as_test_user, note_service):
        """Rejects note with no parent."""
        from core.models import NoteCreate
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="Exactly one"):
            NoteCreate(content="Orphan note")

    def test_rejects_both_parents(self, db, as_test_user, note_service, test_customer, test_ticket):
        """Rejects note with both customer and ticket."""
        from core.models import NoteCreate
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="Exactly one"):
            NoteCreate(
                customer_id=test_customer.id,
                ticket_id=test_ticket.id,
                content="Invalid dual parent"
            )


class TestNoteGet:
    """Tests for NoteService.get_by_id."""

    def test_gets_note(self, db, as_test_user, note_service, test_customer):
        """Gets note by ID."""
        from core.models import NoteCreate

        created = note_service.create(NoteCreate(
            customer_id=test_customer.id,
            content="Test note content."
        ))

        fetched = note_service.get_by_id(created.id)

        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.content == "Test note content."

    def test_returns_none_for_missing(self, db, as_test_user, note_service):
        """Returns None for non-existent note."""
        result = note_service.get_by_id(uuid4())
        assert result is None


class TestNoteList:
    """Tests for NoteService list methods."""

    def test_lists_customer_notes(self, db, as_test_user, note_service, test_customer):
        """Lists all notes for a customer."""
        from core.models import NoteCreate

        note_service.create(NoteCreate(
            customer_id=test_customer.id,
            content="First customer note"
        ))
        note_service.create(NoteCreate(
            customer_id=test_customer.id,
            content="Second customer note"
        ))

        notes = note_service.list_for_customer(test_customer.id)

        assert len(notes) >= 2
        assert all(n.customer_id == test_customer.id for n in notes)

    def test_lists_ticket_notes(self, db, as_test_user, note_service, test_ticket):
        """Lists all notes for a ticket."""
        from core.models import NoteCreate

        note_service.create(NoteCreate(
            ticket_id=test_ticket.id,
            content="First ticket note"
        ))
        note_service.create(NoteCreate(
            ticket_id=test_ticket.id,
            content="Second ticket note"
        ))

        notes = note_service.list_for_ticket(test_ticket.id)

        assert len(notes) >= 2
        assert all(n.ticket_id == test_ticket.id for n in notes)

    def test_excludes_deleted_notes(self, db, as_test_user, note_service, test_customer):
        """list methods exclude soft-deleted notes."""
        from core.models import NoteCreate

        note1 = note_service.create(NoteCreate(
            customer_id=test_customer.id,
            content="Keep this note"
        ))
        note2 = note_service.create(NoteCreate(
            customer_id=test_customer.id,
            content="Delete this note"
        ))

        note_service.delete(note2.id)

        notes = note_service.list_for_customer(test_customer.id)
        note_ids = [n.id for n in notes]

        assert note1.id in note_ids
        assert note2.id not in note_ids


class TestNoteDelete:
    """Tests for NoteService.delete."""

    def test_deletes_note(self, db, as_test_user, note_service, test_customer):
        """Soft deletes note."""
        from core.models import NoteCreate

        note = note_service.create(NoteCreate(
            customer_id=test_customer.id,
            content="Note to delete"
        ))

        result = note_service.delete(note.id)
        assert result is True

        # Should no longer be returned by get_by_id
        fetched = note_service.get_by_id(note.id)
        assert fetched is None

    def test_returns_false_for_missing(self, db, as_test_user, note_service):
        """Returns False when deleting non-existent note."""
        result = note_service.delete(uuid4())
        assert result is False


class TestNoteProcessed:
    """Tests for marking notes as processed."""

    def test_mark_processed(self, db, as_test_user, note_service, test_customer):
        """Marks note as processed by LLM extraction."""
        from core.models import NoteCreate

        note = note_service.create(NoteCreate(
            customer_id=test_customer.id,
            content="Customer mentioned they have 12 windows."
        ))

        assert note.processed_at is None

        updated = note_service.mark_processed(note.id)

        assert updated.processed_at is not None

    def test_list_unprocessed(self, db, as_test_user, note_service, test_customer):
        """Lists notes that haven't been processed."""
        from core.models import NoteCreate

        note1 = note_service.create(NoteCreate(
            customer_id=test_customer.id,
            content="Process this one"
        ))
        note2 = note_service.create(NoteCreate(
            customer_id=test_customer.id,
            content="Already processed"
        ))

        note_service.mark_processed(note2.id)

        unprocessed = note_service.list_unprocessed(limit=100)
        unprocessed_ids = [n.id for n in unprocessed]

        assert note1.id in unprocessed_ids
        assert note2.id not in unprocessed_ids

    def test_list_unprocessed_for_ticket(self, db, as_test_user, note_service, test_customer, test_ticket):
        """Returns only unprocessed notes for a specific ticket."""
        from core.models import NoteCreate

        unprocessed_note = note_service.create(NoteCreate(
            ticket_id=test_ticket.id,
            content="Not yet processed"
        ))
        processed_note = note_service.create(NoteCreate(
            ticket_id=test_ticket.id,
            content="Already processed"
        ))
        note_service.mark_processed(processed_note.id)

        customer_note = note_service.create(NoteCreate(
            customer_id=test_customer.id,
            content="Customer note, no ticket"
        ))

        result = note_service.list_unprocessed_for_ticket(test_ticket.id)
        result_ids = [n.id for n in result]

        assert unprocessed_note.id in result_ids
        assert processed_note.id not in result_ids
        assert customer_note.id not in result_ids

    def test_list_unprocessed_for_ticket_empty(self, db, as_test_user, note_service, test_ticket):
        """Returns empty list when ticket has no unprocessed notes."""
        result = note_service.list_unprocessed_for_ticket(test_ticket.id)
        assert result == []

    def test_list_unprocessed_for_ticket_excludes_deleted(self, db, as_test_user, note_service, test_ticket):
        """Deleted notes are excluded even if unprocessed."""
        from core.models import NoteCreate

        note = note_service.create(NoteCreate(
            ticket_id=test_ticket.id,
            content="Will be deleted"
        ))
        note_service.delete(note.id)

        result = note_service.list_unprocessed_for_ticket(test_ticket.id)
        assert result == []


class TestNoteEventPublishing:
    """Verify that NoteService publishes domain events to the bus."""

    def test_create_publishes_note_created(self, db, as_test_user, note_service, event_bus, test_customer):
        from core.models import NoteCreate
        from core.events import NoteCreated

        received = []
        event_bus.subscribe("NoteCreated", received.append)

        note = note_service.create(NoteCreate(
            customer_id=test_customer.id,
            content="Elderly woman, dog named Biscuit"
        ))

        assert len(received) == 1
        assert isinstance(received[0], NoteCreated)
        assert received[0].note.id == note.id
        assert received[0].note.content == "Elderly woman, dog named Biscuit"
