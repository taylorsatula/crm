"""Database operations for authentication.

Uses non-RLS tables: users, magic_link_tokens.
These tables are accessed during auth before user context is established.
"""

from uuid import UUID

from clients.postgres_client import PostgresClient
from auth.types import User, MagicLinkToken
from utils.timezone import now_utc


class AuthDatabase:
    """Database operations for authentication."""

    def __init__(self, postgres: PostgresClient):
        self._db = postgres

    def get_user_by_email(self, email: str) -> User | None:
        """Find user by email (case-insensitive)."""
        row = self._db.execute_single(
            """SELECT id, email, is_active, created_at, last_login_at
               FROM users WHERE email = lower(%s)""",
            (email,),
        )
        if row is None:
            return None
        return User(
            id=UUID(row["id"]) if isinstance(row["id"], str) else row["id"],
            email=row["email"],
            is_active=row["is_active"],
            created_at=row["created_at"],
            last_login_at=row["last_login_at"],
        )

    def get_user_by_id(self, user_id: UUID) -> User | None:
        """Find user by ID."""
        row = self._db.execute_single(
            """SELECT id, email, is_active, created_at, last_login_at
               FROM users WHERE id = %s""",
            (str(user_id),),
        )
        if row is None:
            return None
        return User(
            id=UUID(row["id"]) if isinstance(row["id"], str) else row["id"],
            email=row["email"],
            is_active=row["is_active"],
            created_at=row["created_at"],
            last_login_at=row["last_login_at"],
        )

    def create_user(self, email: str) -> User:
        """Create new user with email (lowercased)."""
        rows = self._db.execute_returning(
            """INSERT INTO users (email)
               VALUES (lower(%s))
               RETURNING id, email, is_active, created_at, last_login_at""",
            (email,),
        )
        row = rows[0]
        return User(
            id=UUID(row["id"]) if isinstance(row["id"], str) else row["id"],
            email=row["email"],
            is_active=row["is_active"],
            created_at=row["created_at"],
            last_login_at=row["last_login_at"],
        )

    def get_or_create_user(self, email: str) -> tuple[User, bool]:
        """Get existing or create new user.

        Returns:
            Tuple of (user, was_created)
        """
        existing = self.get_user_by_email(email)
        if existing:
            return existing, False
        return self.create_user(email), True

    def update_last_login(self, user_id: UUID) -> None:
        """Update last_login_at to current time."""
        self._db.execute_returning(
            "UPDATE users SET last_login_at = %s WHERE id = %s RETURNING id",
            (now_utc(), str(user_id)),
        )

    def deactivate_user(self, user_id: UUID) -> bool:
        """Set user as inactive (login frozen).

        Returns:
            True if user was found and deactivated, False if not found.
        """
        rows = self._db.execute_returning(
            "UPDATE users SET is_active = false WHERE id = %s RETURNING id",
            (str(user_id),),
        )
        return len(rows) > 0

    def activate_user(self, user_id: UUID) -> bool:
        """Set user as active (login enabled).

        Returns:
            True if user was found and activated, False if not found.
        """
        rows = self._db.execute_returning(
            "UPDATE users SET is_active = true WHERE id = %s RETURNING id",
            (str(user_id),),
        )
        return len(rows) > 0

    def delete_user(self, user_id: UUID) -> bool:
        """Permanently delete user and all associated data.

        Returns:
            True if user was found and deleted, False if not found.
        """
        rows = self._db.execute_returning(
            "DELETE FROM users WHERE id = %s RETURNING id",
            (str(user_id),),
        )
        return len(rows) > 0

    def store_magic_link_token(self, token: MagicLinkToken) -> None:
        """Store magic link token for verification."""
        self._db.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at, used)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING token""",
            (
                token.token,
                str(token.user_id),
                token.email,
                token.created_at,
                token.expires_at,
                token.used,
            ),
        )

    def get_magic_link_token(self, token: str) -> MagicLinkToken | None:
        """Retrieve magic link token by token string."""
        row = self._db.execute_single(
            """SELECT token, user_id, email, created_at, expires_at, used
               FROM magic_link_tokens
               WHERE token = %s""",
            (token,),
        )
        if row is None:
            return None
        return MagicLinkToken(
            token=row["token"],
            user_id=UUID(row["user_id"]) if isinstance(row["user_id"], str) else row["user_id"],
            email=row["email"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            used=row["used"],
        )

    def mark_token_used(self, token: str) -> None:
        """Mark token as used and set used_at timestamp."""
        self._db.execute_returning(
            """UPDATE magic_link_tokens
               SET used = true, used_at = %s
               WHERE token = %s
               RETURNING token""",
            (now_utc(), token),
        )

    def cleanup_expired_tokens(self) -> int:
        """Delete expired tokens. Returns count deleted."""
        rows = self._db.execute(
            """DELETE FROM magic_link_tokens
               WHERE expires_at < %s
               RETURNING token""",
            (now_utc(),),
        )
        return len(rows)
