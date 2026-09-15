"""Application entry point.

Composes the modular monolith: infrastructure concerns (request identity,
payload limits, CORS, error contract) wrap the versioned API routers, which in
turn delegate to the core modules.
"""

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response

from app.api.v1 import agent, agent_handoff, auth, conversations, health, ops
from app.config import get_settings
from app.errors import error_body, register_exception_handlers
from app.modules.monitoring.service import get_metrics

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("app.startup")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Prepare the data layer before the first request.

    This only runs when `AUTO_BOOTSTRAP` is enabled (the default for local
    development). Both steps are idempotent: the schema is created if absent
    and seed rows are inserted only when missing. CI and deployments call
    `python -m app.bootstrap` as an explicit step and set AUTO_BOOTSTRAP=false.
    """
    settings = get_settings()
    if settings.auto_bootstrap:
        from app.bootstrap import create_schema, seed
        from app.db import SessionLocal

        try:
            create_schema()
            session = SessionLocal()
            try:
                seed(session)
            finally:
                session.close()
            logger.info(
                "data layer ready (%s), seeded demo accounts available",
                settings.database_engine,
            )
        except Exception as exc:  # startup must explain itself, not crash silently
            logger.error(
                "could not prepare the database: %s. "
                "Check DATABASE_URL, or run `python run.py` which selects a "
                "working database for you.",
                exc,
            )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        description=(
            "Alpha release. A free education and professional development service for "
            "military members and veterans. Modular monolith with an isolated AI "
            "Integration Module, deterministic escalation rules and asynchronous "
            "feedback analysis."
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
        # The Monitoring component observes the entry point rather than
        # reaching into the modules behind it.
        get_metrics().record_request(response.status_code)
        return response

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(conversations.router)
    app.include_router(agent.router)
    app.include_router(agent_handoff.router)
    app.include_router(ops.router)

    return app


app = create_app()
