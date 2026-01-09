"""HTTP routes for authentication."""

import ipaddress
from dataclasses import asdict

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


def create_auth_router(auth_service: AuthService) -> APIRouter:
    """Create auth router with injected service."""
    router = APIRouter(tags=["auth"])

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
                ).model_dump(mode="json"),
            )

        return success_response(asdict(result))

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
                ).model_dump(mode="json"),
            )
        except UserInactiveError:
            return JSONResponse(
                status_code=403,
                content=error_response(
                    ErrorCodes.NOT_AUTHENTICATED,
                    "Account is deactivated",
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

        return success_response({
            "user": {
                "id": str(result.user.id),
                "email": result.user.email,
            }
        })

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

        return success_response({"message": "Logged out successfully"})

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
                ).model_dump(mode="json"),
            )

        user_id = request.state.user_id

        return success_response({
            "user_id": str(user_id),
        })

    return router
