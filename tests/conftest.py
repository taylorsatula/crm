"""Shared test fixtures for CRM test suite."""

import pytest
from uuid import UUID

from utils.user_context import user_context, clear_current_user_id


# Test user constants
TEST_USER_EMAIL = "testuser@here.local"
TEST_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture(autouse=True)
def reset_user_context():
    """Ensure clean user context before and after each test."""
    clear_current_user_id()
    yield
    clear_current_user_id()


@pytest.fixture
def test_user_id() -> UUID:
    """The standard test user's ID."""
    return TEST_USER_ID


@pytest.fixture
def authenticated_context(test_user_id):
    """Provide an authenticated user context for tests that need it."""
    with user_context(test_user_id):
        yield test_user_id


# =============================================================================
# DATABASE FIXTURES - Implement in Phase 1 with postgres_client
# =============================================================================


@pytest.fixture(scope="session")
def db_connection():
    """
    Session-scoped database connection for tests.

    Phase 1 implementation:
        - Connect to test database
        - Set up connection pool
        - Yield connection
        - Tear down pool on session end
    """
    # TODO: Phase 1 - return actual connection
    return None


@pytest.fixture(autouse=True)
def reset_db_state(db_connection):
    """
    Reset database state before each test.

    Phase 1 implementation:
        - Truncate all tables (preserve schema)
        - Re-insert test user (TEST_USER_EMAIL, TEST_USER_ID)
        - Reset any sequences
    """
    if db_connection is None:
        return

    # Phase 1:
    # db_connection.execute("TRUNCATE users, contacts, tickets, ... CASCADE")
    # db_connection.execute(
    #     "INSERT INTO users (id, email, created_at) VALUES (%s, %s, now())",
    #     (TEST_USER_ID, TEST_USER_EMAIL)
    # )


@pytest.fixture
def ensure_test_user(db_connection):
    """
    Ensure test user exists in database.

    Phase 1 implementation:
        - Check if TEST_USER_ID exists
        - Create if not
        - Return User model
    """
    if db_connection is None:
        return None

    # Phase 1: return actual User
    return None
