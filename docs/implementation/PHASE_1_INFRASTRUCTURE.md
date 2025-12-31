# Phase 1: Infrastructure Clients

**Goal**: Establish connections to external services with proper error handling and fail-fast behavior.

**Estimated files**: 3
**Dependencies**: Phase 0 complete, external services running

---

## Prerequisites

Before starting Phase 1, ensure:

1. **Vault** is running and accessible
2. **PostgreSQL** is running with the schema applied
3. **Valkey** (Redis-compatible) is running
4. Phase 0 is complete and verified

---

## 1.1 clients/vault_client.py

**Purpose**: Retrieve secrets from HashiCorp Vault. All credentials flow through here.

### Implementation

```python
import os
import hvac
from typing import Any


class VaultError(Exception):
    """
    Vault is unavailable or secret not found.

    This is a fatal error - the application cannot function without secrets.
    """
    pass


class VaultClient:
    """
    HashiCorp Vault client for secrets management.

    All sensitive configuration (database URLs, API keys, etc.) is stored
    in Vault and retrieved through this client.

    Fail-fast behavior: If Vault is unavailable or a secret is missing,
    the application should not start.
    """

    def __init__(self, addr: str | None = None, token: str | None = None):
        """
        Initialize Vault client.

        Args:
            addr: Vault server address. Defaults to VAULT_ADDR env var.
            token: Authentication token. Defaults to VAULT_TOKEN env var.

        Raises:
            VaultError: If connection fails or authentication is invalid.
        """
        self.addr = addr or os.environ.get("VAULT_ADDR")
        self.token = token or os.environ.get("VAULT_TOKEN")

        if not self.addr:
            raise VaultError("VAULT_ADDR not set")
        if not self.token:
            raise VaultError("VAULT_TOKEN not set")

        self.client = hvac.Client(url=self.addr, token=self.token)

        # Verify connection
        if not self.client.is_authenticated():
            raise VaultError(f"Failed to authenticate with Vault at {self.addr}")

    def get_secret(self, path: str) -> dict[str, Any]:
        """
        Retrieve secret from Vault.

        Args:
            path: Secret path (e.g., "secret/data/crm/database")

        Returns:
            Secret data as dictionary.

        Raises:
            VaultError: If secret not found or Vault unavailable.

        IMPORTANT: Never returns None or empty dict on failure.
        Missing secrets are fatal errors.
        """
        try:
            response = self.client.secrets.kv.v2.read_secret_version(path=path)
            if response is None or "data" not in response or "data" not in response["data"]:
                raise VaultError(f"Secret not found at path: {path}")
            return response["data"]["data"]
        except hvac.exceptions.InvalidPath:
            raise VaultError(f"Secret not found at path: {path}")
        except hvac.exceptions.VaultError as e:
            raise VaultError(f"Vault error reading {path}: {e}")

    def get_database_url(self) -> str:
        """
        Get PostgreSQL connection URL.

        Expected secret structure at 'crm/database':
        {
            "url": "postgresql://user:pass@host:5432/dbname"
        }
        """
        secret = self.get_secret("crm/database")
        if "url" not in secret:
            raise VaultError("Database secret missing 'url' field")
        return secret["url"]

    def get_valkey_url(self) -> str:
        """
        Get Valkey connection URL.

        Expected secret structure at 'crm/valkey':
        {
            "url": "redis://host:6379/0"
        }
        """
        secret = self.get_secret("crm/valkey")
        if "url" not in secret:
            raise VaultError("Valkey secret missing 'url' field")
        return secret["url"]

    def get_email_credentials(self) -> dict[str, str]:
        """
        Get email service credentials.

        Expected secret structure at 'crm/email':
        {
            "api_key": "...",
            "from_address": "noreply@example.com"
        }
        """
        return self.get_secret("crm/email")

    def health_check(self) -> bool:
        """
        Verify Vault connectivity.

        Returns True if healthy.
        Raises VaultError if unhealthy.
        """
        if not self.client.is_authenticated():
            raise VaultError("Vault authentication lost")
        return True
```

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `VAULT_ADDR` | Vault server URL (e.g., `http://localhost:8200`) | Yes |
| `VAULT_TOKEN` | Authentication token | Yes |

