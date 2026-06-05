"""Security middleware for FastAPI - session validation and user context."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from auth.session import SessionManager
from auth.exceptions import SessionExpiredError
from api.base import error_response, ErrorCodes
from utils.user_context import set_current_user_id, clear_current_user_id


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that validates session and sets user context.

    For protected routes:
    1. Extracts session token from 'session_token' cookie
    2. Validates session via SessionManager
    3. Sets user_id in request.state and user context (for RLS)
    4. Clears context after request completes

    Public paths bypass authentication entirely.
    """

    EXACT_PUBLIC_PATHS = {
        "/",
        "/auth/request-link",
        "/auth/verify",
        # =====================================================================
        # TEMPORARY DEVELOPMENT AUTOBYPASS - REMOVE BEFORE RELEASE.
        # This intentionally allows unauthenticated local browser sessions to
        # mint a session cookie without a magic link. It exists only so the
        # greenfield wireframe can be exercised rapidly during private local
        # development.
        # =====================================================================
        "/auth/dev-autobypass",
        "/auth/logout",
        "/health",
        "/health/ready",
        "/health/live",
        "/docs",
        "/openapi.json",
    }
    PREFIX_PUBLIC_PATHS = (
        "/assets/",
        "/docs/",
    )

    def __init__(self, app, session_manager: SessionManager):
        super().__init__(app)
        self._session_manager = session_manager

    def _is_public_path(self, path: str) -> bool:
        """Check if path is in public paths list."""
        if path in self.EXACT_PUBLIC_PATHS:
            return True

        for public_path in self.PREFIX_PUBLIC_PATHS:
            if path.startswith(public_path):
                return True
        return False

    async def dispatch(self, request: Request, call_next):
        """Process request through middleware."""
        path = request.url.path
        request_id = getattr(request.state, "request_id", None)

        # Skip auth for public paths
        if self._is_public_path(path):
            return await call_next(request)

        # Extract session token from cookie
        session_token = request.cookies.get("session_token")

        if not session_token:
            return JSONResponse(
                status_code=401,
                content=error_response(
                    ErrorCodes.NOT_AUTHENTICATED,
                    "Authentication required",
                    request_id=request_id,
                ).model_dump(mode="json"),
            )

        # Validate session
        try:
            session = self._session_manager.validate_session(session_token)
        except SessionExpiredError:
            return JSONResponse(
                status_code=401,
                content=error_response(
                    ErrorCodes.SESSION_EXPIRED,
                    "Session has expired",
                    request_id=request_id,
                ).model_dump(mode="json"),
            )

        # Set user context for RLS
        set_current_user_id(session.user_id)
        request.state.user_id = session.user_id
        request.state.session = session

        try:
            response = await call_next(request)
            return response
        finally:
            # Always clear context
            clear_current_user_id()
