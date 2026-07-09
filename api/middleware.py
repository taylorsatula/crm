"""Request-scoped middleware for private CRM service requests."""

import hmac
from collections.abc import Callable
from uuid import uuid4
from uuid import UUID
from zoneinfo import ZoneInfo

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.base import ErrorCodes, error_response
from utils.workspace_context import (
    clear_workspace_context,
    set_current_workspace_id,
    set_current_workspace_timezone,
)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assigns a unique request ID to every request."""

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class InternalWorkspaceMiddleware(BaseHTTPMiddleware):
    """Authenticate private callers and establish the request workspace context."""

    HEALTH_PATHS = {"/health", "/health/ready", "/health/live"}

    def __init__(self, app, *, internal_service_secret: str | Callable[[], str]):
        super().__init__(app)
        self._internal_service_secret = internal_service_secret

    @staticmethod
    def _error(request: Request, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content=error_response(
                ErrorCodes.NOT_AUTHENTICATED,
                message,
                request_id=getattr(request.state, "request_id", None),
            ).model_dump(mode="json"),
        )

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.HEALTH_PATHS:
            return await call_next(request)

        authorization = request.headers.get("Authorization")
        scheme, separator, credential = (authorization or "").partition(" ")
        if scheme != "Bearer" or not separator or not credential:
            return self._error(request, "Missing or malformed internal bearer credential")
        expected_secret = (
            self._internal_service_secret()
            if callable(self._internal_service_secret)
            else self._internal_service_secret
        )
        if not expected_secret:
            raise RuntimeError("Internal service secret was not initialized")
        if not hmac.compare_digest(credential, expected_secret):
            return self._error(request, "Invalid internal bearer credential")

        raw_workspace_id = request.headers.get("X-Workspace-ID")
        try:
            workspace_id = UUID(raw_workspace_id or "")
        except (ValueError, AttributeError):
            return self._error(request, "X-Workspace-ID must be a UUID")

        timezone = request.headers.get("X-Workspace-Timezone")
        try:
            ZoneInfo(timezone or "")
        except (ValueError, AttributeError, KeyError):
            return self._error(request, "X-Workspace-Timezone must be an IANA timezone")

        request.state.workspace_id = workspace_id
        request.state.workspace_timezone = timezone
        set_current_workspace_id(workspace_id)
        set_current_workspace_timezone(timezone)
        try:
            return await call_next(request)
        finally:
            clear_workspace_context()
