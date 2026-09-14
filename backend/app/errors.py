"""Consistent error-response contract shared by every endpoint.

Every failure is rendered as:

    {"error": {"code": "...", "message": "...", "requestId": "..."}}
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """Base class for every error the application raises deliberately."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class BadRequestError(AppError):
    def __init__(self, message: str, code: str = "BAD_REQUEST") -> None:
        super().__init__(400, code, message)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Authentication is missing, expired, or invalid.") -> None:
        super().__init__(401, "UNAUTHORIZED", message)


class ForbiddenError(AppError):
    def __init__(
        self, message: str = "You do not have permission to access this resource."
    ) -> None:
        super().__init__(403, "FORBIDDEN", message)


class NotFoundError(AppError):
    def __init__(self, message: str, code: str = "NOT_FOUND") -> None:
        super().__init__(404, code, message)


class ConflictError(AppError):
    def __init__(self, message: str, code: str = "CONFLICT") -> None:
        super().__init__(409, code, message)


class PayloadTooLargeError(AppError):
    def __init__(self, message: str = "Request payload exceeds the permitted size.") -> None:
        super().__init__(413, "PAYLOAD_TOO_LARGE", message)


class UnprocessableError(AppError):
    def __init__(self, message: str, code: str = "UNPROCESSABLE_REQUEST") -> None:
        super().__init__(422, code, message)


class RateLimitError(AppError):
    def __init__(self, message: str = "Rate limit exceeded. Please retry shortly.") -> None:
        super().__init__(429, "RATE_LIMIT_EXCEEDED", message)


class UpstreamError(AppError):
    """External AI or customer-data system returned an invalid response."""

    def __init__(self, message: str = "An upstream system returned an invalid response.") -> None:
        super().__init__(502, "UPSTREAM_INVALID_RESPONSE", message)


class DependencyUnavailableError(AppError):
    def __init__(self, message: str = "A required dependency is unavailable.") -> None:
        super().__init__(503, "DEPENDENCY_UNAVAILABLE", message)


class UpstreamTimeoutError(AppError):
    def __init__(
        self, message: str = "An external dependency exceeded the configured timeout."
    ) -> None:
        super().__init__(504, "UPSTREAM_TIMEOUT", message)


def error_body(code: str, message: str, request_id: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "requestId": request_id}}


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, _request_id(request)),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        detail = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(part) for part in detail.get("loc", [])[1:]) or "request"
        reason = detail.get("msg", "Request failed validation.")
        return JSONResponse(
            status_code=422,
            content=error_body(
                "INVALID_REQUEST",
                f"Field '{field}' is invalid: {reason}",
                _request_id(request),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            413: "PAYLOAD_TOO_LARGE",
            429: "RATE_LIMIT_EXCEEDED",
        }
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(
                codes.get(exc.status_code, "ERROR"),
                str(exc.detail),
                _request_id(request),
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Last resort for anything not raised deliberately. The response is
        # generic on purpose: a stack trace or a database message tells an
        # attacker about the system and tells the member nothing. The request
        # id is the thread back to the server log.
        return JSONResponse(
            status_code=500,
            content=error_body(
                "INTERNAL_ERROR",
                "An unexpected error occurred while processing the request.",
                _request_id(request),
            ),
        )
