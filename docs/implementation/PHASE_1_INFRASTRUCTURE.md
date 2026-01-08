# Phase 1: Infrastructure Clients

**Status**: ✅ Complete
**Goal**: Establish connections to external services with proper error handling and fail-fast behavior.

**Files created**: 3
**Tests**: 38 passing
**Dependencies**: Phase 0 complete, external services running

---

## Prerequisites

Before starting Phase 1, ensure:

1. **Vault** is running and accessible with AppRole configured
2. **PostgreSQL** is running with the schema applied
3. **Valkey** (Redis-compatible) is running
4. Phase 0 is complete and verified

---

## 1.1 clients/vault_client.py

**Purpose**: Retrieve secrets from HashiCorp Vault. All credentials flow through here.

### Implementation Notes

**AppRole Authentication** (not token-based): Uses `VAULT_ROLE_ID` and `VAULT_SECRET_ID` environment variables. AppRole is preferred for application authentication as tokens can expire.

**Path Scoping**: All secret paths are prefixed with `crm/` internally. Caller passes `"database"`, client accesses `crm/database`. This prevents path traversal.

**Singleton Pattern**: Module-level `_vault_client_instance` ensures single client instance. Convenience functions (`get_database_url()`, etc.) use this singleton.

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| AppRole over token | Tokens expire; AppRole is for applications |
| Path prefix `crm/` | Scoped access, no path traversal |
| `get_secret(path, field)` returns string | Caller specifies field, no dict unpacking needed |
| Singleton with convenience functions | Simple API: `get_database_url()` just works |

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `VAULT_ADDR` | Vault server URL (e.g., `http://localhost:8200`) | Yes |
| `VAULT_ROLE_ID` | AppRole Role ID | Yes |
| `VAULT_SECRET_ID` | AppRole Secret ID | Yes |

### Vault Secrets Structure

```
secret/crm/database
  └── url: postgresql://crm_dbuser:...@localhost:5432/crm
  └── admin_url: postgresql://crm_admin:...@localhost:5432/crm

secret/crm/valkey
  └── url: redis://localhost:6379/0

secret/crm/email
  └── api_key: ...
  └── from_address: noreply@example.com

secret/crm/llm
  └── api_key: ...
  └── base_url: ...

secret/crm/stripe
  └── secret_key: ...
  └── webhook_secret: ...
```

### Tests (9 passing)

- `TestVaultClientInit`: missing addr/credentials raises, invalid credentials raises, valid credentials authenticate
- `TestGetSecret`: returns field value, missing path raises, missing field raises KeyError
- `TestConvenienceFunctions`: `get_database_url()` returns postgresql://, `get_valkey_url()` returns redis://

---

## 1.2 clients/postgres_client.py

**Purpose**: PostgreSQL connection pool with automatic RLS context from contextvar.

### Implementation Notes

**psycopg2 with ThreadedConnectionPool**: Uses psycopg2 (not psycopg3) for compatibility. Class-level connection pools are shared across instances keyed by database URL.

**Automatic RLS Context**: Reads user ID from `utils.user_context._current_user_id` contextvar on every `get_connection()` call. No explicit user_id parameter needed.

**Fail-Fast on No Context**: When no user context is set, `app.current_user_id` is set to empty string. RLS policies cast this to UUID which fails, returning zero rows. This is intentional fail-fast behavior - queries on RLS tables without context error immediately rather than silently returning nothing.

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| psycopg2 over psycopg3 | Mature, widely deployed, ThreadedConnectionPool built-in |
| Contextvar for user ID | Ambient context - no parameter threading through call stack |
| Empty string on no context | UUID cast fails = fail-fast on RLS tables |
| Class-level pool sharing | Multiple PostgresClient instances share same pool per URL |
| `execute_returning()` for INSERT/UPDATE | Separate method commits and returns RETURNING results |

### RLS Behavior

```
With user context set:
  → app.current_user_id = "uuid-string"
  → RLS policy: user_id = current_setting('app.current_user_id')::uuid
  → User sees only their data

Without user context:
  → app.current_user_id = ""
  → UUID cast fails: invalid input syntax for type uuid: ""
  → Query errors immediately (fail-fast)

With admin connection (db_admin fixture):
  → crm_admin user has BYPASSRLS
  → Sees all data, used for test setup/teardown
```

### Tests (12 passing)