### Vault Setup

```bash
# Enable KV secrets engine (if not already)
vault secrets enable -path=secret kv-v2

# Store database credentials
vault kv put secret/crm/database url="postgresql://crm_user:password@localhost:5432/crm"

# Store Valkey credentials
vault kv put secret/crm/valkey url="redis://localhost:6379/0"

# Store email credentials
vault kv put secret/crm/email api_key="your-api-key" from_address="noreply@example.com"
```

### Tests Required

```python
# tests/test_vault_client.py

def test_init_without_addr_raises():
    # Clear env vars
    with pytest.raises(VaultError, match="VAULT_ADDR not set"):
        VaultClient(addr=None, token="test")

def test_init_without_token_raises():
    with pytest.raises(VaultError, match="VAULT_TOKEN not set"):
        VaultClient(addr="http://localhost:8200", token=None)

def test_get_secret_not_found_raises():
    client = VaultClient()
    with pytest.raises(VaultError, match="not found"):
        client.get_secret("nonexistent/path")

def test_get_database_url_returns_string():
    client = VaultClient()
    url = client.get_database_url()
    assert url.startswith("postgresql://")

def test_health_check_returns_true():
    client = VaultClient()
    assert client.health_check() is True
```

---

## 1.2 clients/postgres_client.py

**Purpose**: PostgreSQL connection pool with RLS context injection.

### Implementation

```python
from contextlib import contextmanager
from uuid import UUID
from typing import Any
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from utils.user_context import get_current_user_id


class PostgresError(Exception):
    """Database operation failed."""
    pass


class PostgresClient:
    """
    PostgreSQL client with connection pooling and RLS support.

    Key behaviors:
    - Connection pool managed automatically
    - RLS context (app.current_user_id) set on every user-facing connection
    - Context cleared before connection returns to pool
    - Fail-fast on connection errors
    """

    def __init__(self, connection_url: str, pool_size: int = 10):
        """
        Initialize connection pool.

        Args:
            connection_url: PostgreSQL connection URL
            pool_size: Maximum pool size

        Raises:
            PostgresError: If connection fails
        """
        try:
            self.pool = ConnectionPool(
                connection_url,
                min_size=2,
                max_size=pool_size,
                kwargs={"row_factory": dict_row}
            )
            # Verify connectivity
            self.health_check()
        except Exception as e:
            raise PostgresError(f"Failed to connect to database: {e}")

    @contextmanager
    def connection(self, user_id: UUID | None = None):
        """
        Get a connection with RLS context set.

        Args:
            user_id: User ID for RLS. If None, uses get_current_user_id().

        Yields:
            Database connection with RLS context set.

        The connection is automatically returned to the pool on exit,
        and the RLS context is cleared.
        """
        if user_id is None:
            user_id = get_current_user_id()

        with self.pool.connection() as conn:
            # Set RLS context
            conn.execute(
                "SELECT set_config('app.current_user_id', %s, true)",
                (str(user_id),)
            )
            try:
                yield conn
            finally:
                # Clear RLS context before returning to pool
                conn.execute(
                    "SELECT set_config('app.current_user_id', '', true)"
                )

    @contextmanager
    def admin_connection(self):
        """
        Get a connection WITHOUT RLS context.

        USE ONLY FOR:
        - Schema migrations
        - Cross-user batch operations
        - System health checks

        NEVER use for user-facing operations.
        """
        with self.pool.connection() as conn:
            yield conn

    def execute(
        self,
        query: str,
        params: tuple = (),
        user_id: UUID | None = None
    ) -> list[dict[str, Any]]:
        """
        Execute query and return all results as list of dicts.

        Args:
            query: SQL query with %s placeholders
            params: Query parameters
            user_id: Optional explicit user ID for RLS

        Returns:
            List of row dicts. Empty list if no rows.

        Raises:
            PostgresError: On query failure (NOT on empty results)
        """
        try:
            with self.connection(user_id) as conn:
                result = conn.execute(query, params)
                return list(result.fetchall())
        except psycopg.Error as e:
            raise PostgresError(f"Query failed: {e}")

    def execute_one(
        self,
        query: str,
        params: tuple = (),
        user_id: UUID | None = None
    ) -> dict[str, Any] | None:
        """
        Execute query and return first result.

        Returns None if no rows found.
        """
        results = self.execute(query, params, user_id)
        return results[0] if results else None

    def execute_scalar(
        self,
        query: str,
        params: tuple = (),
        user_id: UUID | None = None
    ) -> Any:
        """
        Execute query and return single value from first row.

        Raises ValueError if no rows returned.
        """
        row = self.execute_one(query, params, user_id)
        if row is None:
            raise ValueError("Query returned no rows")
        return list(row.values())[0]

    def execute_admin(
        self,
        query: str,
        params: tuple = ()
    ) -> list[dict[str, Any]]:
        """
        Execute query without RLS context.

        USE ONLY FOR admin operations.
        """
        try:
            with self.admin_connection() as conn:
                result = conn.execute(query, params)
                return list(result.fetchall())
        except psycopg.Error as e:
            raise PostgresError(f"Query failed: {e}")

    def health_check(self) -> bool:
        """
        Verify database connectivity.

        Returns True if healthy.
        Raises PostgresError if unhealthy.
        """
        try:
            with self.admin_connection() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception as e:
            raise PostgresError(f"Health check failed: {e}")

    def close(self) -> None:
        """Close connection pool."""
        self.pool.close()
```

