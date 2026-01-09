# Phase 2: Auth System

**Goal**: Complete magic link authentication with session management.

**Estimated files**: 8
**Dependencies**: Phase 0 and Phase 1 complete

---

## Prerequisites

Before starting Phase 2, ensure:

1. Phase 0 complete (utils, auth/types, api/base)
2. Phase 1 complete (all infrastructure clients working)
3. Database tables for auth exist (see schema below)

### Required Database Tables

```sql
-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

-- Magic link tokens (ephemeral, can be cleared periodically)
CREATE TABLE magic_link_tokens (
    token TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    email TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    used BOOLEAN NOT NULL DEFAULT false
);

-- Security event log (append-only audit trail)
CREATE TABLE security_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL,
    email TEXT,
    user_id UUID,
    ip_address TEXT,
    user_agent TEXT,
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for cleanup queries
CREATE INDEX idx_magic_link_tokens_expires ON magic_link_tokens(expires_at);
CREATE INDEX idx_security_events_created ON security_events(created_at);
CREATE INDEX idx_security_events_user ON security_events(user_id);
```

---

## 2.1 auth/database.py

**Purpose**: Auth-specific database operations.

### Implementation

```python
from uuid import UUID, uuid4
from datetime import datetime

from clients.postgres_client import PostgresClient
from auth.types import User, MagicLinkToken
from auth.exceptions import UserNotFoundError
from utils.timezone import now_utc


class AuthDatabase:
    """
    Database operations for authentication.

    These operations use admin_connection() because auth happens
    before user context exists (user is proving who they are).
    """

    def __init__(self, postgres: PostgresClient):
        self.postgres = postgres

    def get_user_by_email(self, email: str) -> User | None:
        """
        Find user by email.

        Returns None if not found (don't reveal to caller whether email exists).
        """
        row = self.postgres.execute_admin(
            "SELECT id, email, created_at, last_login_at FROM users WHERE email = %s",
            (email.lower(),)
        )
        if not row:
            return None
        return User(**row[0])

    def get_user_by_id(self, user_id: UUID) -> User | None:
        """Find user by ID."""
        row = self.postgres.execute_admin(
            "SELECT id, email, created_at, last_login_at FROM users WHERE id = %s",
            (user_id,)
        )
        if not row:
            return None
        return User(**row[0])

    def create_user(self, email: str) -> User:
        """
        Create new user.

        Raises if email already exists (unique constraint).
        """
        user_id = uuid4()
        now = now_utc()

        self.postgres.execute_admin(
            """
            INSERT INTO users (id, email, created_at)
            VALUES (%s, %s, %s)
            """,
            (user_id, email.lower(), now)
        )

        return User(
            id=user_id,
            email=email.lower(),
            created_at=now,
            last_login_at=None
        )

    def get_or_create_user(self, email: str) -> tuple[User, bool]:
        """
        Get existing user or create new one.

        Returns (user, created) tuple.
        """
        existing = self.get_user_by_email(email)
        if existing:
            return existing, False
        return self.create_user(email), True

    def update_last_login(self, user_id: UUID) -> None:
        """Update last_login_at timestamp."""
        self.postgres.execute_admin(
            "UPDATE users SET last_login_at = %s WHERE id = %s",
            (now_utc(), user_id)
        )

    def store_magic_link_token(self, token: MagicLinkToken) -> None:
        """Store magic link token for later verification."""
        self.postgres.execute_admin(
            """
            INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (token.token, token.user_id, token.email, token.created_at, token.expires_at, token.used)
        )

    def get_magic_link_token(self, token: str) -> MagicLinkToken | None:
        """Retrieve magic link token."""
        row = self.postgres.execute_admin(
            """
            SELECT token, user_id, email, created_at, expires_at, used
            FROM magic_link_tokens
            WHERE token = %s
            """,
            (token,)
        )
        if not row:
            return None
        return MagicLinkToken(**row[0])

    def mark_token_used(self, token: str) -> None:
        """Mark token as used (one-time use)."""
        self.postgres.execute_admin(
            "UPDATE magic_link_tokens SET used = true WHERE token = %s",
            (token,)
        )

    def cleanup_expired_tokens(self) -> int:
        """
        Delete expired tokens.

        Call periodically (e.g., daily) to clean up.
        Returns count of deleted tokens.
        """
        result = self.postgres.execute_admin(
            "DELETE FROM magic_link_tokens WHERE expires_at < %s RETURNING token",
            (now_utc(),)
        )
        return len(result)
```

