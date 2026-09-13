"""Application entry point.

Composes the modular monolith: infrastructure concerns (request identity,
payload limits, CORS, error contract) wrap the versioned API routers, which in
turn delegate to the core modules.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response

from app.api.v1 import agent, auth, conversations, health
from app.config import get_settings
from app.errors import error_body, register_exception_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Alpha release. Modular monolith with an isolated AI Integration Module, "
            "deterministic escalation rules and asynchronous feedback analysis."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Attach a correlation id and enforce the payload size limit."""
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit():
            if int(declared) > settings.max_request_bytes:
                return JSONResponse(
                    status_code=413,
                    content=error_body(
                        "PAYLOAD_TOO_LARGE",
                        "Request payload exceeds the permitted size.",
                        request_id,
                    ),
                    headers={"X-Request-ID": request_id},
                )

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(conversations.router)
    app.include_router(agent.router)

    return app


app = create_app()
