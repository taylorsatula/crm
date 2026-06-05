"""HTTP routes for authentication."""

import ipaddress
from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Request, Response, Query
from fastapi.responses import JSONResponse

from auth.service import AuthService


def _get_client_ip(request: Request) -> str | None:
    """Extract valid IP address from request, or None if invalid."""
    if not request.client:
        return None
    host = request.client.host
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        return None


from auth.types import MagicLinkRequest
from auth.exceptions import (
    RateLimitedError,
    InvalidTokenError,
    UserInactiveError,
)
from api.base import success_response, error_response, ErrorCodes


# =============================================================================
# TEMPORARY DEVELOPMENT AUTOBYPASS - REMOVE BEFORE RELEASE.
# This constant chooses the repo's primary local/test RLS user. The
# /auth/dev-autobypass route below deliberately creates a session for this user
# without a magic link so private local frontend work can move quickly.
# =============================================================================
DEV_AUTOBYPASS_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
DEV_AUTOBYPASS_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def create_auth_router(auth_service: AuthService) -> APIRouter:
    """Create auth router with injected service."""
    router = APIRouter(tags=["auth"])

    def _request_id(request: Request) -> str | None:
        return getattr(request.state, "request_id", None)

    @router.post("/request-link")
    async def request_magic_link(request: Request, body: MagicLinkRequest):
        """Request magic link email.

        Returns:
            - sent=True, needs_signup=False: Email sent to existing user
            - sent=False, needs_signup=True: User doesn't exist, redirect to signup
        """
        ip_address = _get_client_ip(request)
        user_agent = request.headers.get("User-Agent")

        try:
            result = auth_service.request_magic_link(
                email=body.email,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        except RateLimitedError as e:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(e.retry_after_seconds)},
                content=error_response(
                    ErrorCodes.RATE_LIMITED,
                    f"Too many requests. Please wait {e.retry_after_seconds} seconds.",
                    request_id=_request_id(request),
                ).model_dump(mode="json"),
            )

        return success_response(
            asdict(result),
            request_id=_request_id(request),
        ).model_dump(mode="json")

    @router.get("/verify")
    async def verify_magic_link(
        request: Request,
        response: Response,
        token: str = Query(None),
    ):
        """Verify magic link token and create session.

        Sets session_token cookie on success.
        """
        if not token:
            return JSONResponse(
                status_code=400,
                content=error_response(
                    ErrorCodes.INVALID_REQUEST,
                    "Token parameter is required",
                    request_id=_request_id(request),
                ).model_dump(mode="json"),
            )

        ip_address = _get_client_ip(request)
        user_agent = request.headers.get("User-Agent")

        try:
            result = auth_service.verify_magic_link(
                token=token,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        except InvalidTokenError:
            return JSONResponse(
                status_code=401,
                content=error_response(
                    ErrorCodes.INVALID_TOKEN,
                    "Invalid or expired token",
                    request_id=_request_id(request),
                ).model_dump(mode="json"),
            )
        except UserInactiveError:
            return JSONResponse(
                status_code=403,
                content=error_response(
                    ErrorCodes.NOT_AUTHENTICATED,
                    "Account is deactivated",
                    request_id=_request_id(request),
                ).model_dump(mode="json"),
            )

        # Set session cookie
        response.set_cookie(
            key="session_token",
            value=result.session.token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=int((result.session.expires_at - result.session.created_at).total_seconds()),
        )

        return success_response(
            {
                "user": {
                    "id": str(result.user.id),
                    "email": result.user.email,
                }
            },
            request_id=_request_id(request),
        ).model_dump(mode="json")

    @router.post("/dev-autobypass")
    async def development_autobypass(request: Request, response: Response):
        # =====================================================================
        # TEMPORARY DEVELOPMENT AUTOBYPASS - REMOVE BEFORE RELEASE.
        # Insecure by design: this local-only endpoint mints a real auth session
        # with no email proof. It is intentionally loud and isolated so it cannot
        # be mistaken for a supported authentication mode.
        # =====================================================================
        client_host = request.client.host if request.client else None
        if client_host not in DEV_AUTOBYPASS_LOOPBACK_HOSTS:
            return JSONResponse(
                status_code=403,
                content=error_response(
                    ErrorCodes.AUTHORIZATION_DENIED,
                    "Development auth bypass is only allowed from loopback",
                    request_id=_request_id(request),
                ).model_dump(mode="json"),
            )

        session = auth_service.create_development_autobypass_session(
            DEV_AUTOBYPASS_USER_ID
        )
        response.set_cookie(
            key="session_token",
            value=session.token,
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=int((session.expires_at - session.created_at).total_seconds()),
        )

        return success_response(
            {
                "user_id": str(session.user_id),
                "temporary_development_autobypass": True,
            },
            request_id=_request_id(request),
        ).model_dump(mode="json")

    @router.post("/logout")
    async def logout(request: Request, response: Response):
        """Logout - revoke session and clear cookie."""
        session_token = request.cookies.get("session_token")
        ip_address = _get_client_ip(request)

        if session_token:
            auth_service.logout(
                session_token=session_token,
                ip_address=ip_address,
            )

        # Clear cookie
        response.delete_cookie(key="session_token")

        return success_response(
            {"message": "Logged out successfully"},
            request_id=_request_id(request),
        ).model_dump(mode="json")

    @router.get("/me")
    async def get_current_user(request: Request):
        """Get current authenticated user.

        Requires authentication (middleware sets user context).
        """
        if not hasattr(request.state, "user_id"):
            return JSONResponse(
                status_code=401,
                content=error_response(
                    ErrorCodes.NOT_AUTHENTICATED,
                    "Authentication required",
                    request_id=_request_id(request),
                ).model_dump(mode="json"),
            )

        user_id = request.state.user_id

        return success_response(
            {
                "user_id": str(user_id),
            },
            request_id=_request_id(request),
        ).model_dump(mode="json")

    return router
