"""PNG composition: fetch the geometry (fenced), draw it, lay out the template.

This module is the ONLY outbound channel in the MVP, which makes it the single
privacy-fence enforcement point. Geometry arrives here already clipped by
PostGIS - the fence is applied in SQL, not in Python, so there is no path
through this file that can draw an unclipped coordinate.

Three v1.0 mistakes are corrected in the SQL and in truncate_times() below:

  1. the buffer is built with the geography form of ST_Buffer, whose radius is
     in metres. The old degree conversion made a "500 m" fence 384 m wide in
     Beijing and 250 m in Oslo - and the shortfall is on the unsafe side.
  2. break points are jittered. Un-jittered ends sit exactly on the fence
     circle: twenty exports give twenty points, and any three of them fix the
     centre to within metres.
  3. clipped tracks have their times truncated. A route that starts at 08:12
     from a blank area and ends at 18:45 in the same blank area discloses both
     the routine and the address, with no coordinate involved at all.
"""

from __future__ import annotations

import io
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from contrail.render.basemap import Viewport, fit_viewport, render_basemap

log = logging.getLogger(__name__)

# Time attributes of a clipped track are rounded to this granularity.
TIME_GRANULARITY = timedelta(minutes=15)

ATTRIBUTION = "© Mapbox © OpenStreetMap"

MODE_COLORS = {
    "walk": (0.20, 0.65, 0.42),
    "run": (0.95, 0.55, 0.15),
    "bike": (0.25, 0.60, 0.90),
    "car": (0.90, 0.35, 0.35),
    "transit": (0.55, 0.40, 0.85),
    "flight": (0.35, 0.75, 0.85),
    "unknown": (0.55, 0.55, 0.58),
}


@dataclass
class RenderScope:
    trip_ids: list[UUID] = field(default_factory=list)
    place_ids: list[UUID] = field(default_factory=list)


@dataclass
class RenderData:
    tracks: list[dict] = field(default_factory=list)
    places: list[dict] = field(default_factory=list)
    photos: list[dict] = field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None
    title: str = ""
    subtitle: str = ""
    stats_line: str = ""
    clipped: bool = False


def _fence_expr(column: str, action: str | None) -> str:
    """SQL fragment applying the chosen fence policy to a geometry column."""
    if action == "remove":
        return f"contrail_fence_remove({column}, :uid)"
    if action == "blur":
        return f"contrail_fence_blur({column}, :uid)"
    return column


def truncate_times(value: datetime | None, clipped: bool) -> datetime | None:
    """Round a clipped track's timestamps down to a 15-minute boundary.

    Clipping the geometry alone is not enough: exact start and end times of a
    daily journey through a blank area reveal both the routine and the address.
    """
    if value is None or not clipped:
        return value
    seconds = int(TIME_GRANULARITY.total_seconds())
    epoch = int(value.timestamp()) // seconds * seconds
    return datetime.fromtimestamp(epoch, tz=value.tzinfo)


