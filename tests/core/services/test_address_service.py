"""Tests for AddressService."""

import pytest
from uuid import uuid4
from datetime import timedelta

from utils.timezone import now_utc


@pytest.fixture
def test_customer(as_test_workspace, customer_service):
    """Create a test customer, delete after test."""
    from core.models import CustomerCreate

    customer = customer_service.create(CustomerCreate(first_name="Test", last_name="Customer"))
    yield customer
    customer_service.delete(customer.id)


class TestAddressCreate:
    """Tests for AddressService.create."""

    def test_creates_address(self, db, as_test_workspace, address_service, test_customer):
        """Creates address with provided data."""
        from core.models import AddressCreate

        data = AddressCreate(
            customer_id=test_customer.id,
            street="123 Main St",
            city="Austin",
            state="TX",
            zip="78701"
        )

        address = address_service.create(data)

        assert address.street == "123 Main St"
        assert address.city == "Austin"
        assert address.customer_id == test_customer.id

    def test_sets_workspace_id_from_context(self, db, as_test_workspace, test_workspace_id, address_service, test_customer):
        """workspace_id comes from context."""
        from core.models import AddressCreate

        data = AddressCreate(
            customer_id=test_customer.id,
            street="456 Oak Ave",
            city="Dallas",
            state="TX",
            zip="75201"
        )

        address = address_service.create(data)

        assert address.workspace_id == test_workspace_id

    def test_creates_with_optional_fields(self, db, as_test_workspace, address_service, test_customer):
        """Creates address with label and notes."""
        from core.models import AddressCreate

        data = AddressCreate(
            customer_id=test_customer.id,
            street="789 Pine Rd",
            street2="Apt 4B",
            city="Houston",
            state="TX",
            zip="77001",
            label="Office",
            notes="Gate code: 1234"
        )

        address = address_service.create(data)

        assert address.street2 == "Apt 4B"
        assert address.label == "Office"
        assert address.notes == "Gate code: 1234"

    def test_is_primary_defaults_false(self, db, as_test_workspace, address_service, test_customer):
        """is_primary defaults to False."""
        from core.models import AddressCreate

        data = AddressCreate(
            customer_id=test_customer.id,
            street="100 Test St",
            city="Austin",
            state="TX",
            zip="78702"
        )

        address = address_service.create(data)

        assert address.is_primary is False

    def test_can_set_is_primary(self, db, as_test_workspace, address_service, test_customer):
        """Can create primary address."""
        from core.models import AddressCreate

        data = AddressCreate(
            customer_id=test_customer.id,
            street="200 Primary Ave",
            city="Austin",
            state="TX",
            zip="78703",
            is_primary=True
        )

        address = address_service.create(data)

        assert address.is_primary is True


class TestAddressGetById:
    """Tests for AddressService.get_by_id."""

    def test_returns_address_when_exists(self, db, as_test_workspace, address_service, test_customer):
        """Get by ID returns address."""
        from core.models import AddressCreate

        data = AddressCreate(
            customer_id=test_customer.id,
            street="Test St",
            city="Austin",
            state="TX",
            zip="78701"
        )
        created = address_service.create(data)

        found = address_service.get_by_id(created.id)

        assert found is not None
        assert found.id == created.id

    def test_returns_none_for_nonexistent(self, db, as_test_workspace, address_service):
        """Missing ID returns None."""
        result = address_service.get_by_id(uuid4())
        assert result is None


class TestAddressListForCustomer:
    """Tests for AddressService.list_for_customer."""

    def test_returns_customer_addresses(self, db, as_test_workspace, address_service, test_customer):
        """List returns addresses for customer."""
        from core.models import AddressCreate

        address_service.create(AddressCreate(
            customer_id=test_customer.id,
            street="Address 1",
            city="Austin",
            state="TX",
            zip="78701"
        ))
        address_service.create(AddressCreate(
            customer_id=test_customer.id,
            street="Address 2",
            city="Austin",
            state="TX",
            zip="78702"
        ))

        addresses = address_service.list_for_customer(test_customer.id)

        assert len(addresses) == 2

    def test_excludes_other_customers(self, db, as_test_workspace, address_service, customer_service):
        """Only returns addresses for specified customer."""
        from core.models import CustomerCreate, AddressCreate

        customer_a = customer_service.create(CustomerCreate(first_name="Customer A"))
        customer_b = customer_service.create(CustomerCreate(first_name="Customer B"))

        address_service.create(AddressCreate(
            customer_id=customer_a.id,
            street="A's Address",
            city="Austin",
            state="TX",
            zip="78701"
        ))
        address_service.create(AddressCreate(
            customer_id=customer_b.id,
            street="B's Address",
            city="Dallas",
            state="TX",
            zip="75201"
        ))

        addresses_a = address_service.list_for_customer(customer_a.id)
        addresses_b = address_service.list_for_customer(customer_b.id)

        assert len(addresses_a) == 1
        assert addresses_a[0].street == "A's Address"
        assert len(addresses_b) == 1
        assert addresses_b[0].street == "B's Address"

        # Cleanup
        customer_service.delete(customer_a.id)
        customer_service.delete(customer_b.id)


class TestAddressUpdate:
    """Tests for AddressService.update."""

    def test_updates_fields(self, db, as_test_workspace, address_service, test_customer):
        """Updates specified fields."""
        from core.models import AddressCreate, AddressUpdate

        address = address_service.create(AddressCreate(
            customer_id=test_customer.id,
            street="Old Street",
            city="Austin",
            state="TX",
            zip="78701"
        ))

        updated = address_service.update(address.id, AddressUpdate(street="New Street"))

        assert updated.street == "New Street"
        assert updated.city == "Austin"  # Unchanged


class TestAddressDelete:
    """Tests for AddressService.delete."""

    def test_hard_deletes(self, db, as_test_workspace, address_service, test_customer):
        """Addresses are hard deleted (not soft)."""
        from core.models import AddressCreate

        address = address_service.create(AddressCreate(
            customer_id=test_customer.id,
            street="Delete Me",
            city="Austin",
            state="TX",
            zip="78701"
        ))

        address_service.delete(address.id)

        # Should be completely gone (visible within the same transaction)
        rows = db.execute(
            "SELECT * FROM addresses WHERE id = %s",
            (address.id,)
        )
        assert len(rows) == 0

    def test_rejects_delete_when_ticket_references_address(self, db, as_test_workspace, address_service, customer_service, ticket_service, test_customer):
        """Address referenced by a ticket raises AddressInUseError, not an opaque FK 500."""
        from core.exceptions import AddressInUseError
        from core.models import TicketCreate, AddressCreate

        address = address_service.create(AddressCreate(
            customer_id=test_customer.id, street="Guarded", city="Austin", state="TX", zip="78701",
        ))
        ticket_service.create(TicketCreate(
            customer_id=test_customer.id,
            address_id=address.id,
            scheduled_at=now_utc() + timedelta(days=1),
        ))

        with pytest.raises(AddressInUseError) as exc:
            address_service.delete(address.id)
        assert exc.value.code == "ADDRESS_IN_USE"
        assert exc.value.http_status == 409
        # Address still exists.
        assert address_service.get_by_id(address.id) is not None