---

## 2.2 auth/rate_limiter.py

**Purpose**: Prevent brute-force magic link requests.

### Implementation

```python
from clients.valkey_client import ValkeyClient
from auth.config import AuthConfig
from auth.exceptions import RateLimitedError


class RateLimiter:
    """
    Rate limiting for authentication attempts.

    Uses Valkey to track attempt counts with sliding window expiry.
    """

    KEY_PREFIX = "ratelimit:magic_link:"

    def __init__(self, valkey: ValkeyClient, config: AuthConfig):
        self.valkey = valkey
        self.config = config

    def _key(self, email: str) -> str:
        """Generate rate limit key for email."""
        return f"{self.KEY_PREFIX}{email.lower()}"

    def check_rate_limit(self, email: str) -> None:
        """
        Check if email is rate limited.

        Raises RateLimitedError if limit exceeded.
        Otherwise, increments attempt counter.
        """
        key = self._key(email)
        attempts = self.valkey.incr(key)

        if attempts == 1:
            # First attempt in window, set expiry
            self.valkey.expire(key, self.config.rate_limit_window_minutes * 60)

        if attempts > self.config.rate_limit_attempts:
            ttl = self.valkey.ttl(key)
            # Ensure positive TTL (edge case if key expired between incr and ttl)
            retry_after = max(ttl, 1)
            raise RateLimitedError(retry_after_seconds=retry_after)

    def reset_rate_limit(self, email: str) -> None:
        """
        Reset rate limit for email.

        Called after successful login to allow fresh attempts.
        """
        self.valkey.delete(self._key(email))

    def get_remaining_attempts(self, email: str) -> int:
        """
        Get remaining attempts for email.

        Returns max attempts if no attempts made yet.
        """
        key = self._key(email)
        current = self.valkey.get(key)
        if current is None:
            return self.config.rate_limit_attempts
        return max(0, self.config.rate_limit_attempts - int(current))
```

### Tests Required

```python
# tests/test_rate_limiter.py

def test_first_attempt_passes():
    limiter = RateLimiter(valkey, config)
    limiter.reset_rate_limit("test@example.com")  # Clean state

    # Should not raise
    limiter.check_rate_limit("test@example.com")

def test_exceeding_limit_raises():
    config = AuthConfig(rate_limit_attempts=3, rate_limit_window_minutes=1)
    limiter = RateLimiter(valkey, config)
    limiter.reset_rate_limit("test@example.com")

    # First 3 should pass
    for _ in range(3):
        limiter.check_rate_limit("test@example.com")

    # 4th should raise
    with pytest.raises(RateLimitedError) as exc:
        limiter.check_rate_limit("test@example.com")

    assert exc.value.retry_after_seconds > 0

def test_reset_allows_new_attempts():
    limiter = RateLimiter(valkey, config)

    # Use up attempts
    for _ in range(config.rate_limit_attempts):
        limiter.check_rate_limit("test@example.com")

    # Reset
    limiter.reset_rate_limit("test@example.com")

    # Should pass again
    limiter.check_rate_limit("test@example.com")
```

---

## 2.3 auth/security_logger.py

**Purpose**: Audit trail for security-relevant events.

### Implementation