async def collect(
    session: AsyncSession,
    user_id: UUID,
    scope: RenderScope,
    fence_action: str | None,
) -> RenderData:
    """Fetch every feature in scope, with the fence policy already applied."""
    params = {
        "uid": str(user_id),
        "trip_ids": [str(t) for t in scope.trip_ids] or None,
        "place_ids": [str(p) for p in scope.place_ids] or None,
    }
    data = RenderData(clipped=fence_action is not None)

    track_geom = _fence_expr("t.geom", fence_action)
    tracks = (
        await session.execute(
            text(
                f"""
                SELECT t.id, t.mode::text AS mode, t.distance_m, t.start_utc, t.end_utc,
                       ST_AsText(ST_Force2D({track_geom})) AS wkt
                  FROM track t
                 WHERE t.user_id = :uid AND NOT t.is_shadow
                   AND (CAST(:trip_ids AS uuid[]) IS NULL OR t.trip_id = ANY(:trip_ids))
                 ORDER BY t.start_utc
                """
            ),
            params,
        )
    ).all()
    for row in tracks:
        lines = _parse_wkt_lines(row.wkt)
        if not lines:
            continue
        data.tracks.append(
            {
                "mode": row.mode,
                "lines": lines,
                "distance_m": row.distance_m,
                "start_utc": truncate_times(row.start_utc, data.clipped),
                "end_utc": truncate_times(row.end_utc, data.clipped),
            }
        )

    place_geom = _fence_expr("p.centroid", fence_action)
    places = (
        await session.execute(
            text(
                f"""
                SELECT p.id, p.duration_s, coalesce(p.name, p.geo_name, p.geo_city) AS label,
                       ST_AsText({place_geom}) AS wkt
                  FROM place p
                 WHERE p.user_id = :uid
                   AND ((CAST(:trip_ids AS uuid[]) IS NULL OR p.trip_id = ANY(:trip_ids))
                     OR (CAST(:place_ids AS uuid[]) IS NOT NULL AND p.id = ANY(:place_ids)))
                """
            ),
            params,
        )
    ).all()
    for row in places:
        point = _parse_wkt_point(row.wkt)
        # A NULL geometry means the fence removed it entirely. That is the
        # intended outcome, and there is nothing left to draw.
        if point is None:
            continue
        data.places.append({"lat": point[0], "lon": point[1], "duration_s": row.duration_s})

    photo_geom = _fence_expr("ph.geom", fence_action)
    photos = (
        await session.execute(
            text(
                f"""
                SELECT ph.id, ph.thumb_key, ST_AsText({photo_geom}) AS wkt
                  FROM photo ph
                 WHERE ph.user_id = :uid AND ph.geom IS NOT NULL
                   AND (CAST(:trip_ids AS uuid[]) IS NULL OR ph.trip_id = ANY(:trip_ids))
                 ORDER BY ph.taken_at_utc
                """
            ),
            params,
        )
    ).all()
    for row in photos:
        point = _parse_wkt_point(row.wkt)
        if point is None:
            continue
        data.photos.append({"lat": point[0], "lon": point[1], "thumb_key": row.thumb_key})

    coords: list[tuple[float, float]] = []
    for track in data.tracks:
        for line in track["lines"]:
            coords.extend(line)
    coords.extend((p["lat"], p["lon"]) for p in data.places)
    coords.extend((p["lat"], p["lon"]) for p in data.photos)
    if coords:
        lats = [c[0] for c in coords]
        lons = [c[1] for c in coords]
        data.bbox = (min(lons), min(lats), max(lons), max(lats))

    summary = (
        await session.execute(
            text(
                """
                SELECT min(local_date) AS lo, max(local_date) AS hi,
                       count(*) AS n, min(title) AS title
                  FROM trip
                 WHERE user_id = :uid AND (CAST(:trip_ids AS uuid[]) IS NULL OR id = ANY(:trip_ids))
                """
            ),
            params,
        )
    ).first()
    if summary and summary.n:
        data.title = summary.title if summary.n == 1 else f"{summary.lo} – {summary.hi}"
        data.subtitle = f"{summary.n} days" if summary.n > 1 else str(summary.lo)

    known = [t["distance_m"] for t in data.tracks if t["distance_m"] is not None]
    unknown = sum(1 for t in data.tracks if t["distance_m"] is None)
    total_km = sum(known) / 1000 if known else 0.0
    data.stats_line = f"{total_km:,.0f} km · {len(data.places)} places"
    if unknown:
        # Honest reporting: unknown distance is never folded in as zero.
        data.stats_line += f" · {unknown} segments of unknown distance"
    return data


def _parse_wkt_point(wkt: str | None) -> tuple[float, float] | None:
    """POINT WKT -> (lat, lon), or None when nothing survived the fence.

    A geometry lying wholly inside a fence comes back as `POINT EMPTY`, which
    has no parentheses at all. That is the intended outcome of clipping, so it
    has to parse as "nothing here" rather than raise.
    """
    if not wkt or not wkt.upper().startswith("POINT") or "(" not in wkt:
        return None
    body = wkt[wkt.index("(") + 1 : wkt.rindex(")")].strip()
    parts = body.split()
    if len(parts) < 2:
        return None
    return float(parts[1]), float(parts[0])


