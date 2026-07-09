"""Global exception handlers for FastAPI."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from api.base import error_response, ErrorCodes
from core.exceptions import DomainError, NotFoundError

logger = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    """Register global exception handlers on the app."""

    def _request_id(request: Request) -> str | None:
        return getattr(request.state, "request_id", None)

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        return JSONResponse(
            status_code=exc.http_status,
            content=error_response(
                exc.code,
                str(exc),
                request_id=_request_id(request),
            ).model_dump(mode="json"),
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        message = str(exc)
        if "not found" in message.lower():
            return JSONResponse(
                status_code=404,
                content=error_response(
                    ErrorCodes.NOT_FOUND,
                    message,
                    request_id=_request_id(request),
                ).model_dump(mode="json"),
            )
        return JSONResponse(
            status_code=400,
            content=error_response(
                ErrorCodes.INVALID_REQUEST,
                message,
                request_id=_request_id(request),
            ).model_dump(mode="json"),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=error_response(
                ErrorCodes.VALIDATION_ERROR,
                str(exc.errors()),
                request_id=_request_id(request),
            ).model_dump(mode="json"),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception")
        return JSONResponse(
            status_code=500,
            content=error_response(
                ErrorCodes.INTERNAL_ERROR,
                "An internal error occurred",
                request_id=_request_id(request),
            ).model_dump(mode="json"),
        )
