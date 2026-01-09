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
