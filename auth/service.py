"""Authentication service - orchestrates magic link auth flow."""

import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from auth.config import AuthConfig
from auth.database import AuthDatabase
from auth.session import SessionManager
from auth.rate_limiter import RateLimiter
from auth.security_logger import SecurityLogger, SecurityEvent
from auth.types import AuthenticatedUser, MagicLinkToken, Session
from auth.exceptions import InvalidTokenError, RateLimitedError, UserInactiveError
from clients.email_client import EmailGatewayClient
from clients.valkey_client import ValkeyClient
from utils.timezone import now_utc


@dataclass
class MagicLinkResult:
    """Result of magic link request."""

    sent: bool
    needs_signup: bool


class AuthService:
    """Orchestrates magic link authentication flow.

    Handles:
    - Magic link requests (with enumeration protection)
    - Token verification
    - Session management
    - Logout
    """

    ENUMERATION_KEY_PREFIX = "enumeration:"
    ENUMERATION_LIMIT = 3
    ENUMERATION_WINDOW_SECONDS = 900  # 15 minutes

    def __init__(
        self,
        config: AuthConfig,
        auth_db: AuthDatabase,
        session_manager: SessionManager,
        rate_limiter: RateLimiter,
        email_client: EmailGatewayClient,
        security_logger: SecurityLogger,
    ):
        self._config = config
        self._auth_db = auth_db
        self._session_manager = session_manager
        self._rate_limiter = rate_limiter
        self._email_client = email_client
        self._security_logger = security_logger
        # Access valkey through rate_limiter for enumeration tracking
        self._valkey: ValkeyClient = rate_limiter._valkey

    def _enumeration_key(self, ip_address: str) -> str:
        """Generate Valkey key for IP enumeration tracking."""
        return f"{self.ENUMERATION_KEY_PREFIX}{ip_address}"

    def _check_enumeration_limit(self, ip_address: str) -> None:
        """Check if IP is blocked due to enumeration attempts.

        Raises:
            RateLimitedError: If IP has exceeded enumeration limit.
        """
        key = self._enumeration_key(ip_address)
        count = self._valkey.get(key)

        if count is not None and int(count) >= self.ENUMERATION_LIMIT:
            ttl = self._valkey.ttl(key)
            raise RateLimitedError(retry_after_seconds=max(ttl, 1))

    def _increment_enumeration_counter(self, ip_address: str) -> None:
        """Increment enumeration counter for IP."""
        key = self._enumeration_key(ip_address)
        count = self._valkey.incr(key)

        if count == 1:
            # First attempt, set expiry
            self._valkey.expire(key, self.ENUMERATION_WINDOW_SECONDS)

    def _reset_enumeration_counter(self, ip_address: str) -> None:
        """Reset enumeration counter for IP (after successful login)."""
        self._valkey.delete(self._enumeration_key(ip_address))

    def request_magic_link(
        self,
        email: str,
        ip_address: str,
        user_agent: str,
    ) -> MagicLinkResult:
        """Request magic link for email.

        Flow:
        1. Check IP enumeration limit
        2. Look up user by email
        3. If user doesn't exist: increment enumeration counter, return needs_signup
        4. Check per-email rate limit
        5. Generate and store token
        6. Send email
        7. Log security event

        Returns:
            MagicLinkResult with sent=True if email sent, needs_signup=True if user doesn't exist.

        Raises:
            RateLimitedError: If rate limit or enumeration limit exceeded.
            EmailGatewayError: If email send fails.
        """
        email = email.lower().strip()

        # Check IP enumeration limit first
        self._check_enumeration_limit(ip_address)

        # Look up user
        user = self._auth_db.get_user_by_email(email)

        if user is None:
            # User doesn't exist - increment enumeration counter
            self._increment_enumeration_counter(ip_address)

            self._security_logger.log(
                SecurityEvent.MAGIC_LINK_FAILED,
                email=email,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"reason": "user_not_found"},
            )

            return MagicLinkResult(sent=False, needs_signup=True)

        # User exists - check per-email rate limit
        self._rate_limiter.check_rate_limit(email)

        # Generate token
        now = now_utc()
        token_value = secrets.token_urlsafe(32)
        token = MagicLinkToken(
            token=token_value,
            user_id=user.id,
            email=user.email,
            created_at=now,
            expires_at=now + timedelta(minutes=self._config.magic_link_expiry_minutes),
            used=False,
        )

        # Store token
        self._auth_db.store_magic_link_token(token)

        # Log request event
        self._security_logger.log(
            SecurityEvent.MAGIC_LINK_REQUESTED,
            email=user.email,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Send email (may raise EmailGatewayError)
        self._email_client.send_magic_link(
            email=user.email,
            token=token_value,
            app_url=self._config.app_base_url,
        )

        self._security_logger.log(
            SecurityEvent.MAGIC_LINK_SENT,
            email=user.email,
            user_id=user.id,
            ip_address=ip_address,
        )

        return MagicLinkResult(sent=True, needs_signup=False)

    def verify_magic_link(
        self,
        token: str,
        ip_address: str,
        user_agent: str,
    ) -> AuthenticatedUser:
        """Verify magic link token and create session.

        Flow:
        1. Lookup token
        2. Validate not used/expired
        3. Check user is active
        4. Mark token used
        5. Create session
        6. Update last_login
        7. Reset rate limits (per-email and enumeration)
        8. Log security event

        Raises:
            InvalidTokenError: If token invalid, expired, or already used.
            UserInactiveError: If user account is deactivated.
        """
        # Lookup token
        magic_token = self._auth_db.get_magic_link_token(token)

        if magic_token is None:
            self._security_logger.log(
                SecurityEvent.MAGIC_LINK_FAILED,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"reason": "token_not_found"},
            )
            raise InvalidTokenError("Invalid or expired token")

        # Check if already used
        if magic_token.used:
            self._security_logger.log(
                SecurityEvent.MAGIC_LINK_ALREADY_USED,
                email=magic_token.email,
                user_id=magic_token.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise InvalidTokenError("Token has already been used")

        # Check expiry
        now = now_utc()
        if now > magic_token.expires_at:
            self._security_logger.log(
                SecurityEvent.MAGIC_LINK_EXPIRED,
                email=magic_token.email,
                user_id=magic_token.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise InvalidTokenError("Token has expired")

        # Get user and check active
        user = self._auth_db.get_user_by_id(magic_token.user_id)
        if user is None:
            raise InvalidTokenError("User not found")

        if not user.is_active:
            self._security_logger.log(
                SecurityEvent.MAGIC_LINK_FAILED,
                email=user.email,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"reason": "user_inactive"},
            )
            raise UserInactiveError("User account is deactivated")

        # Mark token used
        self._auth_db.mark_token_used(token)

        # Create session
        session = self._session_manager.create_session(user.id)

        # Update last login
        self._auth_db.update_last_login(user.id)

        # Reset rate limits
        self._rate_limiter.reset_rate_limit(user.email)
        self._reset_enumeration_counter(ip_address)

        # Log success
        self._security_logger.log(
            SecurityEvent.MAGIC_LINK_VERIFIED,
            email=user.email,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        self._security_logger.log(
            SecurityEvent.SESSION_CREATED,
            email=user.email,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Refresh user to get updated last_login_at
        user = self._auth_db.get_user_by_id(user.id)

        return AuthenticatedUser(user=user, session=session)

    def logout(self, session_token: str, ip_address: str) -> None:
        """Revoke session (logout).

        Safe to call with invalid token.
        """
        # Try to get session info for logging before revocation
        try:
            session = self._session_manager.validate_session(session_token)
            user = self._auth_db.get_user_by_id(session.user_id)
            email = user.email if user else None
            user_id = session.user_id
        except Exception:
            email = None
            user_id = None

        # Revoke session
        self._session_manager.revoke_session(session_token)

        # Log event
        self._security_logger.log(
            SecurityEvent.SESSION_REVOKED,
            email=email,
            user_id=user_id,
            ip_address=ip_address,
        )

    def validate_session(self, token: str) -> Session:
        """Validate session token.

        Raises:
            SessionExpiredError: If session invalid or expired.
        """
        return self._session_manager.validate_session(token)
