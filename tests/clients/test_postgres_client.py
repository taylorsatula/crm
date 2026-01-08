"""Tests for PostgresClient - PostgreSQL with RLS user isolation."""

import pytest
from uuid import UUID, uuid4

from clients.postgres_client import PostgresClient
from utils.user_context import user_context

# Test user constants (must match conftest.py)
TEST_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
TEST_USER_B_ID = UUID("00000000-0000-0000-0000-000000000002")


class TestPostgresClientInit:
    """Connection pool initialization."""

    def test_creates_pool_with_valid_url(self, db):
        """Valid URL creates working connection pool."""
        result = db.execute_scalar("SELECT 1")
        assert result == 1


class TestRLSContext:
    """Row Level Security context management."""

    def test_sets_user_context_from_contextvar(self, db):
        """User ID from contextvar is set in session config."""
        with user_context(TEST_USER_ID):
            result = db.execute_scalar("SELECT current_setting('app.current_user_id', true)")
            assert result == str(TEST_USER_ID)

    def test_clears_context_without_user_id(self, db):
        """No user context sets app.current_user_id to empty string."""
        # Contextvar is cleared by reset_user_context fixture
        result = db.execute_scalar("SELECT current_setting('app.current_user_id', true)")
        assert result == ""


class TestExecuteMethods:
    """Query execution methods."""

    def test_execute_returns_list_of_dicts(self, db):
        """execute() returns list of row dicts."""
        results = db.execute("SELECT 1 as num, 'hello' as word")
        assert results == [{"num": 1, "word": "hello"}]

    def test_execute_empty_returns_empty_list(self, db):
        """No matching rows returns [], not None."""
        results = db.execute("SELECT 1 WHERE false")
        assert results == []

    def test_execute_single_returns_dict(self, db):
        """execute_single() returns first row as dict."""
        result = db.execute_single("SELECT 42 as answer")
        assert result == {"answer": 42}

    def test_execute_single_no_rows_returns_none(self, db):
        """execute_single() returns None for empty result."""
        result = db.execute_single("SELECT 1 WHERE false")
        assert result is None

    def test_execute_scalar_returns_value(self, db):
        """execute_scalar() returns first value of first row."""
        result = db.execute_scalar("SELECT 'test'")
        assert result == "test"

    def test_execute_scalar_no_rows_returns_none(self, db):
        """execute_scalar() returns None for empty result."""
        result = db.execute_scalar("SELECT 1 WHERE false")
        assert result is None


class TestUserIsolation:
    """RLS user isolation - the core security feature."""

    def test_user_only_sees_own_data(self, db):
        """User A cannot see User B's customers."""
        customer_a_id = uuid4()
        customer_b_id = uuid4()

        # Insert customers for each user
        with user_context(TEST_USER_ID):
            db.execute(
                "INSERT INTO customers (id, user_id, first_name, created_at, updated_at) "
                "VALUES (%s, %s, %s, now(), now())",
                (customer_a_id, TEST_USER_ID, "Alice"),
            )

        with user_context(TEST_USER_B_ID):
            db.execute(
                "INSERT INTO customers (id, user_id, first_name, created_at, updated_at) "
                "VALUES (%s, %s, %s, now(), now())",
                (customer_b_id, TEST_USER_B_ID, "Bob"),
            )

        # User A sees only their customer
        with user_context(TEST_USER_ID):
            customers_a = db.execute("SELECT first_name FROM customers")
            assert len(customers_a) == 1
            assert customers_a[0]["first_name"] == "Alice"

        # User B sees only their customer
        with user_context(TEST_USER_B_ID):
            customers_b = db.execute("SELECT first_name FROM customers")
            assert len(customers_b) == 1
            assert customers_b[0]["first_name"] == "Bob"

    def test_no_context_errors_on_rls_tables(self, db):
        """Without user context, queries on RLS tables fail (fail-fast)."""
        # Insert a customer as user A
        with user_context(TEST_USER_ID):
            db.execute(
                "INSERT INTO customers (id, user_id, first_name, created_at, updated_at) "
                "VALUES (%s, %s, %s, now(), now())",
                (uuid4(), TEST_USER_ID, "Charlie"),
            )

        # Without context, query fails - empty string can't cast to UUID
        # This is intentional fail-fast behavior
        import psycopg2
        with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
            db.execute("SELECT first_name FROM customers")

    def test_cannot_see_other_users_data_by_id(self, db):
        """Even with known ID, user cannot access another user's data."""
        customer_id = uuid4()

        # Create customer as User B
        with user_context(TEST_USER_B_ID):
            db.execute(
                "INSERT INTO customers (id, user_id, first_name, created_at, updated_at) "
                "VALUES (%s, %s, %s, now(), now())",
                (customer_id, TEST_USER_B_ID, "Secret"),
            )

        # User A tries to fetch by ID - gets nothing
        with user_context(TEST_USER_ID):
            result = db.execute_single("SELECT first_name FROM customers WHERE id = %s", (customer_id,))
            assert result is None
