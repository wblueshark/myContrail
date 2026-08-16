"""Basemap tiles for PNG export: fetch, cache on disk, stitch.

Mapbox's own caching guidance permits a local tile cache, so tiles are stored
under data/tilecache/{style}/{z}/{x}/{y}[@2x].png and reused. Concurrency is
capped at 4 to stay inside the provider's rate limits.

Web Mercator only. No datum shift exists here: stored data and the Mapbox
basemap are both WGS-84.
"""

from __future__ import annotations

import asyncio
import logging
import math
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from contrail.config import get_settings

log = logging.getLogger(__name__)

TILE_SIZE = 512
MAX_CONCURRENT_FETCHES = 4
FETCH_TIMEOUT_S = 10
STYLES = {"light": "light-v11", "dark": "dark-v11"}
ENDPOINT = "https://api.mapbox.com/styles/v1/mapbox/{style}/tiles/{size}/{z}/{x}/{y}{ratio}"


@dataclass(slots=True)
class Viewport:
    """Everything needed to convert a coordinate into a canvas pixel."""

    zoom: int
    center_lat: float
    center_lon: float
    width: int
    height: int

    def project(self, lat: float, lon: float) -> tuple[float, float]:
        """WGS-84 -> Web Mercator -> canvas pixel."""
        scale = TILE_SIZE * (2**self.zoom)
        wx, wy = _world(lat, lon, scale)
        cx, cy = _world(self.center_lat, self.center_lon, scale)
        return wx - cx + self.width / 2, wy - cy + self.height / 2


def _world(lat: float, lon: float, scale: float) -> tuple[float, float]:
    lat = max(-85.05112878, min(85.05112878, lat))
    x = (lon + 180.0) / 360.0 * scale
    sin_lat = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * scale
    return x, y


def fit_viewport(
    bbox: tuple[float, float, float, float], width: int, height: int, padding: float = 0.10
) -> Viewport:
    """Derive the best zoom and centre for a bounding box.

    bbox is (min_lon, min_lat, max_lon, max_lat); padding adds breathing room so
    the outermost track does not touch the frame.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    lon_span = max(max_lon - min_lon, 1e-6) * (1 + padding * 2)
    lat_span = max(max_lat - min_lat, 1e-6) * (1 + padding * 2)
    center_lon = (min_lon + max_lon) / 2
    center_lat = (min_lat + max_lat) / 2

    for zoom in range(19, -1, -1):
        scale = TILE_SIZE * (2**zoom)
        x0, y0 = _world(center_lat - lat_span / 2, center_lon - lon_span / 2, scale)
        x1, y1 = _world(center_lat + lat_span / 2, center_lon + lon_span / 2, scale)
        if abs(x1 - x0) <= width and abs(y1 - y0) <= height:
            return Viewport(zoom, center_lat, center_lon, width, height)
    return Viewport(0, center_lat, center_lon, width, height)


def _cache_path(style: str, z: int, x: int, y: int, retina: bool) -> Path:
    suffix = "@2x" if retina else ""
    return get_settings().data_dir / "tilecache" / style / str(z) / str(x) / f"{y}{suffix}.png"


def _fetch_tile(style: str, z: int, x: int, y: int, retina: bool, token: str) -> bytes | None:
    path = _cache_path(style, z, x, y, retina)
    if path.exists():
        return path.read_bytes()

    url = ENDPOINT.format(
        style=style, size=TILE_SIZE, z=z, x=x, y=y, ratio="@2x" if retina else ""
    )
    try:
        request = urllib.request.Request(
            f"{url}?access_token={token}", headers={"User-Agent": "contrail/0.1"}
        )
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_S) as response:
            data = response.read()
    except Exception as exc:  # noqa: BLE001 - a missing tile degrades, never fails
        log.warning("basemap tile fetch failed", extra={"z": z, "error": type(exc).__name__})
        return None

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


async def render_basemap(viewport: Viewport, theme: str = "light", retina: bool = False):
    """Stitch the tiles covering the viewport into one Pillow image.

    Returns a blank canvas when no Mapbox token is configured, so an export
    still succeeds with the user's own data drawn on a plain background.
    """
    from PIL import Image

    settings = get_settings()
    style = STYLES.get(theme, STYLES["light"])
    background = (245, 244, 241) if theme == "light" else (26, 27, 30)
    canvas = Image.new("RGB", (viewport.width, viewport.height), background)
    if not settings.mapbox_token:
        return canvas

    scale = TILE_SIZE * (2**viewport.zoom)
    cx, cy = _world(viewport.center_lat, viewport.center_lon, scale)
    left = cx - viewport.width / 2
    top = cy - viewport.height / 2

    x_start, x_end = int(left // TILE_SIZE), int((left + viewport.width) // TILE_SIZE)
    y_start, y_end = int(top // TILE_SIZE), int((top + viewport.height) // TILE_SIZE)
    limit = 2**viewport.zoom

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    async def one(tx: int, ty: int):
        async with semaphore:
            return tx, ty, await asyncio.to_thread(
                _fetch_tile, style, viewport.zoom, tx % limit, ty, retina, settings.mapbox_token
            )

    jobs = [
        one(tx, ty)
        for tx in range(x_start, x_end + 1)
        for ty in range(y_start, y_end + 1)
        if 0 <= ty < limit
    ]
    for tx, ty, data in await asyncio.gather(*jobs):
        if not data:
            continue
        try:
            import io

            tile = Image.open(io.BytesIO(data)).convert("RGB")
            # A @2x tile is 1024 px but covers the same 512 world units, so it
            # is resampled down before compositing.
            if tile.size != (TILE_SIZE, TILE_SIZE):
                tile = tile.resize((TILE_SIZE, TILE_SIZE), Image.Resampling.LANCZOS)
        except Exception:  # noqa: BLE001
            continue
        canvas.paste(tile, (int(tx * TILE_SIZE - left), int(ty * TILE_SIZE - top)))
    return canvas
