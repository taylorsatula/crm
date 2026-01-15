"""Tests for CustomerService."""

import pytest
from uuid import uuid4


@pytest.fixture
def customer_service(db):
    """CustomerService with real DB."""
    from core.services.customer_service import CustomerService
    from core.audit import AuditLogger

    audit = AuditLogger(db)
    return CustomerService(db, audit)


class TestCustomerCreate:
    """Tests for CustomerService.create."""

    def test_creates_customer(self, db, as_test_user, customer_service):
        """Creates customer with provided data."""
        from core.models import CustomerCreate

        data = CustomerCreate(
            first_name="Alice",
            last_name="Smith",
            email="alice@test.com",
            phone="555-1234"
        )

        customer = customer_service.create(data)

        assert customer.first_name == "Alice"
        assert customer.last_name == "Smith"
        assert customer.email == "alice@test.com"

    def test_sets_user_id_from_context(self, db, as_test_user, test_user_id, customer_service):
        """user_id comes from context, not parameter."""
        from core.models import CustomerCreate

        data = CustomerCreate(first_name="Bob")
        customer = customer_service.create(data)

        assert customer.user_id == test_user_id

    def test_logs_audit_entry(self, db, as_test_user, customer_service):
        """Create logged to audit_log."""
        from core.models import CustomerCreate

        data = CustomerCreate(business_name="Acme Corp")
        customer = customer_service.create(data)

        # Check audit log
        entries = db.execute(
            "SELECT * FROM audit_log WHERE entity_id = %s",
            (customer.id,)
        )
        assert len(entries) == 1
        assert entries[0]["action"] == "create"
        assert entries[0]["entity_type"] == "customer"


class TestCustomerGetById:
    """Tests for CustomerService.get_by_id."""

    def test_returns_customer_when_exists(self, db, as_test_user, customer_service):
        """Get by ID returns customer."""
        from core.models import CustomerCreate

        data = CustomerCreate(first_name="Charlie")
        created = customer_service.create(data)

        found = customer_service.get_by_id(created.id)

        assert found is not None
        assert found.id == created.id
        assert found.first_name == "Charlie"

    def test_returns_none_for_nonexistent(self, db, as_test_user, customer_service):
        """Missing ID returns None."""
        result = customer_service.get_by_id(uuid4())
        assert result is None

    def test_rls_blocks_other_users_customer(self, db, as_test_user, as_test_user_b, test_user_id, test_user_b_id, customer_service):
        """User B cannot see User A's customer."""
        from core.models import CustomerCreate
        from utils.user_context import user_context

        # User A creates customer
        with user_context(test_user_id):
            data = CustomerCreate(first_name="Private")
            customer = customer_service.create(data)

        # User B tries to access
        with user_context(test_user_b_id):
            result = customer_service.get_by_id(customer.id)

        assert result is None


class TestCustomerUpdate:
    """Tests for CustomerService.update."""

    def test_updates_specified_fields(self, db, as_test_user, customer_service):
        """Only provided fields change."""
        from core.models import CustomerCreate, CustomerUpdate

        data = CustomerCreate(first_name="Dave", email="dave@old.com")
        customer = customer_service.create(data)

        update = CustomerUpdate(email="dave@new.com")
        updated = customer_service.update(customer.id, update)

        assert updated.first_name == "Dave"  # Unchanged
        assert updated.email == "dave@new.com"  # Changed

    def test_logs_field_changes(self, db, as_test_user, customer_service):
        """Audit shows old and new values."""
        from core.models import CustomerCreate, CustomerUpdate

        data = CustomerCreate(first_name="Eve")
        customer = customer_service.create(data)

        update = CustomerUpdate(first_name="Eva")
        customer_service.update(customer.id, update)

        # Check audit log for update entry
        entries = db.execute(
            """SELECT * FROM audit_log
               WHERE entity_id = %s AND action = 'update'""",
            (customer.id,)
        )
        assert len(entries) == 1
        changes = entries[0]["changes"]
        assert "first_name" in changes
        assert changes["first_name"]["old"] == "Eve"
        assert changes["first_name"]["new"] == "Eva"

    def test_raises_for_nonexistent(self, db, as_test_user, customer_service):
        """Update on missing customer raises."""
        from core.models import CustomerUpdate

        update = CustomerUpdate(first_name="Ghost")

        with pytest.raises(ValueError, match="not found"):
            customer_service.update(uuid4(), update)


