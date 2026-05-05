"""Health endpoints for process and runtime dependencies."""

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from api.base import ErrorCodes, error_response, success_response


def create_health_router(health_checks: Mapping[str, Any]) -> APIRouter:
    """Create health router with injected dependency checks."""
    router = APIRouter(tags=["health"])

    def _request_id(request: Request) -> str | None:
        return getattr(request.state, "request_id", None)

    def _run_checks() -> dict[str, dict[str, str]]:
        results = {}

        for name, checker in health_checks.items():
            try:
                healthy = checker.health_check()
            except Exception as exc:
                results[name] = {
                    "status": "unhealthy",
                    "message": str(exc),
                }
                continue

            if healthy is True:
                results[name] = {"status": "healthy"}
            else:
                results[name] = {
                    "status": "unhealthy",
                    "message": "health_check returned false",
                }

        return results

    async def _diagnostic_health(request: Request):
        checks = _run_checks()
        healthy = all(check["status"] == "healthy" for check in checks.values())
        data = {
            "status": "healthy" if healthy else "unhealthy",
            "checks": checks,
        }

        if healthy:
            return success_response(
                data,
                request_id=_request_id(request),
            ).model_dump(mode="json")

        return JSONResponse(
            status_code=503,
            content=error_response(
                ErrorCodes.SERVICE_UNAVAILABLE,
                "One or more runtime dependencies are unavailable",
                request_id=_request_id(request),
                data=data,
            ).model_dump(mode="json"),
        )

    @router.get("/health")
    async def health(request: Request):
        return await _diagnostic_health(request)

    @router.get("/health/ready")
    async def ready(request: Request):
        return await _diagnostic_health(request)

    @router.get("/health/live")
    async def live(request: Request):
        return success_response(
            {"status": "alive"},
            request_id=_request_id(request),
        ).model_dump(mode="json")

    return router
