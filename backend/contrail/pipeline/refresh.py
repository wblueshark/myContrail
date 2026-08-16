"""Post-import passes: anchors, commute detection, fence suggestions, geocoding.

These run after the derived layer is in place. All of them are recomputable from
scratch, so each pass deletes its own output and rebuilds it.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from contrail.models import CommuteOD, Geofence, PlaceAnchor
from contrail.pipeline import anchors as anchor_lib
from contrail.pipeline import commute as commute_lib
from contrail.pipeline.trips import COMMUTE_TITLE

log = logging.getLogger(__name__)


async def refresh_anchors(session: AsyncSession, user_id: UUID) -> dict:
    """Rebuild place_anchor from every Place, then label home and work."""
    rows = (
        await session.execute(
            text(
                """
                SELECT id, ST_Y(centroid) AS lat, ST_X(centroid) AS lon,
                       start_utc, end_utc, tz_name, google_place_id, geo_name
                FROM place
                WHERE user_id = :uid
                ORDER BY start_utc
                """
            ),
            {"uid": str(user_id)},
        )
    ).all()
    if not rows:
        await session.execute(delete(PlaceAnchor).where(PlaceAnchor.user_id == user_id))
        return {"anchors": 0}

    semantic = await _semantic_types(session, user_id)
    visits = [
        anchor_lib.VisitRecord(
            lat=r.lat,
            lon=r.lon,
            start_utc=r.start_utc,
            end_utc=r.end_utc,
            tz_name=r.tz_name,
            google_place_id=r.google_place_id,
            semantic_type=semantic.get(str(r.id)),
            place_id=str(r.id),
        )
        for r in rows
    ]

    built = anchor_lib.build_anchors(visits)
    anchor_lib.infer_home_work(built)

    # place.anchor_id is ON DELETE SET NULL, so wiping anchors cannot take
    # Places with it.
    await session.execute(delete(PlaceAnchor).where(PlaceAnchor.user_id == user_id))
    await session.flush()

    for anchor in built:
        record = PlaceAnchor(
            user_id=user_id,
            centroid=f"SRID=4326;POINT({anchor.lon} {anchor.lat})",
            radius_m=anchor.radius_m,
            visit_count=anchor.visit_count,
            first_visit_utc=anchor.first_visit_utc,
            last_visit_utc=anchor.last_visit_utc,
            total_duration_s=anchor.total_duration_s,
            hour_histogram=anchor.hour_histogram,
            weekday_ratio=anchor.weekday_ratio,
            kind=anchor.kind,
            kind_source=anchor.kind_source,
        )
        session.add(record)
        await session.flush()
        if anchor.member_place_ids:
            await session.execute(
                text("UPDATE place SET anchor_id = :aid WHERE id = ANY(:ids)"),
                {"aid": str(record.id), "ids": anchor.member_place_ids},
            )

    return {"anchors": len(built)}


async def _semantic_types(session: AsyncSession, user_id: UUID) -> dict[str, str]:
    """Recover Google's semanticType labels for Places that came from a `visit`.

    Places store the declared place name and google_place_id; the semantic type
    is inferred back from the geofence-relevant labels stored in stats. When the
    label is absent the anchor falls back to the statistical heuristic, which is
    exactly the designed behaviour for the path era.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT id::text AS id, geo_source, geo_name
                FROM place
                WHERE user_id = :uid AND google_place_id IS NOT NULL
                """
            ),
            {"uid": str(user_id)},
        )
    ).all()
    return {r.id: r.geo_name for r in rows if r.geo_name in {"Home", "Work"}}


async def refresh_commute(session: AsyncSession, user_id: UUID) -> dict:
    """Detect commute OD pairs and mark the tracks that belong to them.

    Cold-start guard: with fewer than 30 workdays of data the detector does not
    run at all and the UI says so. Two months of holiday data WILL hit this
    branch, and that is the correct answer, not a failure.
    """
    workdays = (
        await session.execute(
            text(
                """
                SELECT count(DISTINCT local_date) FROM trip
                 WHERE user_id = :uid AND EXTRACT(ISODOW FROM local_date) < 6
                """
            ),
            {"uid": str(user_id)},
        )
    ).scalar_one()

    await session.execute(
        text("UPDATE track SET is_commute = false, commute_od_id = NULL WHERE user_id = :uid"),
        {"uid": str(user_id)},
    )
    await session.execute(delete(CommuteOD).where(CommuteOD.user_id == user_id))
    await session.execute(
        text("UPDATE trip SET commute_class = 'none' WHERE user_id = :uid"), {"uid": str(user_id)}
    )

    if workdays < commute_lib.MIN_WORKDAYS:
        return {
            "ran": False,
            "reason": "cold_start",
            "workdays": int(workdays),
            "required_workdays": commute_lib.MIN_WORKDAYS,
        }

    # A leg is a Track whose ends coincide with two anchored Places.
    rows = (
        await session.execute(
            text(
                """
                SELECT t.id::text            AS track_id,
                       pa_from.id::text      AS from_anchor,
                       pa_to.id::text        AS to_anchor,
                       t.start_utc,
                       p_from.tz_name        AS tz_name,
                       t.distance_m,
                       t.duration_s,
                       ST_AsText(ST_Simplify(t.geom, 0.0005)) AS wkt
                  FROM track t
                  JOIN place p_from
                    ON p_from.user_id = t.user_id
                   AND p_from.end_utc BETWEEN t.start_utc - interval '5 minutes'
                                          AND t.start_utc + interval '5 minutes'
                  JOIN place p_to
                    ON p_to.user_id = t.user_id
                   AND p_to.start_utc BETWEEN t.end_utc - interval '5 minutes'
                                          AND t.end_utc + interval '5 minutes'
                  JOIN place_anchor pa_from ON pa_from.id = p_from.anchor_id
                  JOIN place_anchor pa_to   ON pa_to.id   = p_to.anchor_id
                 WHERE t.user_id = :uid AND NOT t.is_shadow
                """
            ),
            {"uid": str(user_id)},
        )
    ).all()

    legs = [
        commute_lib.CommuteLeg(
            track_id=r.track_id,
            from_anchor=r.from_anchor,
            to_anchor=r.to_anchor,
            depart_utc=r.start_utc,
            tz_name=r.tz_name,
            path=_wkt_points(r.wkt),
            distance_m=r.distance_m,
            duration_s=r.duration_s or 0,
        )
        for r in rows
    ]

    home_work = {
        str(row[0])
        for row in (
            await session.execute(
                select(PlaceAnchor.id).where(
                    PlaceAnchor.user_id == user_id, PlaceAnchor.kind.in_(["home", "work"])
                )
            )
        ).all()
    }

    results = commute_lib.detect_commute_ods(legs, home_work, workday_count=int(workdays))
    for od in results:
        record = CommuteOD(
            user_id=user_id,
            from_anchor_id=od.from_anchor,
            to_anchor_id=od.to_anchor,
            occurrence=od.occurrence,
            weekday_ratio=od.weekday_ratio,
            depart_hour_mean=od.depart_hour_mean,
            depart_hour_circstd=od.depart_hour_circstd,
            path_jaccard=od.path_jaccard,
            evidence=od.evidence,
        )
        session.add(record)
        await session.flush()
        await session.execute(
            text(
                "UPDATE track SET is_commute = true, commute_od_id = :od "
                "WHERE id = ANY(:ids) AND user_id = :uid"
            ),
            {"od": str(record.id), "ids": od.track_ids, "uid": str(user_id)},
        )

    await _classify_trips(session, user_id)
    return {"ran": True, "ods": len(results), "workdays": int(workdays)}


def _wkt_points(wkt: str | None) -> list[tuple[float, float]]:
    """LINESTRING(lon lat, ...) -> [(lat, lon), ...]."""
    if not wkt or "(" not in wkt:
        return []
    body = wkt[wkt.index("(") + 1 : wkt.rindex(")")]
    points: list[tuple[float, float]] = []
    for pair in body.split(","):
        parts = pair.strip().split()
        if len(parts) >= 2:
            points.append((float(parts[1]), float(parts[0])))
    return points


async def _classify_trips(session: AsyncSession, user_id: UUID) -> None:
    """Summarise commute at trip level.

    'pure' requires that almost nothing else happened AND that no photo was
    taken - only pure days may be deleted wholesale, so the bar has to be high.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT t.id::text AS trip_id,
                       COALESCE(SUM(CASE WHEN pa.kind IN ('home','work')
                                         THEN p.duration_s ELSE 0 END), 0) AS commute_dwell,
                       COALESCE(SUM(CASE WHEN pa.kind IN ('home','work')
                                         THEN 0 ELSE p.duration_s END), 0) AS other_dwell,
                       COALESCE(MAX(CASE WHEN tr.is_commute THEN 1 ELSE 0 END), 0) AS has_commute,
                       COALESCE(MAX(ph.cnt), 0) AS photo_count
                  FROM trip t
                  LEFT JOIN place p  ON p.trip_id = t.id
                  LEFT JOIN place_anchor pa ON pa.id = p.anchor_id
                  LEFT JOIN track tr ON tr.trip_id = t.id
                  LEFT JOIN (SELECT trip_id, count(*) AS cnt FROM photo
                              WHERE user_id = :uid GROUP BY trip_id) ph
                         ON ph.trip_id = t.id
                 WHERE t.user_id = :uid
                 GROUP BY t.id
                """
            ),
            {"uid": str(user_id)},
        )
    ).all()

    for row in rows:
        verdict = commute_lib.classify_trip(
            commute_dwell_s=float(row.commute_dwell or 0),
            other_dwell_s=float(row.other_dwell or 0),
            photo_count=int(row.photo_count or 0),
            has_commute_track=bool(row.has_commute),
        )
        if verdict == "none":
            continue
        await session.execute(
            text("UPDATE trip SET commute_class = :c WHERE id = :id"),
            {"c": verdict, "id": row.trip_id},
        )

    # Retitle pure-commute days, but only those still carrying the bare-date
    # fallback title: anything richer came from a place name or from the user.
    await session.execute(
        text(
            """
            UPDATE trip
               SET title = :prefix || ' · ' || to_char(local_date, 'MM-DD')
             WHERE user_id = :uid
               AND commute_class = 'pure'
               AND title ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            """
        ),
        {"uid": str(user_id), "prefix": COMMUTE_TITLE},
    )


async def suggest_fences(session: AsyncSession, user_id: UUID) -> list[dict]:
    """Propose privacy fences from the inferred home/work anchors.

    The three confidence tiers are presented SEPARATELY and never merged.
    Measured: a confirmed Home and an 'Inferred Home' sat 427 m apart. Merged
    into one 500 m fence, the user would confirm one address and leave the other
    completely exposed.

    Nothing is written to `geofence` here - the user confirms each suggestion
    before it becomes a fence.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT id::text AS id, ST_Y(centroid) AS lat, ST_X(centroid) AS lon,
                       kind::text AS kind, kind_source, visit_count,
                       first_visit_utc, last_visit_utc, geo_name, geo_city
                  FROM place_anchor
                 WHERE user_id = :uid AND kind IN ('home','work')
                 ORDER BY last_visit_utc DESC NULLS LAST
                """
            ),
            {"uid": str(user_id)},
        )
    ).all()

    built = [
        anchor_lib.Anchor(
            lat=r.lat,
            lon=r.lon,
            visit_count=r.visit_count,
            first_visit_utc=r.first_visit_utc,
            last_visit_utc=r.last_visit_utc,
            kind=r.kind,
            kind_source=r.kind_source,
        )
        for r in rows
    ]
    merged = anchor_lib.merge_for_fences(built)

    existing = (
        await session.execute(
            text(
                "SELECT ST_Y(center) AS lat, ST_X(center) AS lon FROM geofence WHERE user_id = :uid"
            ),
            {"uid": str(user_id)},
        )
    ).all()

    from contrail.core.geo import haversine_m

    suggestions: list[dict] = []
    for anchor in merged:
        already = any(
            haversine_m(anchor.lat, anchor.lon, e.lat, e.lon) < anchor_lib.FENCE_MERGE_EPS_M
            for e in existing
        )
        suggestions.append(
            {
                "kind": anchor.kind,
                "confidence": anchor.kind_source or anchor_lib.HEURISTIC,
                "lat": anchor.lat,
                "lon": anchor.lon,
                "radius_m": 500,
                "visit_count": anchor.visit_count,
                "first_visit_utc": (
                    anchor.first_visit_utc.isoformat() if anchor.first_visit_utc else None
                ),
                "last_visit_utc": (
                    anchor.last_visit_utc.isoformat() if anchor.last_visit_utc else None
                ),
                "already_fenced": already,
            }
        )
    return suggestions


async def create_fence(
    session: AsyncSession,
    user_id: UUID,
    kind: str,
    label: str,
    lat: float,
    lon: float,
    radius_m: float = 500,
) -> Geofence:
    """Create a fence. buffer_geom is materialised by a database trigger."""
    fence = Geofence(
        user_id=user_id,
        kind=kind,
        label=label,
        center=f"SRID=4326;POINT({lon} {lat})",
        radius_m=radius_m,
        # A fixed seed per fence: identical jitter across every export. A fresh
        # random value each time would let repeated exports be averaged back to
        # the true circle centre.
        jitter_seed=secrets.randbits(63),
    )
    session.add(fence)
    await session.flush()
    return fence


async def geocode_anchors(session: AsyncSession, user_id: UUID, limit: int = 200) -> dict:
    """Reverse-geocode anchors only - never Places, never raw points.

    Anchors number in the hundreds rather than the thousands, so the request
    volume drops by an order of magnitude and the cache hit rate rises above
    95%. Places inherit their names from their anchor.

    Disabled entirely when geocoding is off: no request leaves the machine, and
    spatial search keeps working - only names are missing.
    """
    from contrail.config import get_settings
    from contrail.geocode import reverse_geocode

    settings = get_settings()
    if not settings.geocoding_enabled or not settings.mapbox_token:
        return {"ran": False, "reason": "disabled"}

    rows = (
        await session.execute(
            text(
                """
                SELECT id::text AS id, ST_Y(centroid) AS lat, ST_X(centroid) AS lon
                  FROM place_anchor
                 WHERE user_id = :uid AND geo_name IS NULL
                 ORDER BY visit_count DESC
                 LIMIT :limit
                """
            ),
            {"uid": str(user_id), "limit": limit},
        )
    ).all()

    resolved = 0
    for row in rows:
        result = await reverse_geocode(session, row.lat, row.lon)
        if result is None:
            continue
        await session.execute(
            text(
                """
                UPDATE place_anchor
                   SET geo_name = :name, geo_city = :city,
                       geo_region = :region, geo_country = :country
                 WHERE id = :id
                """
            ),
            {**result, "id": row.id},
        )
        resolved += 1

    # Places inherit the anchor's names.
    await session.execute(
        text(
            """
            UPDATE place p
               SET geo_name  = COALESCE(p.geo_name, a.geo_name),
                   geo_city  = COALESCE(p.geo_city, a.geo_city),
                   geo_region = COALESCE(p.geo_region, a.geo_region),
                   geo_country = COALESCE(p.geo_country, a.geo_country),
                   geo_source = COALESCE(p.geo_source, 'anchor')
              FROM place_anchor a
             WHERE p.anchor_id = a.id AND p.user_id = :uid
            """
        ),
        {"uid": str(user_id)},
    )
    await _retitle_trips(session, user_id)
    return {"ran": True, "resolved": resolved, "candidates": len(rows)}


async def _retitle_trips(session: AsyncSession, user_id: UUID) -> None:
    """Upgrade auto-titles once place names exist.

    Only touches titles that still look generated - the user may have renamed a
    trip, and a title is metadata they own (P7).
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT t.id::text AS trip_id, t.local_date, t.title,
                       (SELECT p.geo_city FROM place p
                         WHERE p.trip_id = t.id AND p.geo_city IS NOT NULL
                         GROUP BY p.geo_city ORDER BY SUM(p.duration_s) DESC LIMIT 1) AS city,
                       (SELECT array_agg(DISTINCT p.geo_country) FROM place p
                         WHERE p.trip_id = t.id AND p.geo_country IS NOT NULL) AS countries
                  FROM trip t
                 WHERE t.user_id = :uid AND t.is_auto
                """
            ),
            {"uid": str(user_id)},
        )
    ).all()

    for row in rows:
        stamp = row.local_date.strftime("%m-%d")
        countries = [c for c in (row.countries or []) if c]
        if len(set(countries)) >= 2:
            title = f"{countries[0]} → {countries[-1]} · {stamp}"
        elif row.city:
            title = f"{row.city} · {stamp}"
        else:
            continue
        if row.title == title:
            continue
        await session.execute(
            text(
                "UPDATE trip SET title = :title WHERE id = :id "
                "AND (title ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' OR title LIKE '%' || :stamp)"
            ),
            {"title": title, "id": row.trip_id, "stamp": stamp},
        )


async def full_refresh(session: AsyncSession, user_id: UUID) -> dict:
    """Anchors -> commute -> geocoding, in the only order that works."""
    result = {"started_at": datetime.utcnow().isoformat()}
    result["anchors"] = await refresh_anchors(session, user_id)
    result["commute"] = await refresh_commute(session, user_id)
    try:
        result["geocode"] = await geocode_anchors(session, user_id)
    except Exception as exc:  # noqa: BLE001 - geocoding must never block the map
        log.warning("geocoding pass failed", extra={"error": str(exc)})
        result["geocode"] = {"ran": False, "reason": "error"}
    return result
