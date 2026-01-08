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

## Phase 1: Infrastructure Clients (Next)

### What's Coming
- `clients/vault_client.py` - Secrets management
- `clients/postgres_client.py` - Connection pool + RLS context
- `clients/valkey_client.py` - Session store + rate limiting

### Fixtures to Implement
- Wire up `db_connection` to actual test database
- Implement `reset_db_state` to truncate + re-seed test user
- Implement `ensure_test_user` to return User model

### Dependencies
- Vault client first (others depend on it for credentials)
- Then postgres and valkey in parallel

---

*Update this document at the end of each phase with new learnings.*