def _parse_wkt_lines(wkt: str | None) -> list[list[tuple[float, float]]]:
    """LINESTRING / MULTILINESTRING -> list of [(lat, lon), ...].

    Returns [] for the EMPTY forms, which is what a fully clipped track becomes.
    """
    if not wkt or "(" not in wkt:
        return []
    upper = wkt.upper()
    if upper.startswith("LINESTRING"):
        chunks = [wkt[wkt.index("(") + 1 : wkt.rindex(")")]]
    elif upper.startswith("MULTILINESTRING"):
        inner = wkt[wkt.index("(") + 1 : wkt.rindex(")")]
        chunks = [c.strip().lstrip("(").rstrip(")") for c in inner.split("),")]
    else:
        return []

    lines: list[list[tuple[float, float]]] = []
    for chunk in chunks:
        points: list[tuple[float, float]] = []
        for pair in chunk.split(","):
            parts = pair.strip().split()
            if len(parts) >= 2:
                points.append((float(parts[1]), float(parts[0])))
        if len(points) >= 2:
            lines.append(points)
    return lines


def draw_features(surface_size: tuple[int, int], viewport: Viewport, data: RenderData) -> bytes:
    """Draw tracks and stay points with cairo. Returns PNG bytes (RGBA)."""
    import cairo

    width, height = surface_size
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    ctx.set_antialias(cairo.ANTIALIAS_BEST)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)

    for track in data.tracks:
        color = MODE_COLORS.get(track["mode"], MODE_COLORS["unknown"])
        for line in track["lines"]:
            pixels = [viewport.project(lat, lon) for lat, lon in line]
            if len(pixels) < 2:
                continue
            # White casing first, so the route stays legible over any basemap.
            _stroke(ctx, pixels, (1, 1, 1), 5.0, 0.85)
            _stroke(ctx, pixels, color, 2.6, 0.95)

    for place in data.places:
        x, y = viewport.project(place["lat"], place["lon"])
        # Radius scales with the log of dwell time: a 12-hour stay must not be
        # 48 times the size of a 15-minute one.
        duration = max(place.get("duration_s") or 0, 60)
        radius = 3.0 + 2.4 * math.log10(duration / 60 + 1) * 2
        ctx.set_source_rgba(0.10, 0.12, 0.16, 0.35)
        ctx.arc(x, y, radius, 0, 2 * math.pi)
        ctx.fill()
        ctx.set_source_rgba(1, 1, 1, 0.95)
        ctx.set_line_width(1.6)
        ctx.arc(x, y, radius, 0, 2 * math.pi)
        ctx.stroke()

    buffer = io.BytesIO()
    surface.write_to_png(buffer)
    return buffer.getvalue()


def _stroke(ctx, pixels, color, line_width: float, alpha: float) -> None:
    ctx.set_source_rgba(color[0], color[1], color[2], alpha)
    ctx.set_line_width(line_width)
    ctx.move_to(*pixels[0])
    for x, y in pixels[1:]:
        ctx.line_to(x, y)
    ctx.stroke()