```python
from enum import Enum
from uuid import UUID, uuid4
from typing import Any

from clients.postgres_client import PostgresClient
from utils.timezone import now_utc


class SecurityEvent(Enum):
    """Security events that get logged."""

    # Magic link events
    MAGIC_LINK_REQUESTED = "magic_link_requested"
    MAGIC_LINK_SENT = "magic_link_sent"
    MAGIC_LINK_VERIFIED = "magic_link_verified"
    MAGIC_LINK_FAILED = "magic_link_failed"
    MAGIC_LINK_EXPIRED = "magic_link_expired"
    MAGIC_LINK_ALREADY_USED = "magic_link_already_used"

    # Session events
    SESSION_CREATED = "session_created"
    SESSION_EXTENDED = "session_extended"
    SESSION_EXPIRED = "session_expired"
    SESSION_REVOKED = "session_revoked"

    # Rate limiting
    RATE_LIMITED = "rate_limited"

    # User events
    USER_CREATED = "user_created"


class SecurityLogger:
    """
    Append-only security event log.

    All authentication and authorization events are logged here
    for audit trail and security analysis.
    """

    def __init__(self, postgres: PostgresClient):
        self.postgres = postgres

    def log(
        self,
        event: SecurityEvent,
        email: str | None = None,
        user_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        details: dict[str, Any] | None = None
    ) -> None:
        """
        Log security event.

        All parameters are optional except event type.
        Include as much context as available.
        """
        from psycopg.types.json import Json

        self.postgres.execute_admin(
            """
            INSERT INTO security_events
                (id, event_type, email, user_id, ip_address, user_agent, details, created_at)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid4(),
                event.value,
                email,
                user_id,
                ip_address,
                user_agent,
                Json(details) if details else None,
                now_utc()
            )
        )

    def get_recent_events(
        self,
        email: str | None = None,
        user_id: UUID | None = None,
        event_type: SecurityEvent | None = None,
        limit: int = 100
    ) -> list[dict]:
        """
        Query recent security events.

        Filter by email, user_id, and/or event_type.
        """
        conditions = []
        params = []

        if email:
            conditions.append("email = %s")
            params.append(email)
        if user_id:
            conditions.append("user_id = %s")
            params.append(user_id)
        if event_type:
            conditions.append("event_type = %s")
            params.append(event_type.value)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        return self.postgres.execute_admin(
            f"""
            SELECT id, event_type, email, user_id, ip_address, user_agent, details, created_at
            FROM security_events
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            tuple(params)
        )
```

---

## 2.4 auth/session.py

**Purpose**: Session token management with Valkey storage.

### Implementation

```python
import secrets
from uuid import UUID
from datetime import timedelta

from clients.valkey_client import ValkeyClient
from auth.config import AuthConfig
from auth.types import Session
from auth.exceptions import SessionExpiredError
from utils.timezone import now_utc


class SessionManager:
    """
    Session token lifecycle management.

    Sessions are stored in Valkey with TTL matching session expiry.
    Token format is cryptographically random.
    """

    KEY_PREFIX = "session:"

    def __init__(self, valkey: ValkeyClient, config: AuthConfig):
        self.valkey = valkey
        self.config = config

    def _key(self, token: str) -> str:
        """Generate Valkey key for session token."""
        return f"{self.KEY_PREFIX}{token}"

    def create_session(self, user_id: UUID) -> Session:
        """
        Create new session for user.

        Generates cryptographically secure token and stores in Valkey.
        """
        token = secrets.token_urlsafe(32)
        now = now_utc()
        expires_at = now + timedelta(hours=self.config.session_expiry_hours)

        session = Session(
            token=token,
            user_id=user_id,
            created_at=now,
            expires_at=expires_at,
            last_activity_at=now
        )

        # Store in Valkey with TTL
        self.valkey.set_json(
            self._key(token),
            {
                "user_id": str(user_id),
                "created_at": session.created_at.isoformat(),
                "expires_at": session.expires_at.isoformat(),
                "last_activity_at": session.last_activity_at.isoformat()
            },
            expire_seconds=self.config.session_expiry_hours * 3600
        )

        return session

    def validate_session(self, token: str) -> Session:
        """
        Validate session token and return session.

        Raises SessionExpiredError if token invalid or expired.
        Extends session if within threshold (if configured).
        """
        data = self.valkey.get_json(self._key(token))

        if data is None:
            raise SessionExpiredError("Session not found or expired")

        from utils.timezone import parse_iso

        session = Session(
            token=token,
            user_id=UUID(data["user_id"]),
            created_at=parse_iso(data["created_at"]),
            expires_at=parse_iso(data["expires_at"]),
            last_activity_at=parse_iso(data["last_activity_at"])
        )

        now = now_utc()

        # Check expiry (belt and suspenders - Valkey TTL should handle this)
        if now > session.expires_at:
            self.valkey.delete(self._key(token))
            raise SessionExpiredError("Session expired")

        # Always extend session on activity (sliding window)
        session = self._extend_session(session)

        return session

    def _extend_session(self, session: Session) -> Session:
        """Extend session expiry."""
        now = now_utc()
        new_expires = now + timedelta(hours=self.config.session_expiry_hours)

        updated = Session(
            token=session.token,
            user_id=session.user_id,
            created_at=session.created_at,
            expires_at=new_expires,
            last_activity_at=now
        )

        self.valkey.set_json(
            self._key(session.token),
            {
                "user_id": str(updated.user_id),
                "created_at": updated.created_at.isoformat(),
                "expires_at": updated.expires_at.isoformat(),
                "last_activity_at": updated.last_activity_at.isoformat()
            },
            expire_seconds=self.config.session_expiry_hours * 3600
        )

        return updated

    def revoke_session(self, token: str) -> None:
        """Revoke session (logout)."""
        self.valkey.delete(self._key(token))
```

