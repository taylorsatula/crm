"""Tests for PostgresClient — PostgreSQL with RLS workspace isolation.

These exercise the real PostgresClient (the crm_dbuser app role) against the
test database, not the conftest TestDb transactional helper. Writes commit for
real, so each test cleans up the rows it inserts via the admin client.
"""

from uuid import UUID, uuid4

import pytest

from clients.postgres_client import PostgresClient
from utils.workspace_context import workspace_context

TEST_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
TEST_WORKSPACE_B_ID = UUID("00000000-0000-0000-0000-000000000002")


@pytest.fixture
def pg(db_url, db_admin):
    """Real PostgresClient (app role) against the repointed test database.

    Requesting db_admin triggers the autouse reset_db_state seed and gives an
    RLS-bypassing handle for cleaning up committed rows after each test.
    """
    client = PostgresClient(db_url)
    yield client
    client.close()


def _insert_customer(pg, customer_id, workspace_id, first_name):
    pg.execute(
        "INSERT INTO customers (id, workspace_id, first_name, created_at, updated_at) "
        "VALUES (%s, %s, %s, now(), now())",
        (customer_id, workspace_id, first_name),
    )


class TestConnectionPoolAndHealth:
    def test_health_check_returns_true_for_live_database(self, pg):
        assert pg.health_check() is True


class TestExecuteMethods:
    def test_execute_returns_list_of_dicts(self, pg):
        with workspace_context(TEST_WORKSPACE_ID):
            assert pg.execute("SELECT 1 as num, 'hello' as word") == [
                {"num": 1, "word": "hello"}
            ]

    def test_execute_empty_returns_empty_list(self, pg):
        with workspace_context(TEST_WORKSPACE_ID):
            assert pg.execute("SELECT 1 WHERE false") == []

    def test_execute_single_returns_dict(self, pg):
        with workspace_context(TEST_WORKSPACE_ID):
            assert pg.execute_single("SELECT 42 as answer") == {"answer": 42}

    def test_execute_single_no_rows_returns_none(self, pg):
        with workspace_context(TEST_WORKSPACE_ID):
            assert pg.execute_single("SELECT 1 WHERE false") is None

    def test_execute_scalar_returns_value(self, pg):
        with workspace_context(TEST_WORKSPACE_ID):
            assert pg.execute_scalar("SELECT 'test'") == "test"

    def test_execute_scalar_no_rows_returns_none(self, pg):
        with workspace_context(TEST_WORKSPACE_ID):
            assert pg.execute_scalar("SELECT 1 WHERE false") is None


class TestRLSContext:
    def test_sets_workspace_context_from_contextvar(self, pg):
        with workspace_context(TEST_WORKSPACE_ID):
            assert pg.execute_scalar(
                "SELECT current_setting('app.current_workspace_id', true)"
            ) == str(TEST_WORKSPACE_ID)

    def test_clears_context_without_workspace_id(self, pg):
        # autouse reset_workspace_context clears the contextvar before the test.
        assert pg.execute_scalar(
            "SELECT current_setting('app.current_workspace_id', true)"
        ) == ""


class TestWorkspaceIsolation:
    def test_user_only_sees_own_data(self, pg, db_admin):
        customer_a = uuid4()
        customer_b = uuid4()
        with workspace_context(TEST_WORKSPACE_ID):
            _insert_customer(pg, customer_a, TEST_WORKSPACE_ID, "Alice")
        with workspace_context(TEST_WORKSPACE_B_ID):
            _insert_customer(pg, customer_b, TEST_WORKSPACE_B_ID, "Bob")
        try:
            with workspace_context(TEST_WORKSPACE_ID):
                names = [r["first_name"] for r in pg.execute("SELECT first_name FROM customers")]
                assert names == ["Alice"]
            with workspace_context(TEST_WORKSPACE_B_ID):
                names = [r["first_name"] for r in pg.execute("SELECT first_name FROM customers")]
                assert names == ["Bob"]
        finally:
            db_admin.execute(
                "DELETE FROM customers WHERE id IN (%s, %s)", (customer_a, customer_b)
            )

    def test_no_context_sees_no_rls_rows(self, pg, db_admin):
        customer_id = uuid4()
        with workspace_context(TEST_WORKSPACE_ID):
            _insert_customer(pg, customer_id, TEST_WORKSPACE_ID, "Charlie")
        try:
            assert pg.execute("SELECT first_name FROM customers") == []
        finally:
            db_admin.execute("DELETE FROM customers WHERE id = %s", (customer_id,))

    def test_cannot_see_other_workspace_data_by_id(self, pg, db_admin):
        secret_id = uuid4()
        with workspace_context(TEST_WORKSPACE_B_ID):
            _insert_customer(pg, secret_id, TEST_WORKSPACE_B_ID, "Secret")
        try:
            with workspace_context(TEST_WORKSPACE_ID):
                assert pg.execute_single(
                    "SELECT first_name FROM customers WHERE id = %s", (secret_id,)
                ) is None
        finally:
            db_admin.execute("DELETE FROM customers WHERE id = %s", (secret_id,))


class TestTransaction:
    def test_transaction_commits_on_success(self, pg, db_admin):
        customer_id = uuid4()
        try:
            with workspace_context(TEST_WORKSPACE_ID):
                with pg.transaction():
                    _insert_customer(pg, customer_id, TEST_WORKSPACE_ID, "Committed")
                row = pg.execute_single(
                    "SELECT first_name FROM customers WHERE id = %s", (customer_id,)
                )
                assert row["first_name"] == "Committed"
        finally:
            db_admin.execute("DELETE FROM customers WHERE id = %s", (customer_id,))

    def test_transaction_rolls_back_on_exception(self, pg, db_admin):
        customer_id = uuid4()
        with workspace_context(TEST_WORKSPACE_ID):
            with pytest.raises(RuntimeError, match="boom"):
                with pg.transaction():
                    _insert_customer(pg, customer_id, TEST_WORKSPACE_ID, "RolledBack")
                    raise RuntimeError("boom")
            assert pg.execute_single(
                "SELECT first_name FROM customers WHERE id = %s", (customer_id,)
            ) is None
        # Rolled back, but guard against any leak.
        db_admin.execute("DELETE FROM customers WHERE id = %s", (customer_id,))