class TestCustomerDelete:
    """Tests for CustomerService.delete."""

    def test_soft_deletes(self, db, db_admin, as_test_user, customer_service):
        """Sets deleted_at, doesn't remove row."""
        from core.models import CustomerCreate

        data = CustomerCreate(first_name="Frank")
        customer = customer_service.create(data)

        customer_service.delete(customer.id)

        # Row still exists with deleted_at set (check via admin to bypass RLS)
        rows = db_admin.execute(
            "SELECT deleted_at FROM customers WHERE id = %s",
            (customer.id,)
        )
        assert len(rows) == 1
        assert rows[0]["deleted_at"] is not None

    def test_deleted_invisible_via_rls(self, db, as_test_user, customer_service):
        """Soft-deleted not returned by get_by_id."""
        from core.models import CustomerCreate

        data = CustomerCreate(first_name="Gina")
        customer = customer_service.create(data)

        customer_service.delete(customer.id)

        result = customer_service.get_by_id(customer.id)
        assert result is None

    def test_logs_delete_action(self, db, as_test_user, customer_service):
        """Delete logged to audit_log."""
        from core.models import CustomerCreate

        data = CustomerCreate(first_name="Henry")
        customer = customer_service.create(data)

        customer_service.delete(customer.id)

        entries = db.execute(
            """SELECT * FROM audit_log
               WHERE entity_id = %s AND action = 'delete'""",
            (customer.id,)
        )
        assert len(entries) == 1


class TestCustomerList:
    """Tests for CustomerService.list."""

    def test_returns_customers(self, db, as_test_user, customer_service):
        """List returns created customers."""
        from core.models import CustomerCreate

        customer_service.create(CustomerCreate(first_name="Ivan"))
        customer_service.create(CustomerCreate(first_name="Jane"))

        result = customer_service.list_all()

        assert len(result) >= 2

    def test_respects_limit(self, db, as_test_user, customer_service):
        """List respects limit parameter."""
        from core.models import CustomerCreate

        for i in range(5):
            customer_service.create(CustomerCreate(first_name=f"User{i}"))

        result = customer_service.list_all(limit=3)

        assert len(result) == 3

    def test_offset_pagination(self, db, as_test_user, customer_service):
        """Offset skips records."""
        from core.models import CustomerCreate

        for i in range(5):
            customer_service.create(CustomerCreate(first_name=f"User{i}"))

        page1 = customer_service.list_all(limit=2, offset=0)
        page2 = customer_service.list_all(limit=2, offset=2)

        # Different customers
        page1_ids = {c.id for c in page1}
        page2_ids = {c.id for c in page2}
        assert page1_ids.isdisjoint(page2_ids)


class TestCustomerSearch:
    """Tests for CustomerService.search."""

    def test_finds_by_first_name(self, db, as_test_user, customer_service):
        """Search matches first_name."""
        from core.models import CustomerCreate

        customer_service.create(CustomerCreate(first_name="Katherine"))
        customer_service.create(CustomerCreate(first_name="Kevin"))

        results = customer_service.search("Kath")

        assert len(results) >= 1
        assert any(c.first_name == "Katherine" for c in results)

    def test_finds_by_email(self, db, as_test_user, customer_service):
        """Search matches email."""
        from core.models import CustomerCreate

        customer_service.create(CustomerCreate(
            first_name="Larry",
            email="larry@unique-domain.com"
        ))

        results = customer_service.search("unique-domain")

        assert len(results) >= 1
        assert any(c.email == "larry@unique-domain.com" for c in results)

    def test_case_insensitive(self, db, as_test_user, customer_service):
        """Search is case-insensitive."""
        from core.models import CustomerCreate

        customer_service.create(CustomerCreate(first_name="Michelle"))

        results = customer_service.search("michelle")

        assert len(results) >= 1
