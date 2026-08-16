"""Development environment verification.

This does not merely check that packages import. Each item verifies that a
capability the design actually depends on genuinely holds on this machine.
Item names reference the defect IDs recorded in docs/working/design-review-r2.md.

Usage:  conda run -n py312 python backend/scripts/verify_env.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OK, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
results: list[tuple[str, bool, str]] = []


def check(name: str, fn):
    try:
        detail = fn()
        results.append((name, True, detail or ""))
        print(f"  {OK}  {name}  {detail or ''}")
    except Exception as e:  # noqa: BLE001
        results.append((name, False, str(e)))
        print(f"  {FAIL}  {name}  ->  {type(e).__name__}: {e}")


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.split("#", 1)[0].strip()
    return env


ENV = load_env()

print("\n\033[1m-- 1. PostGIS: the architectural linchpin ------------------\033[0m")

import psycopg  # noqa: E402

DSN = ENV.get("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://")
conn = psycopg.connect(DSN)
conn.autocommit = True
cur = conn.cursor()


def pg_version():
    cur.execute("SHOW server_version")
    v = cur.fetchone()[0]
    cur.execute("SELECT postgis_lib_version()")
    return f"PostgreSQL {v} - PostGIS {cur.fetchone()[0]}"


def extensions():
    cur.execute("SELECT extname FROM pg_extension ORDER BY 1")
    got = {r[0] for r in cur.fetchall()}
    need = {"postgis", "pg_trgm", "pgcrypto"}
    if missing := need - got:
        raise RuntimeError(f"missing extensions: {missing}")
    return " ".join(sorted(need))


def geofence_buffer_correctness():
    """D-05: geofence buffers must use the geography variant of ST_Buffer.

    The original spec used radius_m / 111320.0, which is a latitude-direction
    degree conversion. At higher latitudes the east-west extent shrinks by
    cos(lat), so the fence protects far less ground than the user believes.

    Method: take the buffer polygon's eastern half-width in degrees and convert
    it back to metres at that latitude.
    """
    cur.execute("""
        WITH c AS (SELECT ST_SetSRID(ST_MakePoint(116.40, 39.90), 4326) AS g),
        deg_buf AS (SELECT ST_Buffer(c.g::geometry, 500.0/111320.0) AS b FROM c),
        -- the ::geography cast is mandatory; without it this buffers 500 DEGREES
        geo_buf AS (SELECT ST_Buffer(c.g::geography, 500)::geometry AS b FROM c)
        SELECT
          (ST_XMax(deg_buf.b) - 116.40) * 111320.0 * cos(radians(39.90)),
          (ST_XMax(geo_buf.b) - 116.40) * 111320.0 * cos(radians(39.90))
        FROM deg_buf, geo_buf
    """)
    wrong, right = cur.fetchone()
    if not (480 <= right <= 520):
        raise RuntimeError(f"geography buffer spans {right:.0f} m east-west, expected ~500 m")
    return (
        f"a 500 m fence at Beijing latitude: degree conversion actually covers only "
        f"\033[31m{wrong:.0f} m\033[0m east-west (this is the D-05 leak); "
        f"geography variant {right:.0f} m"
    )


def mvt():
    """ADR-16: PostGIS ST_AsMVT is the rendering backbone."""
    import math

    z, lon, lat = 12, 139.767, 35.681
    n = 2**z
    xt = int((lon + 180.0) / 360.0 * n)
    yt = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    cur.execute(f"""
        WITH b AS (SELECT ST_TileEnvelope({z}, {xt}, {yt}) AS geom),
        g AS (SELECT ST_AsMVTGeom(
                ST_Transform(ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326), 3857),
                (SELECT geom FROM b), 4096, 64, true) AS geom, 1 AS id)
        SELECT length(ST_AsMVT(g.*, 'places', 4096, 'geom')) FROM g
    """)
    size = cur.fetchone()[0]
    if not size:
        raise RuntimeError("empty tile - geometry did not fall inside the tile envelope")
    return f"tile z{z}/{xt}/{yt} is {size} bytes with 1 feature"


# Test fixture for the CJK check below. These are data, not prose: the whole
# point is that a Japanese place name cannot be prefix-matched by to_tsvector.
CJK_HAYSTACK = "京都市, 京都府, 日本"  # "Kyoto City, Kyoto Pref., Japan"
CJK_NEEDLE = "京都"  # "Kyoto"


def cjk_search():
    """D-20: the 'simple' text search config does not segment CJK.

    Searching the two-character prefix of a longer Japanese place name finds
    nothing, which breaks place search across the product's main region.
    """
    cur.execute(
        "SELECT to_tsvector('simple', %s) @@ to_tsquery('simple', %s)",
        (CJK_HAYSTACK, CJK_NEEDLE),
    )
    ts = cur.fetchone()[0]
    cur.execute("SELECT %s ILIKE ('%%' || %s || '%%')", (CJK_HAYSTACK, CJK_NEEDLE))
    trgm = cur.fetchone()[0]
    if ts:
        return "to_tsvector matched unexpectedly - re-check this assumption"
    if not trgm:
        raise RuntimeError("pg_trgm / ILIKE also failed to match")
    return "to_tsvector cannot prefix-match CJK (confirms D-20); pg_trgm ILIKE matches"


def geometry_index_usable():
    """D-12: `geography && geometry` forces an implicit cast that disables the
    GiST index, turning every tile request into a sequential scan. That is why
    every spatial column is geometry(4326).
    """
    cur.execute("""
        CREATE TEMP TABLE _probe(id serial, geom geometry(Point,4326));
        INSERT INTO _probe(geom)
          SELECT ST_SetSRID(ST_MakePoint(139.7+random()/100, 35.6+random()/100),4326)
          FROM generate_series(1,2000);
        CREATE INDEX ON _probe USING GIST(geom);
        ANALYZE _probe;
    """)
    # NOTE: SET LOCAL is a no-op under autocommit, so use plain SET.
    cur.execute("SET enable_seqscan = off")
    cur.execute("""
        EXPLAIN (FORMAT JSON)
        SELECT count(*) FROM _probe
        WHERE geom && ST_MakeEnvelope(139.70,35.60,139.71,35.61,4326)
    """)
    plan = str(cur.fetchone()[0])
    cur.execute("SET enable_seqscan = on")
    if "Index" not in plan:
        raise RuntimeError("GiST index unused even with sequential scans disabled")
    return "&& on a geometry column uses the GiST index"


check("connection and versions", pg_version)
check("required extensions", extensions)
check("geofence buffer correctness (D-05)", geofence_buffer_correctness)
check("vector tiles ST_AsMVT (ADR-16)", mvt)
check("CJK place-name search (D-20)", cjk_search)
check("geometry + GiST index (D-12)", geometry_index_usable)

print("\n\033[1m-- 2. Redis / task queue ----------------------------------\033[0m")


def redis_ok():
    import redis as r

    c = r.from_url(ENV.get("REDIS_URL", "redis://localhost:6379/0"))
    c.ping()
    return f"Redis {c.info()['redis_version']}"


check("Redis connection", redis_ok)
check("ARQ import", lambda: f"arq {__import__('arq').VERSION}")

print("\n\033[1m-- 3. Parser dependencies ---------------------------------\033[0m")


def heic():
    import pillow_heif

    pillow_heif.register_heif_opener()
    return f"pillow-heif {pillow_heif.__version__} (HEIC is the iPhone default)"


def draft_mode():
    """D-22: Image.draft() decodes only the DCT scale actually needed.

    Without it the "100k photos in 15 min" target is off by an order of magnitude.
    """
    import io
    import time

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4000, 3000), (120, 140, 160)).save(buf, "JPEG", quality=85)

    buf.seek(0)
    t = time.perf_counter()
    Image.open(buf).load()
    full = (time.perf_counter() - t) * 1000

    buf.seek(0)
    t = time.perf_counter()
    im = Image.open(buf)
    im.draft("RGB", (512, 512))
    im.load()
    drafted = (time.perf_counter() - t) * 1000
    return (
        f"full decode {full:.0f} ms -> draft() {drafted:.0f} ms "
        f"({full / drafted:.1f}x), size {im.size}"
    )


def cairo_aa():
    """D-27: Pillow's ImageDraw.line() has no antialiasing.

    Exported images would show hard stair-stepped edges, which directly
    determines whether the output is worth sharing.
    """
    import cairo

    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 64, 64)
    ctx = cairo.Context(surf)
    ctx.set_antialias(cairo.ANTIALIAS_BEST)
    ctx.set_line_width(3)
    ctx.move_to(4, 4)
    ctx.line_to(60, 40)
    ctx.stroke()
    data = bytes(surf.get_data())
    shades = len({data[i + 3] for i in range(0, len(data), 4)})
    if shades < 3:
        raise RuntimeError("no intermediate alpha steps - antialiasing not active")
    return f"pycairo {cairo.version} - {shades} alpha steps detected"


def tzf():
    from timezonefinder import TimezoneFinder

    tf = TimezoneFinder()
    tokyo = tf.timezone_at(lat=35.681, lng=139.767)
    ny = tf.timezone_at(lat=40.7128, lng=-74.0060)
    if tokyo != "Asia/Tokyo" or ny != "America/New_York":
        raise RuntimeError(f"unexpected result: {tokyo} / {ny}")
    return f"Tokyo -> {tokyo}, New York -> {ny} (basis for cross-timezone day splitting)"


def exif_real():
    """Verify the EXIF chain against a real sample photo.

    Skips automatically once the sample directory is removed.
    """
    import exifread

    photo_dir = ROOT / "Sample" / "Photo"
    photos = sorted(photo_dir.glob("*.jpeg")) if photo_dir.exists() else []
    if not photos:
        return "skipped - Sample/Photo not present"
    with open(photos[0], "rb") as f:
        tags = exifread.process_file(f, details=False)
    # exifread's tag names differ from the EXIF specification:
    #   spec GPSDateStamp (0x001D)         -> exifread "GPS GPSDate"
    #   spec GPSHPositioningError (0x001F) -> exifread leaves it UNNAMED,
    #                                         reachable only as "GPS Tag 0x001F"
    # That last one is the accuracy field, which is exactly what makes photos
    # more trustworthy than Google timeline points (those carry no accuracy).
    need = ["EXIF DateTimeOriginal", "EXIF OffsetTimeOriginal", "GPS GPSLatitude", "GPS GPSDate"]
    if missing := [t for t in need if t not in tags]:
        raise RuntimeError(f"missing tags: {missing}")
    acc = tags.get("GPS Tag 0x001F")
    acc_s = f"accuracy {float(acc.values[0]):.1f} m" if acc else "no accuracy field"
    return f"{photos[0].name[:8]}... time/offset/GPS/UTC all present - {acc_s}"


def ijson_stream():
    import io

    import ijson

    data = io.BytesIO(
        b'[{"startTime":"2026-01-01T00:00:00Z","timelinePath":[{"point":"geo:35.68,139.76"}]}]'
    )
    n = sum(1 for _ in ijson.items(data, "item"))
    return f"streamed {n} record(s) - the only viable route for GB-scale Google exports"


check("HEIC support", heic)
check("JPEG DCT-scaled decode (D-22)", draft_mode)
check("vector drawing antialiasing (D-27)", cairo_aa)
check("offline timezone lookup", tzf)
check("EXIF against real sample", exif_real)
check("ijson streaming", ijson_stream)
check("FIT parser", lambda: f"fitparse {__import__('fitparse').__version__}")
check("lxml (GPX/TCX)", lambda: f"lxml {__import__('lxml.etree', fromlist=['etree']).__version__}")

print("\n\033[1m-- 4. Web framework ---------------------------------------\033[0m")
check("FastAPI", lambda: f"fastapi {__import__('fastapi').__version__}")
check("SQLAlchemy", lambda: f"sqlalchemy {__import__('sqlalchemy').__version__}")
check("GeoAlchemy2", lambda: f"geoalchemy2 {__import__('geoalchemy2').__version__}")
check("Alembic", lambda: f"alembic {__import__('alembic').__version__}")

print("\n\033[1m-- 5. Configuration ---------------------------------------\033[0m")


def mapbox_token():
    t = ENV.get("VITE_MAPBOX_TOKEN", "")
    if not t or t.startswith("pk.xxx"):
        raise RuntimeError("not set - basemap, geocoding and PNG export all depend on it")
    return f"configured ({t[:8]}...)"


def directory_picker():
    """v2.3 replaced the scan-root allowlist with the native directory picker.

    There is no allowlist to validate any more, and that is the point: the photo
    directory is chosen in the host's own file dialog and referenced by a
    one-shot token, so no path ever reaches an HTTP request and traversal is
    structurally impossible rather than filtered. Two things have to hold
    instead - no scan root is persisted anywhere, and the native picker actually
    works on this host, because without it photo import has no entry point.
    """
    import platform
    import shutil

    if ENV.get("CONTRAIL_ALLOWED_SCAN_ROOTS"):
        raise RuntimeError(
            "CONTRAIL_ALLOWED_SCAN_ROOTS is set, but v2.3 removed it. "
            "The setting is ignored - delete it from .env so it cannot mislead"
        )
    if platform.system() != "Darwin":
        raise RuntimeError("no native directory picker on this host - photo import is unavailable")
    if shutil.which("osascript") is None:
        raise RuntimeError("osascript not found - the native directory picker cannot open")
    return "native picker available, no scan root persisted"


def sample_ignored():
    import subprocess

    r = subprocess.run(["git", "check-ignore", "Sample/"], cwd=ROOT, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("Sample/ is NOT gitignored - real location history could be committed")
    return "Sample/ is gitignored"


check("Mapbox token", mapbox_token)
check("native directory picker (v2.3)", directory_picker)
check("real data untracked by git", sample_ignored)

cur.close()
conn.close()

passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"\n\033[1m{'-' * 58}\033[0m")
print(f"  \033[1m{passed}/{total} checks passed\033[0m")
if passed < total:
    print("\n  Failed:")
    for name, ok, detail in results:
        if not ok:
            print(f"    {FAIL}  {name}: {detail}")
print()
sys.exit(0 if passed == total else 1)
