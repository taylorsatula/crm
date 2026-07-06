"""Tests for long-lived access token management."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from auth.access_tokens import (
    ACCESS_TOKEN_KIND,
    AccessTokenManager,
    access_token_has_scope,
    hash_access_token,
    normalize_access_token_scopes,
)
from auth.exceptions import InvalidTokenError, UserInactiveError
from utils.timezone import now_utc


class FakeAccessTokenDb:
    def __init__(self):
        self.rows_by_prefix = {}
        self.updated_last_used_for = []
        self.user_is_active = True

    def execute_returning(self, query, params=None):
        normalized_query = " ".join(query.split())
        if normalized_query.startswith("INSERT INTO access_tokens"):
            user_id, name, token_prefix, token_hash, scopes, expires_at = params
            now = now_utc()
            row = {
                "id": uuid4(),
                "user_id": UUID(user_id),
                "name": name,
                "token_prefix": token_prefix,
                "token_hash": token_hash,
                "scopes": scopes,
                "created_at": now,
                "expires_at": expires_at,
                "last_used_at": None,
                "revoked_at": None,
            }
            self.rows_by_prefix[token_prefix] = row
            return [row]

        if normalized_query.startswith("UPDATE access_tokens SET last_used_at"):
            _, token_id = params
            self.updated_last_used_for.append(UUID(token_id))
            return [{"id": UUID(token_id)}]

        raise AssertionError(f"Unexpected execute_returning query: {query}")

    def execute_single(self, query, params=None):
        token_prefix = params[0]
        row = self.rows_by_prefix.get(token_prefix)
        if row is None:
            return None
        return {**row, "is_active": self.user_is_active}


@pytest.fixture
def fake_db():
    return FakeAccessTokenDb()


@pytest.fixture
def manager(fake_db):
    return AccessTokenManager(fake_db)


def test_create_token_returns_raw_token_once_and_stores_hash(manager, fake_db, test_user_id):
    created = manager.create_token(
        user_id=test_user_id,
        name="Local scripts",
        scopes={"read", "write"},
        expires_at=now_utc() + timedelta(days=365),
    )

    assert created.token.startswith(f"{ACCESS_TOKEN_KIND}_")
    assert created.access_token.user_id == test_user_id
    assert created.access_token.name == "Local scripts"
    assert created.access_token.scopes == {"read", "write"}
    assert created.access_token.token_hash == hash_access_token(created.token)
    assert created.access_token.token_hash != created.token
    assert created.access_token.token_prefix in fake_db.rows_by_prefix


def test_validate_token_returns_principal_and_updates_last_used(manager, fake_db, test_user_id):
    created = manager.create_token(
        user_id=test_user_id,
        name="Reader",
        scopes={"read"},
        expires_at=now_utc() + timedelta(days=365),
    )

    principal = manager.validate_token(created.token)

    assert principal.user_id == test_user_id
    assert principal.token_id == created.access_token.id
    assert principal.scopes == {"read"}
    assert fake_db.updated_last_used_for == [created.access_token.id]


def test_validate_token_rejects_tampered_token(manager, test_user_id):
    created = manager.create_token(
        user_id=test_user_id,
        name="Reader",
        scopes={"read"},
        expires_at=now_utc() + timedelta(days=365),
    )

    with pytest.raises(InvalidTokenError):
        manager.validate_token(f"{created.token}tampered")


def test_validate_token_rejects_expired_token(manager, fake_db, test_user_id):
    created = manager.create_token(
        user_id=test_user_id,
        name="Reader",
        scopes={"read"},
        expires_at=now_utc() + timedelta(days=365),
    )
    fake_db.rows_by_prefix[created.access_token.token_prefix]["expires_at"] = (
        now_utc() - timedelta(seconds=1)
    )

    with pytest.raises(InvalidTokenError):
        manager.validate_token(created.token)


def test_validate_token_rejects_revoked_token(manager, fake_db, test_user_id):
    created = manager.create_token(
        user_id=test_user_id,
        name="Reader",
        scopes={"read"},
        expires_at=now_utc() + timedelta(days=365),
    )
    fake_db.rows_by_prefix[created.access_token.token_prefix]["revoked_at"] = now_utc()

    with pytest.raises(InvalidTokenError):
        manager.validate_token(created.token)


def test_validate_token_rejects_inactive_user(manager, fake_db, test_user_id):
    created = manager.create_token(
        user_id=test_user_id,
        name="Reader",
        scopes={"read"},
        expires_at=now_utc() + timedelta(days=365),
    )
    fake_db.user_is_active = False

    with pytest.raises(UserInactiveError):
        manager.validate_token(created.token)


def test_normalize_scopes_rejects_unknown_scope():
    with pytest.raises(ValueError, match="Unknown access token scope"):
        normalize_access_token_scopes(["read", "owner"])


def test_admin_scope_satisfies_read_and_write():
    assert access_token_has_scope({"admin"}, "read") is True
    assert access_token_has_scope({"admin"}, "write") is True
    assert access_token_has_scope({"read"}, "write") is False
