"""
PostgreSQL client with connection pooling and RLS user isolation.

Uses psycopg2 with ThreadedConnectionPool. User isolation enforced via
PostgreSQL Row Level Security - automatically reads user ID from contextvar
and sets app.current_user_id on each connection.

Security: No user context = see nothing (RLS blocks all rows). This is safe.
True admin bypass requires connecting as crm_admin with BYPASSRLS.
"""

import logging
import threading
from contextlib import contextmanager
from typing import Any, Dict, List, Tuple
from uuid import UUID

import psycopg2
import psycopg2.extras
import psycopg2.pool

from utils.user_context import _current_user_id

logger = logging.getLogger(__name__)

# Global JSONB registration flag
_jsonb_registered = False


class PostgresClient:
    """
    PostgreSQL client with automatic RLS context from contextvar.

    User context is read from utils.user_context contextvar on each query.
    - User context set → sees only their data (RLS filtered)
    - No user context → sees nothing (RLS blocks all rows)

    Usage:
        db = PostgresClient(database_url)

        # With user context (normal request flow)
        with user_context(user_id):
            contacts = db.execute("SELECT * FROM contacts")  # User's data only

        # Without user context
        contacts = db.execute("SELECT * FROM contacts")  # Empty - RLS blocks
    """

    # Class-level connection pools shared across instances
    _connection_pools: Dict[str, psycopg2.pool.ThreadedConnectionPool] = {}
    _pools_lock = threading.RLock()

    def __init__(self, database_url: str):
        self._database_url = database_url
        self._ensure_connection_pool()

    def _ensure_connection_pool(self) -> None:
        """Create connection pool if it doesn't exist."""
        with self._pools_lock:
            if self._database_url not in self._connection_pools:
                pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=2,
                    maxconn=20,
                    dsn=self._database_url,
                    connect_timeout=30,
                )

                global _jsonb_registered
                if not _jsonb_registered:
                    psycopg2.extras.register_default_jsonb(globally=True)
                    _jsonb_registered = True

                self._connection_pools[self._database_url] = pool
                logger.info("Connection pool created")

    @contextmanager
    def get_connection(self):
        """Get connection with RLS context from contextvar."""
        if self._database_url not in self._connection_pools:
            self._ensure_connection_pool()

        pool = self._connection_pools[self._database_url]
        conn = None

        try:
            conn = pool.getconn()
            if conn is None:
                raise RuntimeError("Could not get connection from pool")

            user_id = _current_user_id.get()

            with conn.cursor() as cur:
                if user_id is not None:
                    cur.execute("SET app.current_user_id = %s", (str(user_id),))
                else:
                    # Set to empty string to clear context
                    # RLS policies use ::uuid cast which fails on empty string = no rows
                    cur.execute("SET app.current_user_id = ''")

            yield conn

        finally:
            if conn:
                pool.putconn(conn)

    def _convert_params(self, params: Tuple | Dict | None) -> Tuple | Dict | None:
        """Convert UUID objects to strings."""
        if params is None:
            return None

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

    def execute(self, query: str, params: Tuple | Dict | None = None) -> List[Dict[str, Any]]:
        """Execute query, return list of row dicts. Empty list if no results."""
        params = self._convert_params(params)
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                if cur.description:
                    return [dict(row) for row in cur.fetchall()]
                conn.commit()
                return []

    def execute_single(self, query: str, params: Tuple | Dict | None = None) -> Dict[str, Any] | None:
        """Execute query, return first row or None."""
        results = self.execute(query, params)
        return results[0] if results else None

    def execute_scalar(self, query: str, params: Tuple | Dict | None = None) -> Any:
        """Execute query, return first value of first row or None."""
        params = self._convert_params(params)
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                result = cur.fetchone()
                return result[0] if result else None

    def execute_returning(self, query: str, params: Tuple | Dict | None = None) -> List[Dict[str, Any]]:
        """Execute INSERT/UPDATE with RETURNING, return results."""
        params = self._convert_params(params)
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                conn.commit()
                return [dict(row) for row in cur.fetchall()]

    def close(self) -> None:
        """Close connection pool."""
        with self._pools_lock:
            if self._database_url in self._connection_pools:
                self._connection_pools[self._database_url].closeall()
                del self._connection_pools[self._database_url]

    @classmethod
    def close_all_pools(cls) -> None:
        """Close all connection pools."""
        with cls._pools_lock:
            for pool in cls._connection_pools.values():
                pool.closeall()
            cls._connection_pools.clear()
