# Accumulated Knowledge During Phase Implementation

Living document capturing lessons learned, patterns established, and decisions made during implementation. Reference this at the start of each phase to maintain consistency.

---

## Phase 0: Foundation (Complete)

### What Was Built

| File | Purpose |
|------|---------|
| `utils/timezone.py` | UTC-everywhere time handling |
| `utils/user_context.py` | Contextvar for user identity propagation |
| `auth/types.py` | Pydantic models for auth domain |
| `auth/exceptions.py` | Typed auth exceptions |
| `auth/config.py` | Auth configuration with validation |
| `api/base.py` | Unified API response format + ErrorCodes |

### TDD Workflow Established

1. Write test file first
2. Run tests - confirm they fail
3. Write implementation
4. Run tests - confirm they pass
5. Move to next module

Do NOT create stub files with `NotImplementedError`. Write the real implementation directly.

### Code Style Decisions

**No `__all__`**: Use explicit imports in `__init__.py`. `__all__` is for controlling `from x import *` which we don't use.

**Docstrings satisfy class body**: No need for `pass` in exception classes or simple models - the docstring alone is sufficient.

```python
# Good
class AuthError(Exception):
    """Base class for auth errors."""

# Unnecessary
class AuthError(Exception):
    """Base class for auth errors."""
    pass
```

**Explicit imports in `__init__.py`**:
```python
# Good
from auth.exceptions import AuthError, InvalidTokenError

# Not needed
__all__ = ["AuthError", "InvalidTokenError"]
```

### Testing Philosophy

**Test validation, not instantiation**: Don't test that valid Pydantic models can be created - that's testing Pydantic, not your code.

```python
# Useful - tests YOUR schema rejects bad data
def test_rejects_invalid_email(self):
    with pytest.raises(ValidationError):
        User(id=uuid4(), email="not-an-email", created_at=now)

# Theater - just tests Pydantic works
def test_valid_user(self):
    user = User(id=uuid4(), email="test@example.com", created_at=now)
    assert user.email == "test@example.com"  # Of course it does
```

**Test structure mirrors source**: `tests/auth/test_config.py` tests `auth/config.py`. Makes tests easy to find.

### Security Decisions

**Fail closed on tokens**: `MagicLinkToken.used` has no default - must be explicitly set. A token without explicit state should fail validation.

**No assumptions on naive datetimes**: `parse_iso("2024-01-01T12:00:00")` raises ValueError. If you meant UTC, say UTC.

**Server generates request IDs**: Never accept client-provided request IDs. Always `str(uuid4())`.

**No env var config**: Configuration comes from vault or uses defaults. No `AUTH_MAGIC_LINK_EXPIRY_MINUTES` environment variables.

### Business Parameters

| Setting | Value | Rationale |
|---------|-------|-----------|
| Session expiry | 90 days (2160 hours) | Long-lived for mobile convenience |
| Magic link expiry | 10 minutes | Short for security |
| Rate limit | 5 attempts / 15 min | Prevent abuse |

### Test Infrastructure

**conftest.py fixtures**:
- `reset_user_context` (autouse) - clears context before/after each test
- `test_user_id` - returns `TEST_USER_ID` constant
- `authenticated_context` - sets user context for duration of test
- `db_connection` - stub returning None (Phase 1 implementation)
- `reset_db_state` - stub no-op (Phase 1 implementation)

**Test user constants**:
```python
TEST_USER_EMAIL = "testuser@here.local"
TEST_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
```

---

## Patterns to Follow

### API Response Format

All endpoints return:
```python
APIResponse(
    success=True/False,
    data={...} or None,
    error=APIError(code="...", message="...") or None,
    meta=APIMeta(timestamp=now_utc(), request_id=str(uuid4()))
)
```

Use `success_response(data)` and `error_response(code, message)` helpers.

### Error Codes

Always use `ErrorCodes.X` constants, never string literals:
```python
# Good
error_response(ErrorCodes.NOT_FOUND, "Contact not found")

# Bad
error_response("NOT_FOUND", "Contact not found")
```

Add new codes to `docs/ERROR_CODES.md` first, then to `ErrorCodes` class.

### Timezone Handling

```python
from utils.timezone import now_utc, to_utc, to_local, parse_iso

# Current time
now = now_utc()

# Convert aware datetime to UTC
utc_time = to_utc(some_aware_datetime)

# Display only - at render boundary
local_time = to_local(utc_time, "America/Chicago")

# Parse ISO string (must have timezone)
dt = parse_iso("2024-01-01T12:00:00Z")
```

### User Context

```python
from utils.user_context import get_current_user_id, user_context

# In request handlers (after auth middleware sets context)
user_id = get_current_user_id()  # Raises if not set

# In tests or batch jobs
with user_context(some_user_id):
    # Operations here use some_user_id for RLS
    do_something()
```

---

## Common Mistakes to Avoid

1. **Don't create stub files** - Write real implementation directly after tests

2. **Don't test Pydantic's validation works** - Test that YOUR schema rejects bad data

3. **Don't use `pass` with docstrings** - The docstring is the body

4. **Don't accept naive datetimes** - Always require timezone info

5. **Don't use `__all__`** - Explicit imports are clearer

6. **Don't add env var overrides** - Vault or defaults only

7. **Don't let clients set request IDs** - Server generates them

8. **Don't default security-sensitive fields** - Make them required (fail closed)

---

## Phase 1: Infrastructure Clients (Complete)

### What Was Built

| File | Purpose |
|------|---------|
| `clients/vault_client.py` | HashiCorp Vault with AppRole auth |
| `clients/postgres_client.py` | ThreadedConnectionPool + automatic RLS from contextvar |
| `clients/valkey_client.py` | Redis-compatible session/cache store |
| `tests/clients/test_vault_client.py` | 9 tests |
| `tests/clients/test_postgres_client.py` | 12 tests |
| `tests/clients/test_valkey_client.py` | 17 tests |