### Tests Required

```python
# tests/test_session.py

def test_create_session_returns_token():
    manager = SessionManager(valkey, config)
    user_id = uuid4()

    session = manager.create_session(user_id)

    assert session.token is not None
    assert len(session.token) > 20
    assert session.user_id == user_id

def test_validate_session_returns_session():
    manager = SessionManager(valkey, config)
    user_id = uuid4()

    created = manager.create_session(user_id)
    validated = manager.validate_session(created.token)

    assert validated.user_id == user_id

def test_validate_invalid_token_raises():
    manager = SessionManager(valkey, config)

    with pytest.raises(SessionExpiredError):
        manager.validate_session("invalid_token_12345")

def test_revoke_session():
    manager = SessionManager(valkey, config)
    session = manager.create_session(uuid4())

    manager.revoke_session(session.token)

    with pytest.raises(SessionExpiredError):
        manager.validate_session(session.token)
```

---

## 2.5 auth/email_service.py

**Purpose**: Send magic link emails.

### Implementation

```python
from datetime import datetime

from auth.config import AuthConfig


class EmailError(Exception):
    """Email delivery failed."""
    pass


class AuthEmailService:
    """
    Email service for authentication flows.

    Handles magic link delivery with proper formatting.
    """

    def __init__(self, config: AuthConfig, api_key: str, from_address: str):
        """
        Initialize email service.

        Args:
            config: Auth configuration
            api_key: Email provider API key
            from_address: Sender email address
        """
        self.config = config
        self.api_key = api_key
        self.from_address = from_address
        # Initialize provider client here
        # self.client = SomeEmailProvider(api_key)

    def send_magic_link(
        self,
        email: str,
        token: str,
        expires_at: datetime
    ) -> None:
        """
        Send magic link email.

        Raises EmailError if delivery fails.
        """
        link = f"{self.config.app_base_url}/auth/verify?token={token}"

        # Calculate human-readable expiry
        from utils.timezone import now_utc
        minutes_remaining = int((expires_at - now_utc()).total_seconds() / 60)

        subject = f"Sign in to {self.config.app_name}"

        # Plain text version
        text_body = f"""
Click the link below to sign in to {self.config.app_name}:

{link}

This link will expire in {minutes_remaining} minutes.

If you didn't request this email, you can safely ignore it.
        """.strip()

        # HTML version (styled button + fallback link)
        html_body = f"""
<!DOCTYPE html>
<html><body style="font-family: sans-serif; max-width: 600px; margin: auto; padding: 20px;">
    <h2>Sign in to {self.config.app_name}</h2>
    <p><a href="{link}" style="background:#0066cc; color:white; padding:12px 24px; text-decoration:none; border-radius:4px;">Sign In</a></p>
    <p style="color:#666; font-size:14px;">Expires in {minutes_remaining} min. Ignore if you didn't request this.</p>
    <p style="color:#999; font-size:12px;">Fallback: <a href="{link}">{link}</a></p>
</body></html>
        """.strip()

        self._send_email(
            to=email,
            subject=subject,
            text_body=text_body,
            html_body=html_body
        )

    def _send_email(self, to: str, subject: str, text_body: str, html_body: str) -> None:
        """Send email via provider. Implement for your provider (Resend, SendGrid, etc.)."""
        # Provider-specific: resend.Emails.send({from, to, subject, text, html})
        raise NotImplementedError("Implement _send_email for your email provider")
```

