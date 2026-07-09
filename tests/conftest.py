"""Shared fixtures for the workspace-scoped CRM test suite."""

from pathlib import Path
from uuid import UUID

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

import clients.vault_client as vault_module

vault_module._vault_client_instance = None
vault_module._secret_cache.clear()

from utils.workspace_context import clear_workspace_context, workspace_context

TEST_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
TEST_WORKSPACE_B_ID = UUID("00000000-0000-0000-0000-000000000002")


@pytest.fixture(autouse=True)
def reset_workspace_context():
    clear_workspace_context()
    yield
    clear_workspace_context()


@pytest.fixture
def test_workspace_id() -> UUID:
    return TEST_WORKSPACE_ID


@pytest.fixture
def test_workspace_b_id() -> UUID:
    return TEST_WORKSPACE_B_ID


@pytest.fixture
def authenticated_context(test_workspace_id):
    with workspace_context(test_workspace_id, "America/Chicago"):
        yield test_workspace_id


@pytest.fixture(scope="session")
def db_url():
    from clients.vault_client import get_database_url

    return get_database_url()


@pytest.fixture
def db(db_url):
    """Transactional application connection that applies workspace RLS per query."""
    from psycopg import sql
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    from utils.workspace_context import _current_workspace_id

    pool = ConnectionPool(conninfo=db_url, min_size=1, max_size=2, open=True)
    with pool.connection() as conn:
        conn.autocommit = False
        with conn.transaction():
            def _apply_rls(cur):
                workspace_id = _current_workspace_id.get()
                if workspace_id is None:
                    cur.execute("SET app.current_workspace_id = ''")
                else:
                    cur.execute(
                        sql.SQL("SET app.current_workspace_id = {}").format(
                            sql.Literal(str(workspace_id))
                        )
                    )

            class TestDb:
                def execute(self, query, params=None):
                    with conn.cursor(row_factory=dict_row) as cur:
                        _apply_rls(cur)
                        cur.execute(query, params)
                        if cur.description:
                            return [dict(row) for row in cur.fetchall()]
                        return []

                def execute_single(self, query, params=None):
                    results = self.execute(query, params)
                    return results[0] if results else None

                def execute_scalar(self, query, params=None):
                    with conn.cursor() as cur:
                        _apply_rls(cur)
                        cur.execute(query, params)
                        row = cur.fetchone()
                        return row[0] if row else None

                def execute_returning(self, query, params=None):
                    with conn.cursor(row_factory=dict_row) as cur:
                        _apply_rls(cur)
                        cur.execute(query, params)
                        return [dict(row) for row in cur.fetchall()]

            yield TestDb()
    pool.close()


@pytest.fixture(scope="session")
def db_admin(db_url):
    from clients.postgres_client import PostgresClient
    from clients.vault_client import VaultClient

    vault = VaultClient()
    client = PostgresClient(vault.get_secret("database", "admin_url"))
    yield client
    client.close()


@pytest.fixture(autouse=True)
def reset_db_state(request):
    if "db" not in request.fixturenames and "db_admin" not in request.fixturenames:
        yield
        return

    db_admin = request.getfixturevalue("db_admin")
    db_admin.execute("DELETE FROM workspaces WHERE id IN (%s, %s)", (TEST_WORKSPACE_ID, TEST_WORKSPACE_B_ID))
    db_admin.execute(
        "INSERT INTO workspaces (id) VALUES (%s), (%s)",
        (TEST_WORKSPACE_ID, TEST_WORKSPACE_B_ID),
    )
    yield


@pytest.fixture
def as_test_workspace(test_workspace_id):
    with workspace_context(test_workspace_id, "America/Chicago"):
        yield test_workspace_id


@pytest.fixture
def as_test_workspace_b(test_workspace_b_id):
    with workspace_context(test_workspace_b_id, "America/Chicago"):
        yield test_workspace_b_id


@pytest.fixture
def event_bus():
    from core.event_bus import EventBus

    return EventBus()


@pytest.fixture
def audit(db):
    from core.audit import AuditLogger

    return AuditLogger(db)


@pytest.fixture
def customer_service(db, audit, event_bus):
    from core.services.customer_service import CustomerService

    return CustomerService(db, audit, event_bus)


@pytest.fixture
def ticket_service(db, audit, event_bus):
    from core.services.ticket_service import TicketService

    return TicketService(db, audit, event_bus)


@pytest.fixture
def catalog_service(db, audit):
    from core.services.catalog_service import CatalogService

    return CatalogService(db, audit)


@pytest.fixture
def line_item_service(db, audit):
    from core.services.line_item_service import LineItemService

    return LineItemService(db, audit)


@pytest.fixture
def invoice_service(db, audit, event_bus):
    from core.services.invoice_service import InvoiceService

    return InvoiceService(db, audit, event_bus)


@pytest.fixture
def note_service(db, audit, event_bus):
    from core.services.note_service import NoteService

    return NoteService(db, audit, event_bus)


@pytest.fixture
def attribute_service(db, audit):
    from core.services.attribute_service import AttributeService

    return AttributeService(db, audit)


@pytest.fixture
def message_service(db, audit):
    from core.services.message_service import MessageService

    return MessageService(db, audit)


@pytest.fixture
def address_service(db, audit):
    from core.services.address_service import AddressService

    return AddressService(db, audit)


@pytest.fixture
def services(
    customer_service, ticket_service, catalog_service, line_item_service,
    invoice_service, note_service, attribute_service, message_service, address_service,
):
    return {
        "customer": customer_service,
        "ticket": ticket_service,
        "catalog": catalog_service,
        "line_item": line_item_service,
        "invoice": invoice_service,
        "note": note_service,
        "attribute": attribute_service,
        "message": message_service,
        "address": address_service,
    }
