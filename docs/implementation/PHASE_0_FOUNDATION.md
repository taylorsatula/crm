# Phase 0: Foundation

**Status**: Complete (2025-01-07)

**Goal**: Establish the zero-dependency utilities that everything else builds upon.

**Files**: 6
**Dependencies**: None (stdlib + pydantic only)

## Implementation Notes

Deviations from original spec:

| Item | Spec | Implemented | Rationale |
|------|------|-------------|-----------|
| `parse_iso()` on naive | Assume UTC | Raise ValueError | No assumptions - explicit is better |
| `MagicLinkToken.used` | Default False | Required field | Fail closed - state must be explicit |
| `load_auth_config()` | Load from env vars | Not implemented | Vault only - no env var secrets |
| Session expiry | 7 days | 90 days | Business requirement |
| Magic link expiry | 15 minutes | 10 minutes | Business requirement |
| `success_response()` | Accept request_id param | No param | Server always generates |

Test count: 51 passing

---

## 0.1 utils/timezone.py

**Purpose**: UTC-everywhere time handling. Eliminates timezone bugs at the source.

### Implementation

```python
from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo

def now_utc() -> datetime:
    """
    Current time in UTC.

    Use this instead of datetime.now() everywhere.
    """
    return datetime.now(timezone.utc)


def to_utc(dt: datetime) -> datetime:
    """
    Convert a datetime to UTC.

    Raises ValueError if datetime is naive (no timezone).
    """
    if dt.tzinfo is None:
        raise ValueError("Cannot convert naive datetime to UTC. Datetime must be timezone-aware.")
    return dt.astimezone(timezone.utc)


def to_local(dt: datetime, tz_name: str) -> datetime:
    """
    Convert UTC datetime to local timezone for display.

    ONLY use this at display boundaries - when rendering for humans.
    All internal operations should remain in UTC.

    Args:
        dt: UTC datetime
        tz_name: IANA timezone name (e.g., "America/Chicago")

    Raises:
        ValueError: If datetime is naive or timezone name is invalid
    """
    if dt.tzinfo is None:
        raise ValueError("Cannot convert naive datetime. Datetime must be timezone-aware.")

    try:
        local_tz = ZoneInfo(tz_name)
    except KeyError:
        raise ValueError(f"Unknown timezone: {tz_name}")

    return dt.astimezone(local_tz)


def parse_iso(iso_string: str) -> datetime:
    """
    Parse ISO 8601 datetime string to UTC datetime.

    Handles both timezone-aware and naive strings.
    Naive strings are assumed to be UTC.
    """
    dt = datetime.fromisoformat(iso_string)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return to_utc(dt)
```

### Key Decisions

- All internal operations use UTC
- `to_local()` is ONLY for display boundaries
- Naive datetimes are rejected with clear error messages
- `parse_iso()` assumes naive strings are UTC (explicit about assumption)

### Tests Required

```python
# tests/test_timezone.py

def test_now_utc_returns_utc():
    result = now_utc()
    assert result.tzinfo == timezone.utc

def test_to_utc_raises_on_naive():
    naive = datetime(2024, 1, 1, 12, 0, 0)
    with pytest.raises(ValueError, match="naive"):
        to_utc(naive)

def test_to_utc_converts_other_timezone():
    chicago = datetime(2024, 1, 1, 12, 0, 0, tzinfo=ZoneInfo("America/Chicago"))
    result = to_utc(chicago)
    assert result.tzinfo == timezone.utc
    assert result.hour == 18  # Chicago is UTC-6 in January

def test_to_local_converts_correctly():
    utc_time = datetime(2024, 1, 1, 18, 0, 0, tzinfo=timezone.utc)
    result = to_local(utc_time, "America/Chicago")
    assert result.hour == 12

def test_to_local_raises_on_invalid_timezone():
    utc_time = now_utc()
    with pytest.raises(ValueError, match="Unknown timezone"):
        to_local(utc_time, "Not/A/Timezone")

def test_parse_iso_handles_utc():
    result = parse_iso("2024-01-01T12:00:00Z")
    assert result.tzinfo == timezone.utc

def test_parse_iso_assumes_naive_is_utc():
    result = parse_iso("2024-01-01T12:00:00")
    assert result.tzinfo == timezone.utc
```