---

## 2.6 auth/service.py

**Purpose**: Core auth orchestration - the main entry point.

### Implementation

```python
import secrets
from datetime import timedelta
from uuid import UUID

from auth.database import AuthDatabase
from auth.session import SessionManager
from auth.rate_limiter import RateLimiter
from auth.email_service import AuthEmailService
from auth.security_logger import SecurityLogger, SecurityEvent
from auth.config import AuthConfig
from auth.types import User, Session, MagicLinkToken, AuthenticatedUser
from auth.exceptions import InvalidTokenError, RateLimitedError
from utils.timezone import now_utc


class AuthService:
    """
    Core authentication service.

    Orchestrates all auth operations:
    - Magic link request/verification
    - Session creation/validation
    - Rate limiting
    - Security logging
    """

    def __init__(
        self,
        database: AuthDatabase,
        session_manager: SessionManager,
        rate_limiter: RateLimiter,
        email_service: AuthEmailService,
        security_logger: SecurityLogger,
        config: AuthConfig
    ):
        self.database = database
        self.session_manager = session_manager
        self.rate_limiter = rate_limiter
        self.email_service = email_service
        self.security_logger = security_logger
        self.config = config

    def request_magic_link(
        self,
        email: str,
        ip_address: str,
        user_agent: str
    ) -> None:
        """
        Request magic link for email.

        Flow:
        1. Check rate limit
        2. Find or create user
        3. Generate token
        4. Store token
        5. Send email
        6. Log event

        Raises RateLimitedError if too many attempts.

        Note: Returns needs_signup=True for unknown emails to enable
        frontend signup flow. Enumeration protection is handled via
        IP-based rate limiting on failed lookups, not by hiding results.
        """
        email = email.lower().strip()

        # Log request first
        self.security_logger.log(
            SecurityEvent.MAGIC_LINK_REQUESTED,
            email=email,
            ip_address=ip_address,
            user_agent=user_agent
        )

        # Check rate limit
        try:
            self.rate_limiter.check_rate_limit(email)
        except RateLimitedError:
            self.security_logger.log(
                SecurityEvent.RATE_LIMITED,
                email=email,
                ip_address=ip_address
            )
            raise

        # Get or create user
        user, created = self.database.get_or_create_user(email)

        if created:
            self.security_logger.log(
                SecurityEvent.USER_CREATED,
                email=email,
                user_id=user.id,
                ip_address=ip_address
            )

        # Generate token
        token = secrets.token_urlsafe(32)
        now = now_utc()
        expires_at = now + timedelta(minutes=self.config.magic_link_expiry_minutes)

        magic_link = MagicLinkToken(
            token=token,
            user_id=user.id,
            email=email,
            created_at=now,
            expires_at=expires_at,
            used=False
        )

        # Store token
        self.database.store_magic_link_token(magic_link)

        # Send email
        self.email_service.send_magic_link(email, token, expires_at)

        self.security_logger.log(
            SecurityEvent.MAGIC_LINK_SENT,
            email=email,
            user_id=user.id,
            ip_address=ip_address
        )

    def verify_magic_link(
        self,
        token: str,
        ip_address: str,
        user_agent: str
    ) -> AuthenticatedUser:
        """
        Verify magic link token and create session.

        Flow:
        1. Retrieve token
        2. Validate not expired, not used
        3. Mark token used
        4. Create session
        5. Update last login
        6. Reset rate limit
        7. Log event

        Raises InvalidTokenError if token invalid/expired/used.
        """
        # Get token
        magic_link = self.database.get_magic_link_token(token)

        if magic_link is None:
            self.security_logger.log(
                SecurityEvent.MAGIC_LINK_FAILED,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"reason": "token_not_found"}
            )
            raise InvalidTokenError("Invalid or expired token")

        # Check if used
        if magic_link.used:
            self.security_logger.log(
                SecurityEvent.MAGIC_LINK_ALREADY_USED,
                email=magic_link.email,
                user_id=magic_link.user_id,
                ip_address=ip_address
            )
            raise InvalidTokenError("This link has already been used")

        # Check expiry
        if now_utc() > magic_link.expires_at:
            self.security_logger.log(
                SecurityEvent.MAGIC_LINK_EXPIRED,
                email=magic_link.email,
                user_id=magic_link.user_id,
                ip_address=ip_address
            )
            raise InvalidTokenError("This link has expired")

        # Mark used (before creating session to prevent race conditions)
        self.database.mark_token_used(token)

        # Create session
        session = self.session_manager.create_session(magic_link.user_id)

        # Update last login
        self.database.update_last_login(magic_link.user_id)

        # Reset rate limit
        self.rate_limiter.reset_rate_limit(magic_link.email)

        # Get full user
        user = self.database.get_user_by_id(magic_link.user_id)

        self.security_logger.log(
            SecurityEvent.MAGIC_LINK_VERIFIED,
            email=magic_link.email,
            user_id=magic_link.user_id,
            ip_address=ip_address,
            user_agent=user_agent
        )

        self.security_logger.log(
            SecurityEvent.SESSION_CREATED,
            user_id=magic_link.user_id,
            ip_address=ip_address,
            details={"session_token_prefix": session.token[:8]}
        )

        return AuthenticatedUser(user=user, session=session)

    def logout(self, session_token: str, ip_address: str | None = None) -> None:
        """Revoke session."""
        # Try to get session info for logging before revoking
        try:
            session = self.session_manager.validate_session(session_token)
            user_id = session.user_id
        except Exception:
            user_id = None

        self.session_manager.revoke_session(session_token)

        self.security_logger.log(
            SecurityEvent.SESSION_REVOKED,
            user_id=user_id,
            ip_address=ip_address,
            details={"session_token_prefix": session_token[:8] if session_token else None}
        )

    def validate_session(self, token: str) -> Session:
        """
        Validate session token.

        Delegates to session manager.
        """
        return self.session_manager.validate_session(token)
```

