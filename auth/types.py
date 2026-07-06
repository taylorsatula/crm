"""Pydantic models for auth domain."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class User(BaseModel):
    """A registered user of the system."""

    id: UUID
    email: EmailStr
    is_active: bool = True
    created_at: datetime
    last_login_at: datetime | None = None

    model_config = {"from_attributes": True}


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
    used: bool  # Required - fail closed, no default


class AuthenticatedUser(BaseModel):
    """User info returned after successful authentication."""

    user: User
    session: Session


class AccessToken(BaseModel):
    """A persisted personal access token record."""

    id: UUID
    user_id: UUID
    name: str
    token_prefix: str
    token_hash: str
    scopes: set[str] = Field(..., description="Coarse permissions granted to the token")
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class CreatedAccessToken(BaseModel):
    """A newly-created access token. Raw token is shown once."""

    token: str = Field(..., description="Raw bearer token; store it immediately")
    access_token: AccessToken


class AccessTokenPrincipal(BaseModel):
    """Authenticated principal derived from a bearer access token."""

    token_id: UUID
    user_id: UUID
    scopes: set[str]
