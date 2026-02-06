"""Global exception handlers for FastAPI."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from api.base import error_response, ErrorCodes

logger = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    """Register global exception handlers on the app."""

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        message = str(exc)
        if "not found" in message.lower():
            return JSONResponse(
                status_code=404,
                content=error_response(ErrorCodes.NOT_FOUND, message).model_dump(mode="json"),
            )
        return JSONResponse(
            status_code=400,
            content=error_response(ErrorCodes.INVALID_REQUEST, message).model_dump(mode="json"),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=error_response(
                ErrorCodes.VALIDATION_ERROR,
                str(exc.errors()),
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
            ).model_dump(mode="json"),
        )