---

## 0.2 utils/user_context.py

**Purpose**: Propagate user identity through the call stack using contextvars.

### Implementation

```python
from contextvars import ContextVar
from uuid import UUID
from contextlib import contextmanager

_current_user_id: ContextVar[UUID | None] = ContextVar('current_user_id', default=None)


def get_current_user_id() -> UUID:
    """
    Get current user ID from context.

    Raises RuntimeError if no user context is set.
    This is fail-fast behavior - if you're in a code path that
    requires user context and it's not set, that's a bug.
    """
    user_id = _current_user_id.get()
    if user_id is None:
        raise RuntimeError(
            "No user context set. This usually means you're calling "
            "user-scoped code outside of an authenticated request."
        )
    return user_id


def set_current_user_id(user_id: UUID) -> None:
    """
    Set current user ID in context.

    Called by auth middleware after validating session.
    """
    _current_user_id.set(user_id)


def clear_current_user_id() -> None:
    """
    Clear user context.

    Called by auth middleware after request completes.
    Must be called in finally block to prevent context leakage.
    """
    _current_user_id.set(None)


@contextmanager
def user_context(user_id: UUID):
    """
    Context manager for temporarily setting user context.

    Useful for:
    - Tests
    - Background jobs that iterate over users
    - Admin operations on behalf of a user

    Example:
        with user_context(some_user_id):
            # All operations here use some_user_id for RLS
            contacts = contact_service.list()
    """
    previous = _current_user_id.get()
    set_current_user_id(user_id)
    try:
        yield
    finally:
        if previous is None:
            clear_current_user_id()
        else:
            set_current_user_id(previous)
```

### Key Decisions

- `get_current_user_id()` raises if not set (fail-fast)
- Clear error message explains what went wrong
- Context manager provided for tests and batch jobs
- Properly restores previous context (for nested usage)

### Tests Required

```python
# tests/test_user_context.py

def test_get_without_set_raises():
    clear_current_user_id()  # Ensure clean state
    with pytest.raises(RuntimeError, match="No user context"):
        get_current_user_id()

def test_set_then_get_returns_uuid():
    user_id = uuid4()
    set_current_user_id(user_id)
    assert get_current_user_id() == user_id
    clear_current_user_id()

def test_clear_then_get_raises():
    set_current_user_id(uuid4())
    clear_current_user_id()
    with pytest.raises(RuntimeError):
        get_current_user_id()

def test_context_manager_sets_and_clears():
    user_id = uuid4()
    with user_context(user_id):
        assert get_current_user_id() == user_id
    with pytest.raises(RuntimeError):
        get_current_user_id()

def test_context_manager_restores_previous():
    outer_id = uuid4()
    inner_id = uuid4()

    with user_context(outer_id):
        assert get_current_user_id() == outer_id
        with user_context(inner_id):
            assert get_current_user_id() == inner_id
        assert get_current_user_id() == outer_id
```

---

## 0.3 auth/types.py

**Purpose**: Pydantic models for auth domain.

### Implementation

```python
from pydantic import BaseModel, Field, EmailStr
from uuid import UUID
from datetime import datetime


class User(BaseModel):
    """A registered user of the system."""
    id: UUID
    email: EmailStr
    created_at: datetime
    last_login_at: datetime | None = None

    class Config:
        from_attributes = True


class Session(BaseModel):
    """An active user session."""
    token: str = Field(..., description="Session token (opaque string)")
    user_id: UUID
    created_at: datetime
    expires_at: datetime
    last_activity_at: datetime


class MagicLinkRequest(BaseModel):
    """Request payload for magic link."""
    email: EmailStr


class MagicLinkToken(BaseModel):
    """A magic link token awaiting verification."""
    token: str = Field(..., description="URL-safe token")
    user_id: UUID
    email: EmailStr
    created_at: datetime
    expires_at: datetime
    used: bool = False


class AuthenticatedUser(BaseModel):
    """User info returned after successful authentication."""
    user: User
    session: Session
```

