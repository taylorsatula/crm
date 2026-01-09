"""Tests for AuthDatabase - user and magic link token operations."""

from datetime import timedelta
from uuid import UUID

import pytest

from auth.database import AuthDatabase
from auth.types import MagicLinkToken, User
from utils.timezone import now_utc


@pytest.fixture
def auth_db(db):
    """AuthDatabase instance."""
    return AuthDatabase(db)


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


@pytest.fixture
def cleanup_token(db_admin):
    """Track tokens created during tests for cleanup."""
    created_tokens = []

    def _track(token):
        created_tokens.append(token)

    yield _track

    # Cleanup
    for token in created_tokens:
        db_admin.execute("DELETE FROM magic_link_tokens WHERE token = %s", (token,))


class TestGetUserByEmail:
    """Test user lookup by email."""

    def test_returns_user_when_exists(self, db_admin, auth_db, cleanup_user):
        """Returns User when email exists."""
        cleanup_user("test@example.com")
        db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("test@example.com",),
        )

        user = auth_db.get_user_by_email("test@example.com")

        assert user is not None
        assert isinstance(user, User)
        assert user.email == "test@example.com"

    def test_returns_none_when_not_found(self, auth_db):
        """Returns None when email doesn't exist."""
        user = auth_db.get_user_by_email("nonexistent@example.com")
        assert user is None

    def test_case_insensitive_lookup(self, db_admin, auth_db, cleanup_user):
        """Email lookup is case-insensitive."""
        cleanup_user("user@example.com")
        db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("user@example.com",),
        )

        user = auth_db.get_user_by_email("USER@EXAMPLE.COM")

        assert user is not None
        assert user.email == "user@example.com"


class TestGetUserById:
    """Test user lookup by ID."""

    def test_returns_user_when_exists(self, db_admin, auth_db, cleanup_user):
        """Returns User when ID exists."""
        cleanup_user("byid@example.com")
        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("byid@example.com",),
        )
        user_id = result[0]["id"]
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        user = auth_db.get_user_by_id(user_id)

        assert user is not None
        assert user.id == user_id
        assert user.email == "byid@example.com"

    def test_returns_none_when_not_found(self, auth_db):
        """Returns None when ID doesn't exist."""
        fake_id = UUID("00000000-0000-0000-0000-000000000099")
        user = auth_db.get_user_by_id(fake_id)
        assert user is None


class TestCreateUser:
    """Test user creation."""

    def test_creates_user_with_email(self, auth_db, cleanup_user):
        """Creates user and returns User model."""
        cleanup_user("newuser@example.com")

        user = auth_db.create_user("newuser@example.com")

        assert isinstance(user, User)
        assert user.email == "newuser@example.com"
        assert user.id is not None
        assert user.created_at is not None

    def test_lowercases_email(self, auth_db, cleanup_user):
        """Email is lowercased on creation."""
        cleanup_user("uppercase@example.com")

        user = auth_db.create_user("UPPERCASE@EXAMPLE.COM")

        assert user.email == "uppercase@example.com"

    def test_duplicate_email_raises(self, db_admin, auth_db, cleanup_user):
        """Duplicate email raises exception."""
        cleanup_user("existing@example.com")
        db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("existing@example.com",),
        )

        with pytest.raises(Exception):  # IntegrityError
            auth_db.create_user("existing@example.com")


class TestGetOrCreateUser:
    """Test get-or-create pattern."""

    def test_returns_existing_user(self, db_admin, auth_db, cleanup_user):
        """Returns existing user with was_created=False."""
        cleanup_user("existing@example.com")
        db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("existing@example.com",),
        )

        user, was_created = auth_db.get_or_create_user("existing@example.com")

        assert was_created is False
        assert user.email == "existing@example.com"

    def test_creates_new_user(self, auth_db, cleanup_user):
        """Creates new user with was_created=True."""
        cleanup_user("brand_new@example.com")

        user, was_created = auth_db.get_or_create_user("brand_new@example.com")

        assert was_created is True
        assert user.email == "brand_new@example.com"


class TestUpdateLastLogin:
    """Test last_login_at update."""

    def test_updates_last_login_timestamp(self, db_admin, auth_db, cleanup_user):
        """Updates last_login_at to current time."""
        cleanup_user("login@example.com")
        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("login@example.com",),
        )
        user_id = result[0]["id"]
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        before = now_utc()
        auth_db.update_last_login(user_id)
        after = now_utc()

        row = db_admin.execute_single(
            "SELECT last_login_at FROM users WHERE id = %s",
            (str(user_id),),
        )
        assert row["last_login_at"] is not None
        assert before <= row["last_login_at"] <= after


