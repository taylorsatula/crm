"""Tests for AttributeService."""

import pytest
from uuid import uuid4
from decimal import Decimal

from utils.timezone import now_utc


@pytest.fixture
def attribute_service(db):
    """AttributeService with real DB."""
    from core.services.attribute_service import AttributeService
    from core.audit import AuditLogger

    audit = AuditLogger(db)
    return AttributeService(db, audit)


@pytest.fixture
def customer_service(db, event_bus):
    """CustomerService for test setup."""
    from core.services.customer_service import CustomerService
    from core.audit import AuditLogger

    return CustomerService(db, AuditLogger(db), event_bus)


@pytest.fixture
def note_service(db, event_bus):
    """NoteService for test setup."""
    from core.services.note_service import NoteService
    from core.audit import AuditLogger

    return NoteService(db, AuditLogger(db), event_bus)


@pytest.fixture
def test_customer(as_test_user, customer_service):
    """Create a test customer."""
    from core.models import CustomerCreate

    customer = customer_service.create(CustomerCreate(first_name="Attribute", last_name="Test"))
    yield customer
    customer_service.delete(customer.id)


@pytest.fixture
def test_note(as_test_user, note_service, test_customer):
    """Create a test note."""
    from core.models import NoteCreate

    note = note_service.create(NoteCreate(
        customer_id=test_customer.id,
        content="Customer has 15 windows and a pet dog."
    ))
    yield note
    note_service.delete(note.id)


class TestAttributeCreate:
    """Tests for AttributeService.create."""

    def test_creates_manual_attribute(self, db, as_test_user, attribute_service, test_customer):
        """Creates manually entered attribute."""
        from core.models import AttributeCreate

        data = AttributeCreate(
            customer_id=test_customer.id,
            key="window_count",
            value=15,
            source_type="manual"
        )

        attr = attribute_service.create(data)

        assert attr.customer_id == test_customer.id
        assert attr.key == "window_count"
        assert attr.value == 15
        assert attr.source_type == "manual"
        assert attr.confidence is None

    def test_creates_llm_extracted_attribute(self, db, as_test_user, attribute_service, test_customer, test_note):
        """Creates LLM-extracted attribute with confidence."""
        from core.models import AttributeCreate

        data = AttributeCreate(
            customer_id=test_customer.id,
            key="pet_type",
            value="dog",
            source_type="llm_extracted",
            source_note_id=test_note.id,
            confidence=Decimal("0.85")
        )

        attr = attribute_service.create(data)

        assert attr.key == "pet_type"
        assert attr.value == "dog"
        assert attr.source_type == "llm_extracted"
        assert attr.source_note_id == test_note.id
        assert attr.confidence == Decimal("0.85")

    def test_upserts_on_duplicate_key(self, db, as_test_user, attribute_service, test_customer):
        """Creating attribute with existing key updates it."""
        from core.models import AttributeCreate

        # Create first
        attribute_service.create(AttributeCreate(
            customer_id=test_customer.id,
            key="window_count",
            value=10
        ))

        # Create again with same key - should update
        updated = attribute_service.create(AttributeCreate(
            customer_id=test_customer.id,
            key="window_count",
            value=15
        ))

        assert updated.value == 15

        # Should only be one attribute with this key
        attrs = attribute_service.list_for_customer(test_customer.id)
        window_counts = [a for a in attrs if a.key == "window_count"]
        assert len(window_counts) == 1

    def test_stores_complex_value(self, db, as_test_user, attribute_service, test_customer):
        """Stores complex JSON values."""
        from core.models import AttributeCreate

        data = AttributeCreate(
            customer_id=test_customer.id,
            key="service_preferences",
            value={
                "time_of_day": "morning",
                "days": ["monday", "wednesday"],
                "notes": "Call before arriving"
            }
        )

        attr = attribute_service.create(data)

        assert attr.value["time_of_day"] == "morning"
        assert attr.value["days"] == ["monday", "wednesday"]


class TestAttributeGet:
    """Tests for AttributeService get methods."""

    def test_gets_attribute_by_id(self, db, as_test_user, attribute_service, test_customer):
        """Gets attribute by ID."""
        from core.models import AttributeCreate

        created = attribute_service.create(AttributeCreate(
            customer_id=test_customer.id,
            key="test_key",
            value="test_value"
        ))

        fetched = attribute_service.get_by_id(created.id)

        assert fetched is not None
        assert fetched.id == created.id

    def test_gets_attribute_by_key(self, db, as_test_user, attribute_service, test_customer):
        """Gets specific attribute by customer and key."""
        from core.models import AttributeCreate

        attribute_service.create(AttributeCreate(
            customer_id=test_customer.id,
            key="specific_key",
            value="specific_value"
        ))

        fetched = attribute_service.get_for_customer(test_customer.id, "specific_key")

        assert fetched is not None
        assert fetched.key == "specific_key"
        assert fetched.value == "specific_value"

    def test_returns_none_for_missing(self, db, as_test_user, attribute_service):
        """Returns None for non-existent attribute."""
        result = attribute_service.get_by_id(uuid4())
        assert result is None

    def test_returns_none_for_missing_key(self, db, as_test_user, attribute_service, test_customer):
        """Returns None for non-existent key."""
        result = attribute_service.get_for_customer(test_customer.id, "nonexistent_key")
        assert result is None


class TestAttributeList:
    """Tests for AttributeService.list_for_customer."""

    def test_lists_customer_attributes(self, db, as_test_user, attribute_service, test_customer):
        """Lists all attributes for a customer."""
        from core.models import AttributeCreate

        attribute_service.create(AttributeCreate(
            customer_id=test_customer.id,
            key="attr_one",
            value="value_one"
        ))
        attribute_service.create(AttributeCreate(
            customer_id=test_customer.id,
            key="attr_two",
            value="value_two"
        ))

        attrs = attribute_service.list_for_customer(test_customer.id)

        assert len(attrs) >= 2
        keys = [a.key for a in attrs]
        assert "attr_one" in keys
        assert "attr_two" in keys


class TestAttributeDelete:
    """Tests for AttributeService.delete."""

    def test_deletes_attribute(self, db, as_test_user, attribute_service, test_customer):
        """Deletes attribute."""
        from core.models import AttributeCreate

        attr = attribute_service.create(AttributeCreate(
            customer_id=test_customer.id,
            key="to_delete",
            value="delete_me"
        ))

        result = attribute_service.delete(attr.id)
        assert result is True

        # Should no longer be returned
        fetched = attribute_service.get_by_id(attr.id)
        assert fetched is None

    def test_returns_false_for_missing(self, db, as_test_user, attribute_service):
        """Returns False when deleting non-existent attribute."""
        result = attribute_service.delete(uuid4())
        assert result is False


class TestBulkCreate:
    """Tests for AttributeService.bulk_create_from_extraction."""

    def test_bulk_creates_attributes(self, db, as_test_user, attribute_service, test_customer, test_note):
        """Bulk creates attributes from LLM extraction."""
        attrs = {
            "window_count": 15,
            "pet_type": "dog",
            "yard_size": "large"
        }

        created = attribute_service.bulk_create_from_extraction(
            customer_id=test_customer.id,
            attributes=attrs,
            source_note_id=test_note.id,
            confidence=Decimal("0.80")
        )

        assert len(created) == 3
        assert all(a.source_type == "llm_extracted" for a in created)
        assert all(a.source_note_id == test_note.id for a in created)
        assert all(a.confidence == Decimal("0.80") for a in created)
