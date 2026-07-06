"""Long-lived personal access token management.

Access tokens are opaque bearer credentials. The raw token is shown once at
creation time; only a SHA-256 hash and lookup prefix are stored.
"""

import hashlib
import hmac
import secrets
from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from clients.postgres_client import PostgresClient
from auth.exceptions import InvalidTokenError, UserInactiveError
from auth.types import AccessToken, AccessTokenPrincipal, CreatedAccessToken
from utils.timezone import now_utc, to_utc

ACCESS_TOKEN_KIND = "crm_pat"
ALLOWED_ACCESS_TOKEN_SCOPES = frozenset({"read", "write", "admin"})


class AccessTokenManager:
    """Create and validate long-lived personal access tokens."""

    def __init__(self, postgres: PostgresClient):
        self._db = postgres

    def create_token(
        self,
        *,
        user_id: UUID,
        name: str,
        scopes: Iterable[str],
        expires_at: datetime,
    ) -> CreatedAccessToken:
        """Create a token and return the raw token exactly once."""
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Access token name is required")

        normalized_scopes = normalize_access_token_scopes(scopes)
        expires_at = to_utc(expires_at)
        if expires_at <= now_utc():
            raise ValueError("Access token expiry must be in the future")

        token_prefix = secrets.token_hex(8)
        token_secret = secrets.token_urlsafe(32)
        raw_token = f"{ACCESS_TOKEN_KIND}_{token_prefix}_{token_secret}"
        token_hash = hash_access_token(raw_token)

        rows = self._db.execute_returning(
            """
            INSERT INTO access_tokens (user_id, name, token_prefix, token_hash, scopes, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, user_id, name, token_prefix, token_hash, scopes,
                      created_at, expires_at, last_used_at, revoked_at
            """,
            (
                str(user_id),
                clean_name,
                token_prefix,
                token_hash,
                sorted(normalized_scopes),
                expires_at,
            ),
        )
        access_token = _access_token_from_row(rows[0])
        return CreatedAccessToken(token=raw_token, access_token=access_token)

    def validate_token(self, raw_token: str) -> AccessTokenPrincipal:
        """Validate a bearer token and return its authenticated principal."""
        token_prefix = parse_access_token_prefix(raw_token)
        row = self._db.execute_single(
            """
            SELECT at.id, at.user_id, at.name, at.token_prefix, at.token_hash, at.scopes,
                   at.created_at, at.expires_at, at.last_used_at, at.revoked_at,
                   u.is_active
            FROM access_tokens at
            JOIN users u ON u.id = at.user_id
            WHERE at.token_prefix = %s
            """,
            (token_prefix,),
        )
        if row is None:
            raise InvalidTokenError("Access token is invalid")

        if not hmac.compare_digest(row["token_hash"], hash_access_token(raw_token)):
            raise InvalidTokenError("Access token is invalid")

        if row["revoked_at"] is not None:
            raise InvalidTokenError("Access token has been revoked")

        expires_at = to_utc(row["expires_at"])
        if now_utc() > expires_at:
            raise InvalidTokenError("Access token has expired")

        if not row["is_active"]:
            raise UserInactiveError("Access token user is inactive")

        token_id = _uuid(row["id"])
        user_id = _uuid(row["user_id"])
        self._db.execute_returning(
            "UPDATE access_tokens SET last_used_at = %s WHERE id = %s RETURNING id",
            (now_utc(), str(token_id)),
        )

        return AccessTokenPrincipal(
            token_id=token_id,
            user_id=user_id,
            scopes=set(row["scopes"]),
        )


def normalize_access_token_scopes(scopes: Iterable[str]) -> frozenset[str]:
    """Normalize and validate coarse access-token scopes."""
    normalized = frozenset(scope.strip().lower() for scope in scopes if scope.strip())
    if not normalized:
        raise ValueError("At least one access token scope is required")

    unknown = normalized - ALLOWED_ACCESS_TOKEN_SCOPES
    if unknown:
        allowed = ", ".join(sorted(ALLOWED_ACCESS_TOKEN_SCOPES))
        raise ValueError(
            f"Unknown access token scope(s): {', '.join(sorted(unknown))}. "
            f"Allowed scopes: {allowed}"
        )

    return normalized


def access_token_has_scope(scopes: set[str], required_scope: str) -> bool:
    """Return whether token scopes satisfy a required coarse scope."""
    return "admin" in scopes or required_scope in scopes


def hash_access_token(raw_token: str) -> str:
    """Hash the complete raw token for storage and comparison."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def parse_access_token_prefix(raw_token: str) -> str:
    """Extract the lookup prefix from a raw CRM access token."""
    if not raw_token.startswith(f"{ACCESS_TOKEN_KIND}_"):
        raise InvalidTokenError("Access token has invalid format")

    remainder = raw_token[len(ACCESS_TOKEN_KIND) + 1 :]
    token_prefix, separator, token_secret = remainder.partition("_")
    if not token_prefix or not separator or not token_secret:
        raise InvalidTokenError("Access token has invalid format")

    return token_prefix


def _access_token_from_row(row: dict) -> AccessToken:
    return AccessToken(
        id=_uuid(row["id"]),
        user_id=_uuid(row["user_id"]),
        name=row["name"],
        token_prefix=row["token_prefix"],
        token_hash=row["token_hash"],
        scopes=set(row["scopes"]),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        last_used_at=row["last_used_at"],
        revoked_at=row["revoked_at"],
    )


def _uuid(value: UUID | str) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(value)