class TestMagicLinkTokenOperations:
    """Test magic link token CRUD."""

    def test_store_and_retrieve_token(self, db_admin, auth_db, cleanup_user, cleanup_token):
        """Can store and retrieve magic link token."""
        cleanup_user("token@example.com")
        cleanup_token("test-token-123")

        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("token@example.com",),
        )
        user_id = result[0]["id"]
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        now = now_utc()
        token = MagicLinkToken(
            token="test-token-123",
            user_id=user_id,
            email="token@example.com",
            created_at=now,
            expires_at=now + timedelta(minutes=10),
            used=False,
        )
        auth_db.store_magic_link_token(token)

        retrieved = auth_db.get_magic_link_token("test-token-123")
        assert retrieved is not None
        assert retrieved.token == "test-token-123"
        assert retrieved.user_id == user_id
        assert retrieved.used is False

    def test_get_nonexistent_token_returns_none(self, auth_db):
        """Returns None for non-existent token."""
        result = auth_db.get_magic_link_token("nonexistent-token")
        assert result is None

    def test_mark_token_used(self, db_admin, auth_db, cleanup_user, cleanup_token):
        """Marks token as used."""
        cleanup_user("used@example.com")
        cleanup_token("to-be-used")

        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("used@example.com",),
        )
        user_id = result[0]["id"]
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        now = now_utc()
        token = MagicLinkToken(
            token="to-be-used",
            user_id=user_id,
            email="used@example.com",
            created_at=now,
            expires_at=now + timedelta(minutes=10),
            used=False,
        )
        auth_db.store_magic_link_token(token)

        auth_db.mark_token_used("to-be-used")

        retrieved = auth_db.get_magic_link_token("to-be-used")
        assert retrieved.used is True


class TestCleanupExpiredTokens:
    """Test expired token cleanup."""

    def test_deletes_expired_tokens(self, db_admin, auth_db, cleanup_user):
        """Removes expired tokens and returns count."""
        cleanup_user("cleanup@example.com")

        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("cleanup@example.com",),
        )
        user_id = result[0]["id"]

        past = now_utc() - timedelta(hours=1)
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at)
               VALUES (%s, %s, %s, %s, %s) RETURNING token""",
            ("expired-token", user_id, "cleanup@example.com", past - timedelta(hours=1), past),
        )

        count = auth_db.cleanup_expired_tokens()

        assert count >= 1
        assert auth_db.get_magic_link_token("expired-token") is None

    def test_preserves_valid_tokens(self, db_admin, auth_db, cleanup_user, cleanup_token):
        """Does not delete non-expired tokens."""
        cleanup_user("preserve@example.com")
        cleanup_token("valid-token")

        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("preserve@example.com",),
        )
        user_id = result[0]["id"]

        now = now_utc()
        db_admin.execute_returning(
            """INSERT INTO magic_link_tokens (token, user_id, email, created_at, expires_at)
               VALUES (%s, %s, %s, %s, %s) RETURNING token""",
            ("valid-token", user_id, "preserve@example.com", now, now + timedelta(hours=1)),
        )

        auth_db.cleanup_expired_tokens()

        assert auth_db.get_magic_link_token("valid-token") is not None


class TestUserDeactivation:
    """Test user activation/deactivation."""

    def test_deactivate_user(self, db_admin, auth_db, cleanup_user):
        """Deactivates user and returns True."""
        cleanup_user("deactivate@example.com")
        result = db_admin.execute_returning(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            ("deactivate@example.com",),
        )
        user_id = result[0]["id"]
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        success = auth_db.deactivate_user(user_id)

        assert success is True
        user = auth_db.get_user_by_id(user_id)
        assert user.is_active is False

    def test_deactivate_nonexistent_user(self, auth_db):
        """Returns False for nonexistent user."""
        fake_id = UUID("00000000-0000-0000-0000-000000000099")
        success = auth_db.deactivate_user(fake_id)
        assert success is False

    def test_activate_user(self, db_admin, auth_db, cleanup_user):
        """Reactivates user and returns True."""
        cleanup_user("reactivate@example.com")
        result = db_admin.execute_returning(
            "INSERT INTO users (email, is_active) VALUES (%s, %s) RETURNING id",
            ("reactivate@example.com", False),
        )
        user_id = result[0]["id"]
        if isinstance(user_id, str):
            user_id = UUID(user_id)

        success = auth_db.activate_user(user_id)

        assert success is True
        user = auth_db.get_user_by_id(user_id)
        assert user.is_active is True


class TestDeleteUser:
    """Test user deletion."""

    def test_delete_user(self, auth_db, cleanup_user):
        """Deletes user and returns True."""
        cleanup_user("delete@example.com")
        user = auth_db.create_user("delete@example.com")

        success = auth_db.delete_user(user.id)

        assert success is True
        assert auth_db.get_user_by_id(user.id) is None

    def test_delete_nonexistent_user(self, auth_db):
        """Returns False for nonexistent user."""
        fake_id = UUID("00000000-0000-0000-0000-000000000099")
        success = auth_db.delete_user(fake_id)
        assert success is False

    def test_delete_cascades_to_tokens(self, db_admin, auth_db, cleanup_user):
        """Deleting user also deletes their magic link tokens."""
        cleanup_user("cascade@example.com")
        user = auth_db.create_user("cascade@example.com")

        now = now_utc()
        token = MagicLinkToken(
            token="cascade-token",
            user_id=user.id,
            email="cascade@example.com",
            created_at=now,
            expires_at=now + timedelta(minutes=10),
            used=False,
        )
        auth_db.store_magic_link_token(token)

        auth_db.delete_user(user.id)

        assert auth_db.get_magic_link_token("cascade-token") is None