### Dependencies

- pydantic

---

## 0.4 auth/exceptions.py

**Purpose**: Typed exceptions for auth failures.

### Implementation

```python
class AuthError(Exception):
    """Base class for authentication/authorization errors."""
    pass


class InvalidTokenError(AuthError):
    """
    Token is invalid, expired, or already used.

    Used for both magic link tokens and session tokens.
    """
    pass


class RateLimitedError(AuthError):
    """
    Too many attempts. Client should wait before retrying.
    """
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Rate limited. Retry after {retry_after_seconds} seconds.")


class UserNotFoundError(AuthError):
    """
    Email not associated with any user.

    Note: In user-facing responses, don't reveal whether email exists.
    This exception is for internal logic only.
    """
    pass


class SessionExpiredError(AuthError):
    """Session has expired and user must re-authenticate."""
    pass


class SessionRevokedError(AuthError):
    """Session was explicitly revoked (logout or security action)."""
    pass
```

### Key Decisions

- `RateLimitedError` carries retry timing (for Retry-After header)
- `UserNotFoundError` is internal only - never expose to client
- Separate `SessionExpiredError` and `SessionRevokedError` for different handling

---

## 0.5 auth/config.py

**Purpose**: Auth configuration with sensible defaults.

### Implementation

```python
from pydantic import BaseModel, Field


class AuthConfig(BaseModel):
    """
    Authentication configuration.

    All durations are in their natural units (minutes for short durations,
    hours for longer ones) to make configuration intuitive.
    """

    # Magic link settings
    magic_link_expiry_minutes: int = Field(
        default=15,
        description="How long magic links remain valid",
        ge=5,
        le=60
    )

    # Session settings
    session_expiry_hours: int = Field(
        default=168,  # 7 days
        description="Session lifetime in hours",
        ge=1,
        le=720  # 30 days max
    )
    session_extend_on_activity: bool = Field(
        default=True,
        description="Whether to extend session expiry on activity"
    )
    session_extend_threshold_hours: int = Field(
        default=24,
        description="Extend session if less than this many hours remaining",
        ge=1
    )

    # Rate limiting
    rate_limit_attempts: int = Field(
        default=5,
        description="Max magic link requests per email per window",
        ge=1,
        le=20
    )
    rate_limit_window_minutes: int = Field(
        default=15,
        description="Rate limit window duration",
        ge=5,
        le=60
    )

    # Application
    app_base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL for magic link generation"
    )
    app_name: str = Field(
        default="CRM",
        description="Application name for emails"
    )
```

### Environment Loading

```python
def load_auth_config() -> AuthConfig:
    """
    Load auth config from environment variables.

    Environment variables are prefixed with AUTH_:
    - AUTH_MAGIC_LINK_EXPIRY_MINUTES
    - AUTH_SESSION_EXPIRY_HOURS
    - etc.
    """
    import os

    overrides = {}

    if val := os.getenv("AUTH_MAGIC_LINK_EXPIRY_MINUTES"):
        overrides["magic_link_expiry_minutes"] = int(val)
    if val := os.getenv("AUTH_SESSION_EXPIRY_HOURS"):
        overrides["session_expiry_hours"] = int(val)
    # ... etc

    return AuthConfig(**overrides)
```

---

## 0.6 api/base.py

**Purpose**: Unified API response format and error handling.

### Implementation