### Database Schema Setup

Before using, ensure RLS is enabled:

```sql
-- Enable RLS on user-scoped tables
ALTER TABLE contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE addresses ENABLE ROW LEVEL SECURITY;
-- ... etc for all user-scoped tables

-- Create RLS policy
CREATE POLICY user_isolation ON contacts
    FOR ALL
    USING (user_id = current_setting('app.current_user_id')::uuid);

-- Repeat for each table
CREATE POLICY user_isolation ON tickets
    FOR ALL
    USING (user_id = current_setting('app.current_user_id')::uuid);

-- Tables without user_id (like users themselves) don't get RLS
```

### Key Decisions

- RLS context set on EVERY user-facing connection
- Context cleared in finally block (prevents leakage)
- `admin_connection()` is explicit and loud about bypassing RLS
- Empty results are valid (return `[]`), failures raise
- Connection pool handles connection lifecycle

### Tests Required

```python
# tests/test_postgres_client.py

def test_connection_sets_rls_context():
    client = PostgresClient(get_test_db_url())
    user_id = uuid4()

    with client.connection(user_id) as conn:
        result = conn.execute("SELECT current_setting('app.current_user_id')").fetchone()
        assert result[0] == str(user_id)

def test_rls_context_cleared_after_connection():
    client = PostgresClient(get_test_db_url())
    user_id = uuid4()

    with client.connection(user_id) as conn:
        pass  # Connection used and returned

    # Get fresh connection and verify context is empty
    with client.admin_connection() as conn:
        result = conn.execute("SELECT current_setting('app.current_user_id', true)").fetchone()
        assert result[0] == ""

def test_execute_returns_list_of_dicts():
    client = PostgresClient(get_test_db_url())
    results = client.execute_admin("SELECT 1 as num, 'hello' as word")
    assert results == [{"num": 1, "word": "hello"}]

def test_execute_one_returns_single_dict():
    client = PostgresClient(get_test_db_url())
    result = client.execute_admin("SELECT 1 as num").fetchone()
    assert result == {"num": 1}

def test_execute_one_returns_none_for_empty():
    client = PostgresClient(get_test_db_url())
    result = client.execute_admin("SELECT 1 WHERE false").fetchone()
    assert result is None

def test_rls_filters_data():
    """Integration test: verify RLS actually filters data."""
    client = PostgresClient(get_test_db_url())

    user_a = uuid4()
    user_b = uuid4()

    # Insert as admin
    client.execute_admin(
        "INSERT INTO contacts (id, user_id, name) VALUES (%s, %s, %s)",
        (uuid4(), user_a, "User A Contact")
    )
    client.execute_admin(
        "INSERT INTO contacts (id, user_id, name) VALUES (%s, %s, %s)",
        (uuid4(), user_b, "User B Contact")
    )

    # Query as user A - should only see their contact
    contacts = client.execute("SELECT * FROM contacts", user_id=user_a)
    assert len(contacts) == 1
    assert contacts[0]["name"] == "User A Contact"

def test_health_check_returns_true():
    client = PostgresClient(get_test_db_url())
    assert client.health_check() is True
```

