"""System and authentication routes.

The auth routes are reserved, not implemented: they return 501 so the shape of
the API does not change when cloud mode arrives. GET /auth/me returns the fixed
local identity, which is what the frontend needs today.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from contrail import picker
from contrail.config import CAPABILITIES, get_settings
from contrail.db import get_session
from contrail.schemas import Capabilities
from contrail.security import current_user_id

router = APIRouter(tags=["system"])


@router.get("/capabilities", response_model=Capabilities)
async def capabilities() -> Capabilities:
    """What this deployment can do. The frontend renders from this.

    A capability that is off means the UI does not render the entry point at
    all - never an entry point that errors when clicked.
    """
    settings = get_settings()
    caps = dict(CAPABILITIES[settings.mode])
    # Declared support is not enough: the native chooser needs a GUI session on
    # this host. Without it, photo import is hidden rather than broken.
    if caps.get("directory_picker") == "native" and not picker.picker_available():
        caps["directory_picker"] = None
        caps["scan_local_path"] = False
    return Capabilities(
        mode=settings.mode,
        scan_local_path=bool(caps["scan_local_path"]),
        directory_picker=caps["directory_picker"],
        serve_original=bool(caps["serve_original"]),
        multi_user=bool(caps["multi_user"]),
        sharing=bool(caps["sharing"]),
        geocoding_enabled=settings.geocoding_enabled,
        mapbox_token_configured=bool(settings.mapbox_token),
    )


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    checks: dict[str, str] = {}
    try:
        version = (await session.execute(text("SELECT postgis_lib_version()"))).scalar_one()
        checks["postgis"] = version
    except Exception as exc:  # noqa: BLE001
        checks["postgis"] = f"error: {type(exc).__name__}"
    return {"status": "ok" if "error" not in checks.get("postgis", "") else "degraded", **checks}


@router.get("/auth/me")
async def me(user_id=Depends(current_user_id)) -> dict:
    return {"id": str(user_id), "display_name": "Local", "auth": "disabled"}


@router.post("/auth/register", status_code=501)
async def register() -> None:
    raise HTTPException(status_code=501, detail="registration is not implemented in the MVP")


@router.post("/auth/login", status_code=501)
async def login() -> None:
    raise HTTPException(status_code=501, detail="login is not implemented in the MVP")


@router.post("/auth/logout", status_code=501)
async def logout() -> None:
    raise HTTPException(status_code=501, detail="logout is not implemented in the MVP")
