"""Application entry point.

    uvicorn contrail.main:app --host 127.0.0.1 --port 8000 --reload

Middleware execution order is the reverse of registration, so the stack that
actually runs is:

    HostHeader  ->  CORS  ->  LocalGuard  ->  RequestContext  ->  routes

Host first, because a rebound hostname must be rejected before anything else
looks at the request. CORS next, so a preflight is answered without needing the
local token. LocalGuard after that, so every real request carries the token and
the anti-CSRF header.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request

from contrail import __version__
from contrail.api import api_router
from contrail.config import get_settings, resolve_local_token
from contrail.db import dispose_engine
from contrail.logging_config import configure_logging
from contrail.parsers.base import UnknownFormatError
from contrail.security import (
    CLIENT_HEADER,
    TOKEN_HEADER,
    HostHeaderMiddleware,
    LocalGuardMiddleware,
    RequestContextMiddleware,
)

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()
    if settings.mode == "local":
        token = resolve_local_token(settings)
        log.info(
            "contrail started",
            extra={
                "mode": settings.mode,
                "data_dir": str(settings.data_dir),
                "token_source": "env" if settings.local_token else "~/.contrail/token",
                "token_len": len(token),
            },
        )
    try:
        from contrail.bootstrap import get_local_user_id

        await get_local_user_id()
    except Exception as exc:  # noqa: BLE001 - the API must still serve /health
        log.error("bootstrap failed; is the database migrated?", extra={"error": str(exc)})
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Contrail",
        version=__version__,
        description="Personal location-history aggregation and visualization.",
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(LocalGuardMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        # A strict allowlist, never "*": with no authentication there is no
        # credential to withhold, so the origin check is the only gate.
        allow_origins=settings.origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["content-type", CLIENT_HEADER, TOKEN_HEADER, "x-request-id"],
        expose_headers=["x-request-id"],
        max_age=600,
    )
    app.add_middleware(HostHeaderMiddleware, settings=settings)

    app.include_router(api_router)

    @app.exception_handler(UnknownFormatError)
    async def unknown_format(_: Request, exc: UnknownFormatError) -> JSONResponse:
        """An unrecognised file is reported with its sample, never skipped (P6)."""
        return JSONResponse(
            status_code=422,
            content={"detail": {"error": str(exc), "sample": str(exc.sample)}},
        )

    return app


app = create_app()