---

## 1.3 clients/valkey_client.py

**Purpose**: Valkey (Redis-compatible) client for sessions and rate limiting.

### Implementation

```python
import redis
from typing import Any


class ValkeyError(Exception):
    """Valkey operation failed."""
    pass


class ValkeyClient:
    """
    Valkey (Redis-compatible) client for ephemeral data.

    Used for:
    - Session token storage
    - Rate limiting counters
    - Short-lived caches

    Fail-fast behavior: Connection failures raise immediately.
    """

    def __init__(self, connection_url: str):
        """
        Initialize Valkey client.

        Args:
            connection_url: Redis-compatible URL (e.g., redis://localhost:6379/0)

        Raises:
            ValkeyError: If connection fails
        """
        try:
            self.client = redis.from_url(
                connection_url,
                decode_responses=True  # Return strings, not bytes
            )
            # Verify connectivity
            self.health_check()
        except redis.RedisError as e:
            raise ValkeyError(f"Failed to connect to Valkey: {e}")

    def get(self, key: str) -> str | None:
        """
        Get value by key.

        Returns None if key doesn't exist.
        Raises ValkeyError on connection failure.
        """
        try:
            return self.client.get(key)
        except redis.RedisError as e:
            raise ValkeyError(f"Get failed for key {key}: {e}")

    def set(
        self,
        key: str,
        value: str,
        expire_seconds: int | None = None
    ) -> None:
        """
        Set value with optional expiration.

        Args:
            key: Key name
            value: Value (will be stored as string)
            expire_seconds: TTL in seconds (None for no expiry)
        """
        try:
            if expire_seconds:
                self.client.setex(key, expire_seconds, value)
            else:
                self.client.set(key, value)
        except redis.RedisError as e:
            raise ValkeyError(f"Set failed for key {key}: {e}")

    def delete(self, key: str) -> bool:
        """
        Delete key.

        Returns True if key existed and was deleted.
        """
        try:
            return bool(self.client.delete(key))
        except redis.RedisError as e:
            raise ValkeyError(f"Delete failed for key {key}: {e}")

    def incr(self, key: str) -> int:
        """
        Increment counter.

        Creates key with value 1 if it doesn't exist.
        Returns new value.
        """
        try:
            return self.client.incr(key)
        except redis.RedisError as e:
            raise ValkeyError(f"Incr failed for key {key}: {e}")

    def expire(self, key: str, seconds: int) -> bool:
        """
        Set expiration on existing key.

        Returns True if key exists and expiry was set.
        """
        try:
            return bool(self.client.expire(key, seconds))
        except redis.RedisError as e:
            raise ValkeyError(f"Expire failed for key {key}: {e}")

    def ttl(self, key: str) -> int:
        """
        Get remaining TTL in seconds.

        Returns:
            -2 if key doesn't exist
            -1 if key has no expiry
            Otherwise, seconds remaining
        """
        try:
            return self.client.ttl(key)
        except redis.RedisError as e:
            raise ValkeyError(f"TTL failed for key {key}: {e}")

    def exists(self, key: str) -> bool:
        """Check if key exists."""
        try:
            return bool(self.client.exists(key))
        except redis.RedisError as e:
            raise ValkeyError(f"Exists failed for key {key}: {e}")

    def get_json(self, key: str) -> dict | None:
        """
        Get value and parse as JSON.

        Returns None if key doesn't exist.
        Raises ValkeyError if value is not valid JSON.
        """
        import json
        value = self.get(key)
        if value is None:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            raise ValkeyError(f"Invalid JSON at key {key}: {e}")

    def set_json(
        self,
        key: str,
        value: dict,
        expire_seconds: int | None = None
    ) -> None:
        """
        Serialize value as JSON and store.
        """
        import json
        self.set(key, json.dumps(value), expire_seconds)

    def health_check(self) -> bool:
        """
        Verify connectivity.

        Returns True if healthy.
        Raises ValkeyError if unhealthy.
        """
        try:
            self.client.ping()
            return True
        except redis.RedisError as e:
            raise ValkeyError(f"Health check failed: {e}")

    def close(self) -> None:
        """Close connection."""
        self.client.close()
```

