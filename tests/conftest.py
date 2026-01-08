"""Shared test fixtures for CRM test suite."""

import pytest
from uuid import UUID
from pathlib import Path

from dotenv import load_dotenv

# Load .env file BEFORE any other imports that might use env vars
# override=True ensures .env takes precedence over shell env vars
load_dotenv(Path(__file__).parent.parent / ".env", override=True)

# Reset vault client singleton to pick up env vars
import clients.vault_client as vault_module
vault_module._vault_client_instance = None
vault_module._secret_cache.clear()

from utils.user_context import user_context, clear_current_user_id


# =============================================================================
# TEST USER CONSTANTS
# =============================================================================

# Primary test user - use for single-user tests
TEST_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
TEST_USER_EMAIL = "testuser@test.local"

# Secondary test user - use for RLS isolation tests
TEST_USER_B_ID = UUID("00000000-0000-0000-0000-000000000002")
TEST_USER_B_EMAIL = "testuser-b@test.local"


# =============================================================================
# USER CONTEXT FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def reset_user_context():
    """Ensure clean user context before and after each test."""
    clear_current_user_id()
    yield
    clear_current_user_id()


@pytest.fixture
def test_user_id() -> UUID:
    """The primary test user's ID."""
    return TEST_USER_ID


@pytest.fixture
def test_user_b_id() -> UUID:
    """The secondary test user's ID (for isolation tests)."""
    return TEST_USER_B_ID


@pytest.fixture
def authenticated_context(test_user_id):
    """Provide an authenticated user context for the primary test user."""
    with user_context(test_user_id):
        yield test_user_id


# =============================================================================
# DATABASE FIXTURES
# =============================================================================


@pytest.fixture(scope="session")
def db():
    """Session-scoped PostgresClient (application user, RLS enforced)."""
    from clients.postgres_client import PostgresClient
    from clients.vault_client import get_database_url

    client = PostgresClient(get_database_url())
    yield client
    client.close()


@pytest.fixture(scope="session")
def db_admin():
    """Session-scoped admin PostgresClient (bypasses RLS, for test setup/teardown)."""
    from clients.postgres_client import PostgresClient
    from clients.vault_client import VaultClient

    vault = VaultClient()
    admin_url = vault.get_secret("database", "admin_url")
    client = PostgresClient(admin_url)
    yield client
    client.close()


@pytest.fixture(scope="session")
def db_url():
    """Database URL from Vault."""
    from clients.vault_client import get_database_url
    return get_database_url()


@pytest.fixture(autouse=True)
def reset_db_state(db_admin):
    """Reset database state before each test using admin connection."""
    if db_admin is None:
        return

    # Truncate user-scoped tables (CASCADE handles foreign keys)
    db_admin.execute("""
        TRUNCATE
            customers, addresses, services, tickets, ticket_technicians,
            line_items, invoices, notes, attributes, scheduled_messages,
            waitlist, leads, recurring_templates, recurring_template_services,
            model_authorization_queue
        CASCADE
    """)

    # Ensure test users exist
    db_admin.execute("""
        INSERT INTO users (id, email, created_at, updated_at)
        VALUES
            (%s, %s, now(), now()),
            (%s, %s, now(), now())
        ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email
    """, (TEST_USER_ID, TEST_USER_EMAIL, TEST_USER_B_ID, TEST_USER_B_EMAIL))

    yield


@pytest.fixture
def as_test_user(test_user_id):
    """Context manager that sets primary test user context."""
    with user_context(test_user_id):
        yield test_user_id


@pytest.fixture
def as_test_user_b(test_user_b_id):
    """Context manager that sets secondary test user context."""
    with user_context(test_user_b_id):
        yield test_user_b_id


# =============================================================================
# VALKEY FIXTURES
# =============================================================================


@pytest.fixture(scope="session")
def valkey():
    """Session-scoped ValkeyClient."""
    from clients.valkey_client import ValkeyClient
    from clients.vault_client import get_valkey_url

    client = ValkeyClient(get_valkey_url())
    yield client
    client.close()