async def render(
    session: AsyncSession,
    user_id: UUID,
    scope: RenderScope,
    template: str = "map",
    width: int = 1080,
    height: int = 1920,
    theme: str = "light",
    fence_action: str | None = None,
) -> bytes:
    """Render one PNG. The fence policy is applied while collecting geometry."""
    from PIL import Image

    data = await collect(session, user_id, scope, fence_action)
    if data.bbox is None:
        raise ValueError("nothing to render: the selection contains no geometry")

    header = 150 if template == "poster" else 0
    footer = 110 if template in {"poster", "collage"} else 0
    grid = 360 if template == "collage" and data.photos else 0
    map_height = max(200, height - header - footer - grid)

    viewport = fit_viewport(data.bbox, width, map_height)
    background = (255, 255, 255) if theme == "light" else (18, 19, 22)
    canvas = Image.new("RGB", (width, height), background)

    basemap = await render_basemap(viewport, theme=theme)
    canvas.paste(basemap, (0, header))

    overlay = Image.open(io.BytesIO(draw_features((width, map_height), viewport, data))).convert(
        "RGBA"
    )
    canvas.paste(overlay, (0, header), overlay)

    _draw_photos(canvas, viewport, data, header)

    if template == "poster":
        _draw_poster_chrome(canvas, data, theme, header, footer)
    if template == "collage" and data.photos:
        _draw_photo_grid(canvas, data, y=height - footer - grid, height=grid, width=width)

    _draw_attribution(canvas, theme)

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _draw_photos(canvas, viewport: Viewport, data: RenderData, offset_y: int) -> None:
    """Thumbnails on the map, thinned so they do not pile up."""
    from PIL import Image

    from contrail.storage import get_storage

    if not data.photos:
        return
    storage = get_storage()
    placed: list[tuple[float, float]] = []
    size = 56
    for photo in data.photos:
        if not photo.get("thumb_key"):
            continue
        x, y = viewport.project(photo["lat"], photo["lon"])
        if any(abs(x - px) < size and abs(y - py) < size for px, py in placed):
            continue  # overlap avoidance
        try:
            thumb = Image.open(io.BytesIO(storage.get(photo["thumb_key"]))).convert("RGB")
        except Exception:  # noqa: BLE001
            continue
        thumb.thumbnail((size, size), Image.Resampling.LANCZOS)
        frame = Image.new("RGB", (thumb.width + 4, thumb.height + 4), (255, 255, 255))
        frame.paste(thumb, (2, 2))
        canvas.paste(frame, (int(x - frame.width / 2), int(offset_y + y - frame.height / 2)))
        placed.append((x, y))
        if len(placed) >= 40:
            break


def _font(size: int):
    from PIL import ImageFont

    for candidate in (
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_poster_chrome(canvas, data: RenderData, theme: str, header: int, footer: int) -> None:
    from PIL import ImageDraw

    draw = ImageDraw.Draw(canvas)
    fg = (24, 25, 28) if theme == "light" else (238, 238, 240)
    bg = (255, 255, 255) if theme == "light" else (18, 19, 22)

    draw.rectangle([0, 0, canvas.width, header], fill=bg)
    draw.text((48, 40), data.title or "Contrail", font=_font(46), fill=fg)
    draw.text((48, 100), data.subtitle, font=_font(24), fill=(fg[0], fg[1], fg[2]))

    draw.rectangle([0, canvas.height - footer, canvas.width, canvas.height], fill=bg)
    draw.text((48, canvas.height - footer + 34), data.stats_line, font=_font(26), fill=fg)


def _draw_photo_grid(canvas, data: RenderData, y: int, height: int, width: int) -> None:
    from PIL import Image

    from contrail.storage import get_storage

    storage = get_storage()
    columns = max(3, min(6, int(width / 220)))
    cell = width // columns
    rows = max(1, height // cell)
    # Even sampling across time rather than the first N, so a collage of a
    # ten-day trip is not entirely the first afternoon.
    photos = [p for p in data.photos if p.get("thumb_key")]
    step = max(1, len(photos) // (columns * rows)) if photos else 1
    chosen = photos[::step][: columns * rows]

    for index, photo in enumerate(chosen):
        try:
            thumb = Image.open(io.BytesIO(storage.get(photo["thumb_key"]))).convert("RGB")
        except Exception:  # noqa: BLE001
            continue
        thumb = thumb.resize((cell - 6, cell - 6), Image.Resampling.LANCZOS)
        cx = (index % columns) * cell + 3
        cy = y + (index // columns) * cell + 3
        canvas.paste(thumb, (cx, cy))


def _draw_attribution(canvas, theme: str) -> None:
    """Attribution is not optional and has no toggle."""
    from PIL import Image, ImageDraw

    font = _font(20)
    draw = ImageDraw.Draw(canvas)
    box = draw.textbbox((0, 0), ATTRIBUTION, font=font)
    pad = 8
    w, h = box[2] - box[0] + pad * 2, box[3] - box[1] + pad * 2
    strip = Image.new("RGBA", (w, h), (0, 0, 0, 110) if theme == "light" else (255, 255, 255, 60))
    canvas.paste(strip, (canvas.width - w - 12, canvas.height - h - 12), strip)
    draw.text(
        (canvas.width - w - 12 + pad, canvas.height - h - 12 + pad),
        ATTRIBUTION,
        font=font,
        fill=(255, 255, 255) if theme == "light" else (20, 20, 20),
    )
