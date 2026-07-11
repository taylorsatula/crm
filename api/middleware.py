"""Request identity middleware for CRM workspace and lifecycle calls."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from uuid import uuid4

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
    """Assign a unique request ID to every request."""

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class WorkspaceAccessMiddleware(BaseHTTPMiddleware):
    """Authenticate workspace tokens or the separate lifecycle boundary."""

    HEALTH_PATHS = {"/health", "/health/ready", "/health/live"}
    LIFECYCLE_PREFIX = "/api/lifecycle/"
    FORBIDDEN_WORKSPACE_HEADERS = ("X-Workspace-ID", "X-Workspace-Timezone")

    def __init__(
        self,
        app,
        *,
        postgres,
        lifecycle_service_secret: str | Callable[[], str],
    ) -> None:
        super().__init__(app)
        self._postgres = postgres
        self._lifecycle_service_secret = lifecycle_service_secret

    @property
    def postgres(self):
        return self._postgres() if callable(self._postgres) else self._postgres

    @staticmethod
    def _error(
        request: Request,
        message: str,
        *,
        status_code: int = 401,
        code: str = ErrorCodes.NOT_AUTHENTICATED,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content=error_response(
                code,
                message,
                request_id=getattr(request.state, "request_id", None),
            ).model_dump(mode="json"),
        )

    @staticmethod
    def _bearer_credential(request: Request) -> str | None:
        authorization = request.headers.get("Authorization")
        scheme, separator, credential = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not separator or not credential:
            return None
        return credential

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.HEALTH_PATHS:
            return await call_next(request)

        credential = self._bearer_credential(request)
        if credential is None:
            return self._error(request, "Missing or malformed bearer credential")

        if request.url.path.startswith(self.LIFECYCLE_PREFIX):
            expected_secret = (
                self._lifecycle_service_secret()
                if callable(self._lifecycle_service_secret)
                else self._lifecycle_service_secret
            )
            if not expected_secret:
                raise RuntimeError("Lifecycle service secret was not initialized")
            if not hmac.compare_digest(credential, expected_secret):
                return self._error(request, "Invalid lifecycle bearer credential")
            request.state.lifecycle_authenticated = True
            return await call_next(request)

        spoofed = [
            header for header in self.FORBIDDEN_WORKSPACE_HEADERS
            if request.headers.get(header) is not None
        ]
        if spoofed:
            return self._error(
                request,
                f"Workspace identity headers are forbidden: {', '.join(spoofed)}",
                status_code=400,
                code=ErrorCodes.INVALID_REQUEST,
            )

        token_hash = hashlib.sha256(credential.encode("utf-8")).hexdigest()
        required_scope = "read" if request.method in {"GET", "HEAD", "OPTIONS"} else "write"
        token = self.postgres.execute_single(
            """
            SELECT id, workspace_id, scopes
            FROM workspace_access_tokens
            WHERE token_hash = %s
              AND revoked_at IS NULL
              AND (expires_at IS NULL OR expires_at > NOW())
            """,
            (token_hash,),
        )
        if not token:
            return self._error(request, "Invalid, expired, or revoked workspace token")
        if required_scope not in token["scopes"]:
            return self._error(
                request,
                f"Workspace token lacks required '{required_scope}' scope",
                status_code=403,
                code=ErrorCodes.NOT_AUTHENTICATED,
            )

        workspace_id = token["workspace_id"]
        set_current_workspace_id(workspace_id)
        try:
            workspace = self.postgres.execute_single(
                "SELECT timezone FROM workspaces WHERE id = %s",
                (workspace_id,),
            )
            if not workspace:
                return self._error(request, "Workspace for token no longer exists")
            timezone = workspace["timezone"]
            set_current_workspace_timezone(timezone)
            self.postgres.execute(
                "UPDATE workspace_access_tokens SET last_used_at = NOW() WHERE id = %s",
                (token["id"],),
            )
            request.state.workspace_id = workspace_id
            request.state.workspace_timezone = timezone
            request.state.workspace_token_id = token["id"]
            request.state.workspace_scopes = tuple(token["scopes"])
            return await call_next(request)
        finally:
            clear_workspace_context()