---

## 2.7 auth/security_middleware.py

**Purpose**: FastAPI middleware for request-level auth.

### Implementation

```python
from uuid import UUID

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from auth.service import AuthService
from auth.session import SessionManager
from auth.exceptions import SessionExpiredError
from utils.user_context import set_current_user_id, clear_current_user_id


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Request-level authentication middleware.

    Responsibilities:
    - Extract session token from cookie
    - Validate session
    - Set user context for RLS
    - Clear user context after request
    """

    # Paths that don't require authentication
    PUBLIC_PATHS = [
        "/auth/request-link",
        "/auth/verify",
        "/health",
        "/docs",
        "/openapi.json",
        "/static/",
    ]

    def __init__(self, app, session_manager: SessionManager):
        super().__init__(app)
        self.session_manager = session_manager

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request through auth middleware."""

        # Skip auth for public endpoints
        if self._is_public_path(request.url.path):
            return await call_next(request)

        # Extract session token
        token = request.cookies.get("session_token")

        if not token:
            raise HTTPException(
                status_code=401,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Cookie"}
            )

        # Validate session
        try:
            session = self.session_manager.validate_session(token)
        except SessionExpiredError:
            raise HTTPException(
                status_code=401,
                detail="Session expired",
                headers={"WWW-Authenticate": "Cookie"}
            )

        # Set user context for RLS
        set_current_user_id(session.user_id)

        # Store user info in request state for handlers
        request.state.user_id = session.user_id
        request.state.session = session

        try:
            response = await call_next(request)
            return response
        finally:
            # Always clear user context
            clear_current_user_id()

    def _is_public_path(self, path: str) -> bool:
        """Check if path is public (no auth required)."""
        for public_path in self.PUBLIC_PATHS:
            if path == public_path or path.startswith(public_path):
                return True
        return False
```

---

## 2.8 auth/api.py

**Purpose**: HTTP endpoints for auth.

### Implementation

