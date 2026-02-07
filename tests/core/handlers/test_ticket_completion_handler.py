"""Tests for ticket completion handler.

On TicketCompleted: extract attributes from unprocessed notes,
persist them via real services, and mark notes as processed.

Only the LLM extractor is mocked — it's the external boundary.
All other services use real DB-backed instances.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest

from core.events import TicketCompleted
from core.handlers.ticket_completion_handler import handle_ticket_completed
from core.models import (
    CustomerCreate, TicketCreate, NoteCreate,
    AttributeCreate,
)
from core.models.attribute import ExtractedAttributes
from utils.timezone import now_utc


@pytest.fixture
def note_service(db, event_bus):
    from core.services.note_service import NoteService
    from core.audit import AuditLogger
    return NoteService(db, AuditLogger(db), event_bus)


@pytest.fixture
def attribute_service(db):
    from core.services.attribute_service import AttributeService
    from core.audit import AuditLogger
    return AttributeService(db, AuditLogger(db))


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
def mock_extractor():
    return Mock()


@pytest.fixture
def test_customer(as_test_user, customer_service):
    return customer_service.create(CustomerCreate(first_name="Handler", last_name="Test"))


@pytest.fixture
def test_address(as_test_user, address_service, test_customer):
    from core.models import AddressCreate
    return address_service.create(AddressCreate(
        customer_id=test_customer.id,
        street="100 Handler St", city="Austin", state="TX", zip="78701"
    ))


@pytest.fixture
def test_ticket(as_test_user, ticket_service, test_customer, test_address):
    return ticket_service.create(TicketCreate(
        customer_id=test_customer.id,
        address_id=test_address.id,
        scheduled_at=now_utc() + timedelta(days=1)
    ))


@pytest.fixture
def handler(mock_extractor, attribute_service, note_service):
    return handle_ticket_completed(mock_extractor, attribute_service, note_service)


class TestTicketCompletionHandler:

    def test_extracts_and_persists_attributes_from_note(
        self, db, as_test_user, handler, mock_extractor,
        note_service, attribute_service,
        test_customer, test_ticket
    ):
        """Full integration: note created → handler extracts → attributes persisted in DB."""
        note = note_service.create(NoteCreate(
            ticket_id=test_ticket.id,
            content="Elderly woman, dog named Biscuit"
        ))

        mock_extractor.extract_attributes.return_value = ExtractedAttributes(
            attributes={"pet": {"type": "dog", "name": "Biscuit"}, "customer_demographic": "elderly"},
            raw_response='{"pet": {"type": "dog", "name": "Biscuit"}, "customer_demographic": "elderly"}',
            confidence=Decimal("0.80"),
        )

        event = TicketCompleted(ticket=test_ticket)
        handler(event)

        # Extractor called with exact note content
        mock_extractor.extract_attributes.assert_called_once_with("Elderly woman, dog named Biscuit")

        # Attributes actually persisted in DB
        attrs = attribute_service.list_for_customer(test_customer.id)
        attr_keys = {a.key for a in attrs}
        assert "pet" in attr_keys
        assert "customer_demographic" in attr_keys

        pet_attr = next(a for a in attrs if a.key == "pet")
        assert pet_attr.value == {"type": "dog", "name": "Biscuit"}
        assert pet_attr.source_type == "llm_extracted"
        assert pet_attr.source_note_id == note.id
        assert pet_attr.confidence == Decimal("0.80")

        # Note actually marked processed in DB
        updated_note = note_service.get_by_id(note.id)
        assert updated_note.processed_at is not None

    def test_processes_multiple_notes_and_marks_each_processed(
        self, db, as_test_user, handler, mock_extractor,
        note_service, test_customer, test_ticket
    ):
        note_1 = note_service.create(NoteCreate(
            ticket_id=test_ticket.id, content="Note one"
        ))
        note_2 = note_service.create(NoteCreate(
            ticket_id=test_ticket.id, content="Note two"
        ))

        mock_extractor.extract_attributes.return_value = ExtractedAttributes(
            attributes={"key": "val"},
            raw_response='{"key": "val"}',
            confidence=Decimal("0.80"),
        )

        event = TicketCompleted(ticket=test_ticket)
        handler(event)

        assert mock_extractor.extract_attributes.call_count == 2

        assert note_service.get_by_id(note_1.id).processed_at is not None
        assert note_service.get_by_id(note_2.id).processed_at is not None

    def test_skips_already_processed_notes(
        self, db, as_test_user, handler, mock_extractor,
        note_service, test_ticket
    ):
        """Already-processed notes are excluded at the SQL level."""
        processed_note = note_service.create(NoteCreate(
            ticket_id=test_ticket.id, content="Already done"
        ))
        note_service.mark_processed(processed_note.id)

        unprocessed_note = note_service.create(NoteCreate(
            ticket_id=test_ticket.id, content="Still fresh"
        ))

        mock_extractor.extract_attributes.return_value = ExtractedAttributes(
            attributes={}, raw_response="{}", confidence=Decimal("0.80"),
        )

        event = TicketCompleted(ticket=test_ticket)
        handler(event)

        # Only the unprocessed note should trigger extraction
        mock_extractor.extract_attributes.assert_called_once_with("Still fresh")

    def test_no_notes_does_not_call_extractor(
        self, db, as_test_user, handler, mock_extractor, test_ticket
    ):
        event = TicketCompleted(ticket=test_ticket)
        handler(event)

        mock_extractor.extract_attributes.assert_not_called()

    def test_empty_extraction_still_marks_note_processed(
        self, db, as_test_user, handler, mock_extractor,
        note_service, test_ticket
    ):
        note = note_service.create(NoteCreate(
            ticket_id=test_ticket.id, content="Nothing useful"
        ))

        mock_extractor.extract_attributes.return_value = ExtractedAttributes(
            attributes={}, raw_response="{}", confidence=Decimal("0.80"),
        )

        event = TicketCompleted(ticket=test_ticket)
        handler(event)

        assert note_service.get_by_id(note.id).processed_at is not None
