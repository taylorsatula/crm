"""Authentication and authorization modules."""

from auth.exceptions import (
    AuthError,
    InvalidTokenError,
    RateLimitedError,
    UserNotFoundError,
    SessionExpiredError,
    SessionRevokedError,
    UserInactiveError,
)
from auth.types import (
    User,
    Session,
    MagicLinkRequest,
    MagicLinkToken,
    AuthenticatedUser,
)
from auth.config import AuthConfig
from auth.database import AuthDatabase
from auth.rate_limiter import RateLimiter
from auth.security_logger import SecurityLogger, SecurityEvent
from auth.session import SessionManager
from auth.service import AuthService, MagicLinkResult
from auth.security_middleware import AuthMiddleware
from auth.api import create_auth_router