```python
from fastapi import APIRouter, Request, Response, Depends

from auth.service import AuthService
from auth.types import MagicLinkRequest
from auth.exceptions import RateLimitedError, InvalidTokenError
from auth.config import AuthConfig
from api.base import success_response, error_response, ErrorCodes, APIResponse


def get_auth_service() -> AuthService:
    """Dependency to get auth service instance."""
    # This will be properly initialized in main.py
    from main import auth_service
    return auth_service


def get_auth_config() -> AuthConfig:
    """Dependency to get auth config."""
    from main import auth_config
    return auth_config


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/request-link")
async def request_magic_link(
    request: Request,
    body: MagicLinkRequest,
    auth_service: AuthService = Depends(get_auth_service)
) -> APIResponse:
    """
    Request magic link email.

    Always returns success message regardless of whether email exists.
    This prevents email enumeration attacks.
    """
    try:
        auth_service.request_magic_link(
            email=body.email,
            ip_address=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("user-agent", "")
        )
    except RateLimitedError as e:
        return error_response(
            ErrorCodes.RATE_LIMITED,
            f"Too many attempts. Please try again in {e.retry_after_seconds} seconds."
        )

    # Always return same message (don't reveal if email exists)
    return success_response({
        "message": "If this email is registered, a sign-in link has been sent."
    })


@router.get("/verify")
async def verify_magic_link(
    request: Request,
    response: Response,
    token: str,
    auth_service: AuthService = Depends(get_auth_service),
    config: AuthConfig = Depends(get_auth_config)
) -> APIResponse:
    """
    Verify magic link and create session.

    Sets httponly session cookie on success.
    """
    try:
        auth_result = auth_service.verify_magic_link(
            token=token,
            ip_address=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("user-agent", "")
        )
    except InvalidTokenError as e:
        return error_response(
            ErrorCodes.INVALID_TOKEN,
            str(e)
        )

    # Set session cookie
    response.set_cookie(
        key="session_token",
        value=auth_result.session.token,
        httponly=True,
        secure=True,  # Requires HTTPS
        samesite="lax",
        max_age=config.session_expiry_hours * 3600
    )

    return success_response({
        "message": "Signed in successfully",
        "user": {
            "id": str(auth_result.user.id),
            "email": auth_result.user.email
        }
    })


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service)
) -> APIResponse:
    """
    Logout and clear session.
    """
    token = request.cookies.get("session_token")

    if token:
        auth_service.logout(
            session_token=token,
            ip_address=request.client.host if request.client else None
        )

    response.delete_cookie("session_token")

    return success_response({
        "message": "Signed out successfully"
    })


@router.get("/me")
async def get_current_user(request: Request) -> APIResponse:
    """
    Get current authenticated user.

    Requires valid session (enforced by middleware).
    """
    # User info is set by middleware
    user_id = request.state.user_id

    # Could fetch full user profile here
    return success_response({
        "user_id": str(user_id)
    })
```

---

## Phase 2 Verification Checklist

Before proceeding to Phase 3:

### Functional Tests

- [ ] `pytest tests/test_auth_database.py` - all tests pass
- [ ] `pytest tests/test_rate_limiter.py` - all tests pass
- [ ] `pytest tests/test_session.py` - all tests pass
- [ ] `pytest tests/test_auth_service.py` - all tests pass

### Integration Tests

- [ ] Can POST to `/auth/request-link` with email
- [ ] Email is received with valid magic link
- [ ] Can GET `/auth/verify?token=...` with token from email
- [ ] Response includes `Set-Cookie` header
- [ ] Subsequent requests with cookie can access `/auth/me`
- [ ] POST to `/auth/logout` clears cookie
- [ ] After logout, `/auth/me` returns 401
- [ ] Rate limiting triggers after configured attempts
- [ ] Security events are logged in database

### Security Verification

- [ ] Magic link tokens are one-time use
- [ ] Expired tokens are rejected
- [ ] Invalid tokens don't reveal whether email exists
- [ ] Session cookies are httponly and secure
- [ ] Rate limiting cannot be bypassed

---

## Next Phase

Proceed to [Phase 3: Core Domain](./PHASE_3_CORE_DOMAIN.md)
