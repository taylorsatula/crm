"""Authentication configuration."""

from pydantic import BaseModel, Field


class AuthConfig(BaseModel):
    """
    Authentication configuration.

    All durations are in their natural units (minutes for short durations,
    hours for longer ones) to make configuration intuitive.
    """

    # Magic link settings
    magic_link_expiry_minutes: int = Field(
        default=10,
        description="How long magic links remain valid",
        ge=5,
        le=60,
    )

    # Session settings
    session_expiry_hours: int = Field(
        default=2160,  # 90 days
        description="Session lifetime in hours",
        ge=1,
        le=2160,
    )
    session_extend_on_activity: bool = Field(
        default=True,
        description="Whether to extend session expiry on activity",
    )
    session_extend_threshold_hours: int = Field(
        default=24,
        description="Extend session if less than this many hours remaining",
        ge=1,
    )

    # Rate limiting
    rate_limit_attempts: int = Field(
        default=5,
        description="Max magic link requests per email per window",
        ge=1,
        le=20,
    )
    rate_limit_window_minutes: int = Field(
        default=15,
        description="Rate limit window duration",
        ge=5,
        le=60,
    )

    # Application
    app_base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL for magic link generation",
    )
    app_name: str = Field(
        default="CRM",
        description="Application name for emails",
    )
