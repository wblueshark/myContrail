"""Privacy fence regression - THE CI BLOCKING TEST.

A fence leak is the one unacceptable bug in this product, so this file asserts
the full matrix from the design: 2 policies x 3 layers = 6 combinations, none of
which may emit a coordinate inside a fence.

It also covers the two subtler failures that a naive implementation passes while
still leaking:

  the buffer must be metric      a degree-based buffer is only 384 m wide
                                 east-west in Beijing and 250 m in Oslo, so
                                 points just outside it survive the cut while
                                 the user believes a 500 m radius protected them
  break points must be jittered  an un-jittered cut leaves every endpoint
                                 exactly on the fence circle, and three of them
                                 from three exports reconstruct the centre

Skipping this test is not a pass. It requires PostGIS.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC

import pytest

pytestmark = pytest.mark.privacy

# Beijing: high enough in latitude that a degree-based buffer is visibly wrong.
FENCE_LAT, FENCE_LON = 39.9042, 116.4074
RADIUS_M = 500.0


def _meters_per_degree_lon(lat: float) -> float:
    return 111_320.0 * math.cos(math.radians(lat))


@pytest.fixture
def fenced_user(pg_conn):
    """A user with one fence and a track running straight through it."""
    user_id = uuid.uuid4()
    with pg_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO app_user (id, email, display_name) VALUES (%s, %s, 'fence-test')",
            (user_id, f"fence-{user_id}@test.invalid"),
        )
        cur.execute(
            """
            INSERT INTO geofence (user_id, kind, label, center, radius_m, jitter_seed)
            VALUES (%s, 'home', 'test home',
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, 42)
            """,
            (user_id, FENCE_LON, FENCE_LAT, RADIUS_M),
        )
    yield user_id
    with pg_conn.cursor() as cur:
        cur.execute("DELETE FROM app_user WHERE id = %s", (user_id,))


def _distance_from_fence(cur, lon: float, lat: float) -> float:
    cur.execute(
        "SELECT ST_DistanceSphere(ST_SetSRID(ST_MakePoint(%s, %s), 4326),"
        " ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
        (lon, lat, FENCE_LON, FENCE_LAT),
    )
    return cur.fetchone()[0]


def _line_through_fence(span_deg: float = 0.05) -> str:
    """An east-west line crossing the fence centre, sampled every ~50 m."""
    steps = 200
    points = []
    for i in range(steps + 1):
        lon = FENCE_LON - span_deg + (2 * span_deg) * i / steps
        points.append(f"{lon} {FENCE_LAT}")
    return "SRID=4326;LINESTRING(" + ", ".join(points) + ")"


def test_fence_buffer_is_metric_in_every_direction(pg_conn, fenced_user):
    """The buffer must be ~500 m east-west, not 384 m.

    This is the exact bug the degree conversion produced: the shortfall lands on
    the unsafe side, so points 400 m east of home were exported in the clear.
    """
    with pg_conn.cursor() as cur:
        cur.execute("SELECT contrail_fence_buffer(%s)", (fenced_user,))
        assert cur.fetchone()[0] is not None

        # East edge of the buffer.
        cur.execute(
            """
            SELECT ST_DistanceSphere(
                ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                ST_ClosestPoint(ST_Boundary(contrail_fence_buffer(%s)),
                                ST_SetSRID(ST_MakePoint(%s, %s), 4326)))
            """,
            (FENCE_LON + 0.02, FENCE_LAT, fenced_user, FENCE_LON + 0.02, FENCE_LAT),
        )
        east_gap = cur.fetchone()[0]
        east_edge_m = _meters_per_degree_lon(FENCE_LAT) * 0.02 - east_gap

    # The degree-based bug would give ~384 m here.
    assert 470 <= east_edge_m <= 530, f"east-west fence radius is {east_edge_m:.0f} m, not ~500 m"


@pytest.mark.parametrize("policy", ["remove", "blur"])
def test_tracks_contain_no_in_fence_coordinates(pg_conn, fenced_user, policy):
    """Layer 1 of 3: tracks, under both policies."""
    function = f"contrail_fence_{policy}"
    with pg_conn.cursor() as cur:
        cur.execute(
            f"SELECT ST_AsText({function}(%s::geometry, %s))",
            (_line_through_fence(), fenced_user),
        )
        wkt = cur.fetchone()[0]
        assert wkt is not None

        for lon, lat in _coords(wkt):
            distance = _distance_from_fence(cur, lon, lat)
            assert distance >= RADIUS_M - 1.0, (
                f"{policy}: a vertex survived {distance:.0f} m from the fence centre"
            )


@pytest.mark.parametrize("policy", ["remove", "blur"])
def test_places_contain_no_in_fence_coordinates(pg_conn, fenced_user, policy):
    """Layer 2 of 3: stay points."""
    function = f"contrail_fence_{policy}"
    inside = f"SRID=4326;POINT({FENCE_LON + 0.001} {FENCE_LAT})"
    with pg_conn.cursor() as cur:
        cur.execute(f"SELECT ST_AsText({function}(%s::geometry, %s))", (inside, fenced_user))
        wkt = cur.fetchone()[0]
        if wkt is None or "EMPTY" in wkt.upper():
            return  # removed entirely: the intended outcome
        for lon, lat in _coords(wkt):
            assert _distance_from_fence(cur, lon, lat) >= RADIUS_M - 1.0


@pytest.mark.parametrize("policy", ["remove", "blur"])
def test_photos_contain_no_in_fence_coordinates(pg_conn, fenced_user, policy):
    """Layer 3 of 3: photo positions."""
    function = f"contrail_fence_{policy}"
    inside = f"SRID=4326;POINT({FENCE_LON} {FENCE_LAT + 0.002})"
    with pg_conn.cursor() as cur:
        cur.execute(f"SELECT ST_AsText({function}(%s::geometry, %s))", (inside, fenced_user))
        wkt = cur.fetchone()[0]
        if wkt is None or "EMPTY" in wkt.upper():
            return
        for lon, lat in _coords(wkt):
            assert _distance_from_fence(cur, lon, lat) >= RADIUS_M - 1.0


def test_break_points_do_not_reveal_the_centre(pg_conn, fenced_user):
    """Cut ends must NOT sit on the fence circle.

    Un-jittered, every endpoint lands at exactly the radius; collect three from
    three exports and the centre follows from the circumscribed circle. Jitter
    pulls each end back by a seeded 0-30% of R, so the distances spread out.
    """
    distances = []
    with pg_conn.cursor() as cur:
        for offset in range(6):
            # Different lines through the same fence, as different exports would be.
            lat = FENCE_LAT + offset * 0.0005
            steps = 200
            points = [
                f"{FENCE_LON - 0.05 + 0.1 * i / steps} {lat}" for i in range(steps + 1)
            ]
            line = "SRID=4326;LINESTRING(" + ", ".join(points) + ")"
            cur.execute("SELECT ST_AsText(contrail_fence_remove(%s::geometry, %s))",
                        (line, fenced_user))
            wkt = cur.fetchone()[0]
            if not wkt:
                continue
            for segment in _segments(wkt):
                for lon, plat in (segment[0], segment[-1]):
                    d = _distance_from_fence(cur, lon, plat)
                    # Only the ends produced by the cut, not the line's own ends.
                    if d < RADIUS_M * 2:
                        distances.append(d)

    assert len(distances) >= 4, "expected several cut endpoints to examine"
    spread = max(distances) - min(distances)
    # Un-jittered this spread is ~0. Jitter is 0-30% of R = up to 150 m.
    assert spread > 20.0, (
        f"cut endpoints are clustered within {spread:.1f} m of one radius; "
        "three of them would locate the fence centre"
    )
    assert all(d >= RADIUS_M - 1.0 for d in distances)


def test_jitter_is_stable_across_exports(pg_conn, fenced_user):
    """The same fence and geometry must clip identically every time.

    A fresh random offset per export would let repeated exports be averaged back
    to the true circle - which is what the fixed jitter_seed prevents.
    """
    line = _line_through_fence()
    with pg_conn.cursor() as cur:
        cur.execute("SELECT ST_AsText(contrail_fence_remove(%s::geometry, %s))",
                    (line, fenced_user))
        first = cur.fetchone()[0]
        cur.execute("SELECT ST_AsText(contrail_fence_remove(%s::geometry, %s))",
                    (line, fenced_user))
        second = cur.fetchone()[0]
    assert first == second


def test_disabled_fence_is_not_applied(pg_conn, fenced_user):
    """A fence the user switched off must stop clipping - and switching it back
    on must resume clipping. Nothing else may leak in the meantime."""
    line = _line_through_fence()
    with pg_conn.cursor() as cur:
        cur.execute("UPDATE geofence SET enabled = false WHERE user_id = %s", (fenced_user,))
        cur.execute("SELECT contrail_fence_buffer(%s)", (fenced_user,))
        assert cur.fetchone()[0] is None
        cur.execute("SELECT ST_AsText(contrail_fence_remove(%s::geometry, %s))",
                    (line, fenced_user))
        assert cur.fetchone()[0] is not None  # passes through untouched

        cur.execute("UPDATE geofence SET enabled = true WHERE user_id = %s", (fenced_user,))
        cur.execute("SELECT ST_AsText(contrail_fence_remove(%s::geometry, %s))",
                    (line, fenced_user))
        for lon, lat in _coords(cur.fetchone()[0]):
            assert _distance_from_fence(cur, lon, lat) >= RADIUS_M - 1.0


def test_time_attributes_are_truncated_on_clipped_tracks():
    """Clipping geometry alone is not enough.

    A track that starts at 08:12 in a blank area and ends at 18:45 in the same
    blank area discloses both the routine and the address without a single
    coordinate being exposed.
    """
    from datetime import datetime

    from contrail.render.png import truncate_times

    exact = datetime(2024, 5, 3, 8, 12, 37, tzinfo=UTC)
    assert truncate_times(exact, clipped=False) == exact
    truncated = truncate_times(exact, clipped=True)
    assert truncated.minute % 15 == 0 and truncated.second == 0
    assert truncated <= exact


# ── helpers ───────────────────────────────────────────────
def _segments(wkt: str) -> list[list[tuple[float, float]]]:
    upper = wkt.upper()
    if upper.startswith("LINESTRING"):
        bodies = [wkt[wkt.index("(") + 1 : wkt.rindex(")")]]
    elif upper.startswith("MULTILINESTRING"):
        inner = wkt[wkt.index("(") + 1 : wkt.rindex(")")]
        bodies = [c.strip().lstrip("(").rstrip(")") for c in inner.split("),")]
    elif upper.startswith("POINT"):
        body = wkt[wkt.index("(") + 1 : wkt.rindex(")")]
        parts = body.split()
        return [[(float(parts[0]), float(parts[1]))]]
    else:
        return []

    out = []
    for body in bodies:
        points = []
        for pair in body.split(","):
            parts = pair.strip().split()
            if len(parts) >= 2:
                points.append((float(parts[0]), float(parts[1])))
        if points:
            out.append(points)
    return out


def _coords(wkt: str) -> list[tuple[float, float]]:
    return [point for segment in _segments(wkt) for point in segment]
