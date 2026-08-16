"""Local-mode security.

"It only listens on 127.0.0.1, so it is safe" is false. All four guards below
are required, and each one blocks a different real attack:

  Host header check   DNS rebinding. A malicious page rebinds its own hostname
                      to 127.0.0.1, escapes the same-origin policy and reads the
                      entire location history over the API.
  strict CORS         limits which origins the browser will hand responses to.
  X-Contrail-Client   CSRF. With no authentication there is no credential to
                      require, so a hostile page could simply issue
                      DELETE /api/v1/sources/{id} and wipe everything. A custom
                      header cannot be set by a simple cross-origin form or
                      image request without a preflight.
  local token         other processes on the same machine calling the API.
                      Nearly free, and it removes most of the local attack
                      surface.

Path traversal is handled structurally rather than by validation: absolute
paths never appear in any request. See picker.py.
"""

from __future__ import annotations

import hmac
import uuid
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from contrail.config import Settings, get_settings, resolve_local_token
from contrail.logging_config import request_id_var, user_id_var

CLIENT_HEADER = "x-contrail-client"
CLIENT_VALUE = "contrail-web"
TOKEN_HEADER = "x-contrail-token"
# Map tiles and <img> thumbnails are fetched by the browser and by mapbox-gl,
# neither of which can attach a custom header. Once the header token has been
# validated the middleware mints a cookie so those subresource requests carry
# proof too. SameSite=Strict keeps it off cross-site requests, so it grants no
# CSRF power, and writes still require the custom client header on top.
TOKEN_COOKIE = "contrail_token"

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Endpoints reachable before the frontend knows anything about the server.
PUBLIC_PATHS = {"/api/v1/health", "/api/v1/capabilities", "/docs", "/openapi.json", "/redoc"}


class HostHeaderMiddleware(BaseHTTPMiddleware):
    """Reject any request whose Host header is not a loopback name."""

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.allowed = settings.hosts
        self.enabled = settings.mode == "local"

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if self.enabled:
            host = (request.headers.get("host") or "").split(":")[0].strip().lower()
            if host and host not in self.allowed:
                # A rebound hostname lands here, which is the entire point.
                return JSONResponse(
                    {"detail": "host not allowed"}, status_code=status.HTTP_421_MISDIRECTED_REQUEST
                )
        return await call_next(request)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id so log lines can be correlated."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        token = request.headers.get("x-request-id") or uuid.uuid4().hex
        request_id_var.set(token)
        request.state.request_id = token
        response = await call_next(request)
        response.headers["x-request-id"] = token
        return response


class LocalGuardMiddleware(BaseHTTPMiddleware):
    """Enforce the local token and the anti-CSRF custom header."""

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings
        self.token = resolve_local_token(settings) if settings.mode == "local" else ""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if self.settings.mode != "local" or path in PUBLIC_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        from_header = False
        if self.token:
            header_token = request.headers.get(TOKEN_HEADER, "")
            cookie_token = request.cookies.get(TOKEN_COOKIE, "")
            # compare_digest: constant time, so the token cannot be recovered by
            # timing the rejection.
            from_header = hmac.compare_digest(header_token, self.token)
            if not from_header and not hmac.compare_digest(cookie_token, self.token):
                return JSONResponse({"detail": "invalid local token"}, status_code=401)

        # The cookie alone must never authorise a write: SameSite blocks the
        # obvious cross-site path, but the custom header is what makes a forged
        # write impossible without a preflight the browser will deny.
        if request.method in WRITE_METHODS and request.headers.get(CLIENT_HEADER) != CLIENT_VALUE:
            return JSONResponse(
                {"detail": "missing client header"}, status_code=status.HTTP_403_FORBIDDEN
            )

        response = await call_next(request)
        if from_header and TOKEN_COOKIE not in request.cookies:
            response.set_cookie(
                TOKEN_COOKIE,
                self.token,
                httponly=True,
                samesite="strict",
                path="/api",
                max_age=60 * 60 * 24 * 30,
            )
        return response


PATH_FIELDS = ("path", "directory", "root", "scan_path", "abs_path")


def reject_path_fields(payload: object | None) -> None:
    """API contract: /sources/prescan and /imports accept a pick_token ONLY.

    A request carrying a path field is rejected with 400 rather than sanitised.
    There is nothing to sanitise - the field must not exist, because a field
    that does not exist cannot be poisoned.

    The walk is recursive: `/imports` now nests an `options` object, and a check
    that only looked at the top level would leave exactly one place to hide a
    path in.
    """
    if isinstance(payload, dict):
        for field in PATH_FIELDS:
            if field in payload:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "filesystem paths are not accepted over HTTP; "
                        "use POST /fs/pick to obtain a pick_token"
                    ),
                )
        for value in payload.values():
            reject_path_fields(value)
    elif isinstance(payload, list):
        for value in payload:
            reject_path_fields(value)


async def current_user_id(request: Request) -> uuid.UUID:
    """The single local user.

    Authentication is not implemented in the MVP, but every route and every
    user_id foreign key already exists. Moving to the cloud means implementing
    this dependency, not reshaping the data model.
    """
    settings = get_settings()
    if settings.enable_auth:  # pragma: no cover - reserved for cloud mode
        raise HTTPException(status_code=501, detail="authentication is not implemented")
    from contrail.bootstrap import get_local_user_id

    user_id = await get_local_user_id()
    user_id_var.set(str(user_id))
    request.state.user_id = user_id
    return user_id
