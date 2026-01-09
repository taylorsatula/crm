"""Session token lifecycle management.

Sessions are stored in Valkey with TTL matching session expiry.
Token format is cryptographically random (secrets.token_urlsafe).
"""

import secrets
from datetime import timedelta
from uuid import UUID

from clients.valkey_client import ValkeyClient
from auth.config import AuthConfig
from auth.types import Session
from auth.exceptions import SessionExpiredError
from utils.timezone import now_utc, parse_iso


class SessionManager:
    """Session token lifecycle management.

    Sessions are stored in Valkey with TTL matching session expiry.
    Supports automatic session extension on activity.
    """

    KEY_PREFIX = "session:"

    def __init__(self, valkey: ValkeyClient, config: AuthConfig):
        self._valkey = valkey
        self._config = config

    def _key(self, token: str) -> str:
        """Generate Valkey key for session token."""
        return f"{self.KEY_PREFIX}{token}"

    def create_session(self, user_id: UUID) -> Session:
        """Create new session for user.

        Generates cryptographically secure token and stores in Valkey
        with TTL matching session expiry.
        """
        token = secrets.token_urlsafe(32)
        now = now_utc()
        expires_at = now + timedelta(hours=self._config.session_expiry_hours)

        session = Session(
            token=token,
            user_id=user_id,
            created_at=now,
            expires_at=expires_at,
            last_activity_at=now,
        )

        self._valkey.set_json(
            self._key(token),
            {
                "user_id": str(user_id),
                "created_at": session.created_at.isoformat(),
                "expires_at": session.expires_at.isoformat(),
                "last_activity_at": session.last_activity_at.isoformat(),
            },
            expire_seconds=self._config.session_expiry_hours * 3600,
        )

        return session

    def validate_session(self, token: str) -> Session:
        """Validate session token and return session.

        Raises SessionExpiredError if token invalid or expired.
        Extends session if within threshold (if configured).
        """
        data = self._valkey.get_json(self._key(token))

        if data is None:
            raise SessionExpiredError("Session not found or expired")

        session = Session(
            token=token,
            user_id=UUID(data["user_id"]),
            created_at=parse_iso(data["created_at"]),
            expires_at=parse_iso(data["expires_at"]),
            last_activity_at=parse_iso(data["last_activity_at"]),
        )

        now = now_utc()

        # Check expiry (belt and suspenders - Valkey TTL should handle this)
        if now > session.expires_at:
            self._valkey.delete(self._key(token))
            raise SessionExpiredError("Session expired")

        # Always extend session on activity (sliding window)
        session = self._extend_session(session)

        return session

    def _extend_session(self, session: Session) -> Session:
        """Extend session expiry and update last_activity_at."""
        now = now_utc()
        new_expires = now + timedelta(hours=self._config.session_expiry_hours)

        updated = Session(
            token=session.token,
            user_id=session.user_id,
            created_at=session.created_at,
            expires_at=new_expires,
            last_activity_at=now,
        )

        self._valkey.set_json(
            self._key(session.token),
            {
                "user_id": str(updated.user_id),
                "created_at": updated.created_at.isoformat(),
                "expires_at": updated.expires_at.isoformat(),
                "last_activity_at": updated.last_activity_at.isoformat(),
            },
            expire_seconds=self._config.session_expiry_hours * 3600,
        )

        return updated

    def revoke_session(self, token: str) -> None:
        """Revoke session (logout).

        Safe to call with nonexistent token.
        """
        self._valkey.delete(self._key(token))