### Key Decisions

- `get()` returning None is valid (key not found), connection failure raises
- `decode_responses=True` so all values are strings
- JSON helpers provided for structured data
- All operations fail-fast on connection issues

### Tests Required

```python
# tests/test_valkey_client.py

def test_set_and_get():
    client = ValkeyClient(get_test_valkey_url())
    client.set("test_key", "test_value")
    assert client.get("test_key") == "test_value"
    client.delete("test_key")

def test_get_nonexistent_returns_none():
    client = ValkeyClient(get_test_valkey_url())
    assert client.get("nonexistent_key_12345") is None

def test_expiration():
    client = ValkeyClient(get_test_valkey_url())
    client.set("expire_test", "value", expire_seconds=1)
    assert client.get("expire_test") == "value"

    import time
    time.sleep(1.1)
    assert client.get("expire_test") is None

def test_incr_creates_key():
    client = ValkeyClient(get_test_valkey_url())
    client.delete("counter_test")  # Ensure clean state

    assert client.incr("counter_test") == 1
    assert client.incr("counter_test") == 2
    assert client.incr("counter_test") == 3

    client.delete("counter_test")

def test_ttl():
    client = ValkeyClient(get_test_valkey_url())
    client.set("ttl_test", "value", expire_seconds=100)

    ttl = client.ttl("ttl_test")
    assert 95 <= ttl <= 100

    client.delete("ttl_test")

def test_json_roundtrip():
    client = ValkeyClient(get_test_valkey_url())
    data = {"user_id": "123", "roles": ["admin", "user"]}

    client.set_json("json_test", data, expire_seconds=60)
    result = client.get_json("json_test")

    assert result == data
    client.delete("json_test")

def test_health_check():
    client = ValkeyClient(get_test_valkey_url())
    assert client.health_check() is True
```

---

## Phase 1 Verification Checklist

Before proceeding to Phase 2:

### Infrastructure Running

- [ ] Vault server is accessible at `VAULT_ADDR`
- [ ] Secrets are stored at correct paths (`crm/database`, `crm/valkey`)
- [ ] PostgreSQL is running with RLS-enabled schema
- [ ] Valkey is running and accessible

### Client Tests

- [ ] `pytest tests/test_vault_client.py` - all tests pass
- [ ] `pytest tests/test_postgres_client.py` - all tests pass
- [ ] `pytest tests/test_valkey_client.py` - all tests pass

### Integration Verification

```python
# Quick integration check
from clients.vault_client import VaultClient
from clients.postgres_client import PostgresClient
from clients.valkey_client import ValkeyClient

vault = VaultClient()
postgres = PostgresClient(vault.get_database_url())
valkey = ValkeyClient(vault.get_valkey_url())

assert vault.health_check()
assert postgres.health_check()
assert valkey.health_check()

print("All infrastructure clients healthy!")
```

---

## Next Phase

Proceed to [Phase 2: Auth System](./PHASE_2_AUTH.md)