```python
from pydantic import BaseModel, Field
from typing import Any, TypeVar, Generic
from datetime import datetime
from uuid import uuid4

from utils.timezone import now_utc


class APIError(BaseModel):
    """Error details in API response."""
    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error message")


class APIMeta(BaseModel):
    """Metadata included in every API response."""
    timestamp: datetime = Field(..., description="Response timestamp (UTC)")
    request_id: str = Field(..., description="Unique request identifier for tracing")


class APIResponse(BaseModel):
    """
    Unified response format for all API endpoints.

    Every endpoint returns this structure, making client parsing predictable.
    """
    success: bool
    data: Any | None = None
    error: APIError | None = None
    meta: APIMeta


def success_response(
    data: Any,
    request_id: str | None = None
) -> APIResponse:
    """
    Create a success response.

    Args:
        data: Response payload (will be serialized to JSON)
        request_id: Optional request ID (generated if not provided)
    """
    return APIResponse(
        success=True,
        data=data,
        error=None,
        meta=APIMeta(
            timestamp=now_utc(),
            request_id=request_id or str(uuid4())
        )
    )


def error_response(
    code: str,
    message: str,
    request_id: str | None = None
) -> APIResponse:
    """
    Create an error response.

    Args:
        code: Machine-readable error code (e.g., "RATE_LIMITED", "NOT_FOUND")
        message: Human-readable error message
        request_id: Optional request ID (generated if not provided)
    """
    return APIResponse(
        success=False,
        data=None,
        error=APIError(code=code, message=message),
        meta=APIMeta(
            timestamp=now_utc(),
            request_id=request_id or str(uuid4())
        )
    )


# Error codes - see docs/ERROR_CODES.md for complete registry
class ErrorCodes:
    """
    Standard error codes for consistent error handling.

    IMPORTANT: See docs/ERROR_CODES.md for the complete list of codes,
    when to use each one, and client handling guidance.

    Add new codes to ERROR_CODES.md first, then add the constant here.
    """

    # Populate from docs/ERROR_CODES.md
    # Example:
    # NOT_FOUND = "NOT_FOUND"
    # VALIDATION_ERROR = "VALIDATION_ERROR"
    # etc.
    pass
```

### FastAPI Exception Handler

```python
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

async def api_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Global exception handler that ensures all errors use APIResponse format.
    """
    request_id = getattr(request.state, "request_id", str(uuid4()))

    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response(
                code=ErrorCodes.INTERNAL_ERROR,
                message=exc.detail,
                request_id=request_id
            ).model_dump(mode="json")
        )

    # Log unexpected errors
    # logger.exception(f"Unhandled exception: {exc}")

    return JSONResponse(
        status_code=500,
        content=error_response(
            code=ErrorCodes.INTERNAL_ERROR,
            message="An unexpected error occurred",
            request_id=request_id
        ).model_dump(mode="json")
    )
```

### Tests Required

```python
# tests/test_api_base.py

def test_success_response_structure():
    resp = success_response({"foo": "bar"})
    assert resp.success is True
    assert resp.data == {"foo": "bar"}
    assert resp.error is None
    assert resp.meta.timestamp is not None
    assert resp.meta.request_id is not None

def test_error_response_structure():
    resp = error_response("TEST_ERROR", "Something went wrong")
    assert resp.success is False
    assert resp.data is None
    assert resp.error.code == "TEST_ERROR"
    assert resp.error.message == "Something went wrong"

def test_request_id_preserved():
    resp = success_response({}, request_id="my-request-id")
    assert resp.meta.request_id == "my-request-id"

def test_timestamp_is_utc():
    resp = success_response({})
    assert resp.meta.timestamp.tzinfo is not None
```

---

## Phase 0 Verification Checklist

Before proceeding to Phase 1:

- [ ] `utils/__init__.py` exists and exports `timezone`, `user_context`
- [ ] `auth/__init__.py` exists and exports `types`, `exceptions`, `config`
- [ ] `api/__init__.py` exists and exports `base`
- [ ] `pytest tests/test_timezone.py` - all tests pass
- [ ] `pytest tests/test_user_context.py` - all tests pass
- [ ] `pytest tests/test_api_base.py` - all tests pass
- [ ] `python -c "from utils.timezone import now_utc"` - imports work
- [ ] `python -c "from utils.user_context import get_current_user_id"` - imports work
- [ ] `python -c "from auth.types import User, Session"` - imports work
- [ ] `python -c "from api.base import success_response, error_response"` - imports work

---

## Next Phase

Proceed to [Phase 1: Infrastructure Clients](./PHASE_1_INFRASTRUCTURE.md)