### Key Learnings

**AppRole over Token**: VaultClient uses AppRole authentication (`VAULT_ROLE_ID` + `VAULT_SECRET_ID`) rather than tokens. Tokens expire; AppRole is designed for applications.

**Path Scoping**: All Vault paths are prefixed with `crm/` internally. Caller passes `"database"`, client accesses `crm/database`. This prevents path traversal attacks.

**Contextvar for RLS**: PostgresClient reads user ID from `utils.user_context._current_user_id` automatically on every connection. No explicit `user_id` parameter needed - context flows from auth middleware through to database.

**Fail-Fast RLS**: When no user context is set, `app.current_user_id` is set to empty string. RLS policies cast this to UUID which fails immediately. This is better than silently returning zero rows - the error is loud and obvious.

**Shell Env Override**: When running outside pytest, shell environment variables may contain credentials from other projects (MIRA). Use `load_dotenv('.env', override=True)` to ensure CRM's credentials are used.

**Two Test Users**: `TEST_USER_ID` and `TEST_USER_B_ID` enable proper RLS isolation testing. User A inserts data, User B queries, should see nothing.

**db_admin Fixture**: Uses `crm_admin` (with BYPASSRLS) for test setup/teardown operations like TRUNCATE. The regular `db` fixture uses `crm_dbuser` with RLS enforced.

### Implementation Deviations from Spec

| Spec Said | We Did | Why |
|-----------|--------|-----|
| Token auth | AppRole auth | Tokens expire, AppRole is for apps |
| Explicit user_id param | Contextvar automatic | Ambient context, no parameter threading |
| VaultError wrapper | No wrapper | Let redis.ConnectionError propagate |

### Test Infrastructure Updates

**conftest.py now has**:
```python
# Two test users for RLS isolation
TEST_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
TEST_USER_B_ID = UUID("00000000-0000-0000-0000-000000000002")

# Session-scoped fixtures
@pytest.fixture(scope="session")
def db():  # RLS-enforced (crm_dbuser)

@pytest.fixture(scope="session")
def db_admin():  # Bypasses RLS (crm_admin)

@pytest.fixture(scope="session")
def valkey():  # ValkeyClient

# Autouse fixture resets DB state before each test
@pytest.fixture(autouse=True)
def reset_db_state(db_admin):
    db_admin.execute("TRUNCATE customers, ... CASCADE")
    db_admin.execute("INSERT INTO users ...")
```

### Environment Setup

**.env file** (not committed, in .gitignore):
```
VAULT_ADDR=http://127.0.0.1:8200
VAULT_ROLE_ID=<crm-approle-role-id>
VAULT_SECRET_ID=<crm-approle-secret-id>
```

**Vault secrets**:
```
secret/crm/database → url, admin_url
secret/crm/valkey → url
secret/crm/email → api_key, from_address
secret/crm/llm → api_key, base_url
secret/crm/stripe → secret_key, webhook_secret
```

---

## Common Mistakes to Avoid

1. **Don't create stub files** - Write real implementation directly after tests

2. **Don't test Pydantic's validation works** - Test that YOUR schema rejects bad data

3. **Don't use `pass` with docstrings** - The docstring is the body

4. **Don't accept naive datetimes** - Always require timezone info

5. **Don't use `__all__`** - Explicit imports are clearer

6. **Don't add env var overrides** - Vault or defaults only

7. **Don't let clients set request IDs** - Server generates them

8. **Don't default security-sensitive fields** - Make them required (fail closed)

9. **Don't forget `override=True` in load_dotenv** - Shell env may have other project credentials

10. **Don't use regular db fixture for TRUNCATE** - Use db_admin (crm_admin has BYPASSRLS)

---

## Phase 2: Auth System (In Progress)

### What Was Built

| File | Purpose |
|------|---------|
| `clients/email_client.py` | HTTP gateway client with HMAC signing |
| `auth/database.py` | User and magic link token operations |

### Database Operations

**Direct psql commands**: For schema migrations during development, use the taylut user:
```bash
psql -U taylut -d crm -c "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;"
```

**Schema changes made**:
- Added `is_active` column to `users` table (for freezing logins)

### UUID Handling in Tests

PostgresClient returns native UUID objects. When extracting IDs from query results:
```python
# Handle both string and UUID return types
user_id = result[0]["id"]
if isinstance(user_id, str):
    user_id = UUID(user_id)
```

### Test Cleanup Pattern

Use fixtures to track and clean up test data:
```python
@pytest.fixture
def cleanup_user(db_admin):
    """Track users created during tests for cleanup."""
    created_emails = []

    def _track(email):
        created_emails.append(email.lower())

    yield _track

    # Cleanup
    for email in created_emails:
        db_admin.execute("DELETE FROM users WHERE email = %s", (email,))
```

### Email Gateway Pattern

Using HTTP gateway (same as botwithmemory) instead of direct SMTP:
- Payload: `{"email": ..., "token": ..., "app_url": ...}`
- Headers: `X-API-Key`, `X-Signature` (HMAC-SHA256)
- Vault secrets: `secret/crm/email` → `gateway_url`, `api_key`, `hmac_secret`

### Auth Tables Have NO RLS

Auth tables (`users`, `magic_link_tokens`, `security_events`) are accessed before user context exists. They have no RLS policies - authentication happens before authorization.

### Dependencies
- All Phase 1 clients (Vault for secrets, Postgres for users/sessions, Valkey for rate limiting)

---

*Update this document at the end of each phase with new learnings.*
