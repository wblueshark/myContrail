"""HTTP API. Everything is mounted under /api/v1."""

from fastapi import APIRouter

from contrail.api import (
    commute,
    corrections,
    exports,
    imports,
    organize,
    overview,
    query,
    settings,
    system,
    tiles,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system.router)
api_router.include_router(imports.router)
api_router.include_router(query.router)
api_router.include_router(overview.router)
api_router.include_router(tiles.router)
api_router.include_router(organize.router)
api_router.include_router(commute.router)
api_router.include_router(settings.router)
api_router.include_router(exports.router)
api_router.include_router(corrections.router)

__all__ = ["api_router"]