- `TestPostgresClientInit`: creates pool with valid URL
- `TestRLSContext`: sets user context from contextvar, clears context without user ID
- `TestExecuteMethods`: execute returns list of dicts, execute_single returns dict or None, execute_scalar returns value or None
- `TestUserIsolation`: user only sees own data, no context errors on RLS tables, cannot see other user's data by ID

---

## 1.3 clients/valkey_client.py

**Purpose**: Valkey (Redis-compatible) client for sessions and rate limiting.

### Implementation Notes

**Simple redis-py Wrapper**: Uses `redis.from_url()` with `decode_responses=True`. No async, no TTL monitoring, no binary client - just the essentials.

**Fail-Fast**: Connection verified at init with `ping()`. Connection failures raise immediately.

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| redis-py (not valkey lib) | Redis protocol compatible, widely used |
| `decode_responses=True` | All values are strings, not bytes |
| `get()` returns None for missing | None = not found, exception = connection failure |
| JSON helpers built-in | `set_json()`/`get_json()` for structured data |
| No ValkeyError wrapper | Let redis.ConnectionError propagate - it's descriptive |

### Operations

| Method | Returns | Notes |
|--------|---------|-------|
| `get(key)` | `str \| None` | None if key doesn't exist |
| `set(key, value, expire_seconds)` | None | Optional TTL |
| `delete(key)` | `bool` | True if key existed |
| `exists(key)` | `bool` | Key existence check |
| `ttl(key)` | `int` | -2 missing, -1 no expiry, else seconds |
| `incr(key)` | `int` | Creates with 1 if missing |
| `set_json(key, value, expire_seconds)` | None | JSON serialization |
| `get_json(key)` | `dict \| list \| None` | Raises ValueError on invalid JSON |
| `ping()` | `bool` | Health check |

### Tests (17 passing)

- `TestValkeyClientInit`: connects with valid URL
- `TestBasicOperations`: set/get, get missing returns None, delete returns bool, exists
- `TestExpiration`: set with expiration, TTL returns remaining, TTL -2 for missing, TTL -1 for no expiry
- `TestCounter`: incr creates with 1, incr increments
- `TestJsonHelpers`: JSON roundtrip, get_json missing returns None, get_json invalid raises ValueError
- `TestHealthCheck`: ping returns True

---

## Phase 1 Verification

### Checklist (Complete)

- [x] Vault server accessible with AppRole
- [x] Secrets stored at `crm/database`, `crm/valkey`
- [x] PostgreSQL running with RLS-enabled schema
- [x] Valkey running and accessible
- [x] `pytest tests/clients/test_vault_client.py` - 9 tests pass
- [x] `pytest tests/clients/test_postgres_client.py` - 12 tests pass
- [x] `pytest tests/clients/test_valkey_client.py` - 17 tests pass

### Integration Check

```python
from pathlib import Path
from dotenv import load_dotenv

# Load .env with override (shell may have other project's credentials)
load_dotenv(Path('.env'), override=True)

from clients import VaultClient, PostgresClient, ValkeyClient
from clients.vault_client import get_database_url, get_valkey_url

vault = VaultClient()
postgres = PostgresClient(get_database_url())
valkey = ValkeyClient(get_valkey_url())

assert valkey.ping() is True
print("All infrastructure clients healthy!")
```

**Note**: The `override=True` is required because shell environment may have credentials from other projects (e.g., MIRA). The `.env` file contains CRM-specific Vault AppRole credentials.

---

## Test Infrastructure

### conftest.py Fixtures

| Fixture | Scope | Purpose |
|---------|-------|---------|
| `db` | session | PostgresClient with RLS (crm_dbuser) |
| `db_admin` | session | PostgresClient bypassing RLS (crm_admin) |
| `valkey` | session | ValkeyClient |
| `reset_db_state` | function (autouse) | Truncates tables, ensures test users exist |
| `reset_user_context` | function (autouse) | Clears contextvar before/after each test |

### Test Users

```python
TEST_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
TEST_USER_EMAIL = "testuser@test.local"

TEST_USER_B_ID = UUID("00000000-0000-0000-0000-000000000002")
TEST_USER_B_EMAIL = "testuser-b@test.local"
```

Two test users enable RLS isolation testing - User A cannot see User B's data.

---

## Next Phase

Proceed to [Phase 2: Auth System](./PHASE_2_AUTH.md)
