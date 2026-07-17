"""
PostgreSQL client with connection pooling and RLS workspace isolation.

Uses psycopg3 with ConnectionPool. Workspace isolation enforced via
PostgreSQL Row Level Security - automatically reads workspace ID from contextvar
and sets app.current_workspace_id on each connection.

Security: No workspace context = see nothing (RLS blocks all rows). This is safe.
True admin bypass requires connecting as crm_admin with BYPASSRLS.
"""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from psycopg import Connection, sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from utils.workspace_context import _current_workspace_id

logger = logging.getLogger(__name__)


class PostgresClient:
    """
    PostgreSQL client with automatic RLS context from contextvar.

    Workspace context is read from utils.workspace_context contextvar on each query.
    - Workspace context set → sees only their data (RLS filtered)
    - No workspace context → sees nothing (RLS blocks all rows)

    Usage:
        db = PostgresClient(database_url)

        # With workspace context (normal request flow)
        with workspace_context(workspace_id):
            contacts = db.execute("SELECT * FROM contacts")  # Workspace data only

        # Without workspace context
        contacts = db.execute("SELECT * FROM contacts")  # Empty - RLS blocks
    """

    # Class-level connection pools shared across instances
    _connection_pools: dict[str, ConnectionPool] = {}

    def __init__(self, database_url: str):
        self._database_url = database_url
        self._transaction_connection: ContextVar[Connection | None] = ContextVar(
            f"postgres_transaction_connection_{id(self)}",
            default=None,
        )
        self._ensure_connection_pool()

    def _ensure_connection_pool(self) -> None:
        """Create connection pool if it doesn't exist."""
        if self._database_url not in self._connection_pools:
            pool = ConnectionPool(
                conninfo=self._database_url,
                min_size=2,
                max_size=20,
                open=True,
            )
            self._connection_pools[self._database_url] = pool
            logger.info("Connection pool created")

    @contextmanager
    def get_connection(self):
        """Get connection with RLS context from contextvar."""
        active_connection = self._transaction_connection.get()
        if active_connection is not None:
            yield active_connection
            return

        if self._database_url not in self._connection_pools:
            self._ensure_connection_pool()

        pool = self._connection_pools[self._database_url]

        with pool.connection() as conn:
            self._apply_workspace_context(conn)
            yield conn

    def _apply_workspace_context(self, conn: Connection) -> None:
        """Apply the current RLS workspace to one checked-out connection."""
        workspace_id = _current_workspace_id.get()
        with conn.cursor() as cur:
            if workspace_id is not None:
                cur.execute(
                    sql.SQL("SET app.current_workspace_id = {}").format(
                        sql.Literal(str(workspace_id))
                    )
                )
            else:
                cur.execute("SET app.current_workspace_id = ''")

    @contextmanager
    def transaction(self):
        """Run all client calls in this context on one atomic connection."""
        active_connection = self._transaction_connection.get()
        if active_connection is not None:
            with active_connection.transaction():
                yield
            return

        if self._database_url not in self._connection_pools:
            self._ensure_connection_pool()
        pool = self._connection_pools[self._database_url]
        with pool.connection() as conn:
            token = self._transaction_connection.set(conn)
            try:
                with conn.transaction():
                    self._apply_workspace_context(conn)
                    yield
            finally:
                self._transaction_connection.reset(token)

    def _convert_params(
        self, params: tuple | dict | None
    ) -> tuple | dict | None:
        """Convert UUID objects to strings for query parameters."""
        if params is None:
            return None

        from uuid import UUID

        def convert(value: Any) -> Any:
            if isinstance(value, UUID):
                return str(value)
            if isinstance(value, list):
                return [convert(v) for v in value]
            if isinstance(value, tuple):
                return tuple(convert(v) for v in value)
            if isinstance(value, dict):
                return {k: convert(v) for k, v in value.items()}
            return value

        return convert(params)

    def execute(
        self, query: str, params: tuple | dict | None = None
    ) -> list[dict[str, Any]]:
        """Execute query, return list of row dicts. Empty list if no results."""
        in_transaction = self._transaction_connection.get() is not None
        params = self._convert_params(params)
        with self.get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
                if cur.description:
                    return [dict(row) for row in cur.fetchall()]
                if not in_transaction:
                    conn.commit()
                return []

    def execute_single(
        self, query: str, params: tuple | dict | None = None
    ) -> dict[str, Any] | None:
        """Execute query, return first row or None."""
        results = self.execute(query, params)
        return results[0] if results else None

    def execute_scalar(
        self, query: str, params: tuple | dict | None = None
    ) -> Any:
        """Execute query, return first value of first row or None."""
        params = self._convert_params(params)
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                result = cur.fetchone()
                return result[0] if result else None

    def execute_returning(
        self, query: str, params: tuple | dict | None = None
    ) -> list[dict[str, Any]]:
        """Execute INSERT/UPDATE with RETURNING, return results."""
        in_transaction = self._transaction_connection.get() is not None
        params = self._convert_params(params)
        with self.get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
                results = [dict(row) for row in cur.fetchall()]
                if not in_transaction:
                    conn.commit()
                return results

    def health_check(self) -> bool:
        """Return True when PostgreSQL accepts a simple query."""
        return self.execute_scalar("SELECT 1") == 1

    def close(self) -> None:
        """Close connection pool."""
        if self._database_url in self._connection_pools:
            self._connection_pools[self._database_url].close()
            del self._connection_pools[self._database_url]

    @classmethod
    def close_all_pools(cls) -> None:
        """Close all connection pools."""
        for pool in cls._connection_pools.values():
            pool.close()
        cls._connection_pools.clear()
