"""Security middleware for FastAPI - session validation and user context."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from auth.access_tokens import AccessTokenManager, access_token_has_scope
from auth.session import SessionManager
from auth.exceptions import InvalidTokenError, SessionExpiredError, UserInactiveError
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

    def __init__(
        self,
        app,
        session_manager: SessionManager,
        access_token_manager: AccessTokenManager | None = None,
    ):
        super().__init__(app)
        self._session_manager = session_manager
        self._access_token_manager = access_token_manager

    def _is_public_path(self, path: str) -> bool:
        """Check if path is in public paths list."""
        if path in self.EXACT_PUBLIC_PATHS:
            return True

        for public_path in self.PREFIX_PUBLIC_PATHS:
            if path.startswith(public_path):
                return True
        return False

    def _required_access_token_scope(self, method: str, path: str) -> str:
        """Map protected requests to a coarse access-token scope."""
        if path.startswith("/api/actions"):
            return "write"
        if method.upper() in {"GET", "HEAD"}:
            return "read"
        return "write"

    def _auth_error_response(
        self,
        status_code: int,
        code: str,
        message: str,
        request_id: str | None,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content=error_response(
                code,
                message,
                request_id=request_id,
            ).model_dump(mode="json"),
        )

    async def dispatch(self, request: Request, call_next):
        """Process request through middleware."""
        path = request.url.path
        request_id = getattr(request.state, "request_id", None)

        # Skip auth for public paths
        if self._is_public_path(path):
            return await call_next(request)

        authorization = request.headers.get("Authorization")
        if authorization is not None:
            scheme, separator, credential = authorization.partition(" ")
            if scheme.lower() != "bearer" or not separator:
                return self._auth_error_response(
                    401,
                    ErrorCodes.INVALID_TOKEN,
                    "Invalid access token",
                    request_id,
                )
            raw_token = credential.strip()
            if not raw_token or self._access_token_manager is None:
                return self._auth_error_response(
                    401,
                    ErrorCodes.INVALID_TOKEN,
                    "Invalid access token",
                    request_id,
                )

            try:
                principal = self._access_token_manager.validate_token(raw_token)
            except InvalidTokenError:
                return self._auth_error_response(
                    401,
                    ErrorCodes.INVALID_TOKEN,
                    "Invalid access token",
                    request_id,
                )
            except UserInactiveError:
                return self._auth_error_response(
                    403,
                    ErrorCodes.NOT_AUTHENTICATED,
                    "Account is deactivated",
                    request_id,
                )

            required_scope = self._required_access_token_scope(request.method, path)
            if not access_token_has_scope(principal.scopes, required_scope):
                return self._auth_error_response(
                    403,
                    ErrorCodes.AUTHORIZATION_DENIED,
                    f"Access token requires '{required_scope}' scope",
                    request_id,
                )

            set_current_user_id(principal.user_id)
            request.state.user_id = principal.user_id
            request.state.auth_method = "access_token"
            request.state.access_token_id = principal.token_id
            request.state.access_token_scopes = principal.scopes

            try:
                response = await call_next(request)
                return response
            finally:
                clear_current_user_id()

        # Extract session token from cookie
        session_token = request.cookies.get("session_token")

        if not session_token:
            return self._auth_error_response(
                401,
                ErrorCodes.NOT_AUTHENTICATED,
                "Authentication required",
                request_id,
            )

        # Validate session
        try:
            session = self._session_manager.validate_session(session_token)
        except SessionExpiredError:
            return self._auth_error_response(
                401,
                ErrorCodes.SESSION_EXPIRED,
                "Session has expired",
                request_id,
            )

        # Set user context for RLS
        set_current_user_id(session.user_id)
        request.state.user_id = session.user_id
        request.state.session = session
        request.state.auth_method = "session"

        try:
            response = await call_next(request)
            return response
        finally:
            # Always clear context
            clear_current_user_id()
