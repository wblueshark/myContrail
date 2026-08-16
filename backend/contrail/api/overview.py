"""Overview aggregates: where you have been, by country and by city.

Read-only. Nothing here derives, writes, or triggers a geocoding request - a
missing place name stays missing and the page says so, because silently calling
Mapbox to fill a table would turn browsing into a stream of outbound requests.

Two rules the numbers depend on:

  attribution   a trip belongs to a country/city when at least one of its places
                does. A trip that crossed a border therefore counts once in EACH
                country, and the rows add up to more than the overall total. The
                page states this; the alternative (splitting distance at the
                border) needs boundary data this product deliberately does not
                carry.
  no dropping   places whose reverse geocoding never ran land in a row with a
                null key rather than vanishing. Dropping them makes these rows
                disagree with the totals in the map header, and a user cannot
                tell which of the two lied.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from contrail.db import get_session
from contrail.schemas import OverviewRow
from contrail.security import current_user_id

router = APIRouter(prefix="/overview", tags=["overview"])

# Distinct (key, trip) pairs first, then one join back to the trip: aggregating
# straight over the place join would multiply a trip's mileage by the number of
# places it happens to contain.
_AGGREGATE = """
    WITH pairs AS (
        SELECT DISTINCT {key_expr} AS key, t.id AS trip_id
          FROM trip t
          JOIN place p ON p.trip_id = t.id
         WHERE t.user_id = :uid
    )
    SELECT pairs.key                                              AS key,
           count(*)                                               AS trip_count,
           coalesce(sum((t.stats->>'photo_count')::int), 0)       AS photo_count,
           coalesce(sum((t.stats->>'distance_total_m')::float), 0) AS distance_m,
           min(t.local_date)                                      AS first_day,
           max(t.local_date)                                      AS last_day
      FROM pairs
      JOIN trip t ON t.id = pairs.trip_id
     GROUP BY pairs.key
     ORDER BY trip_count DESC, key
"""


async def _aggregate(session: AsyncSession, user_id, key_expr: str) -> list[dict]:
    result = await session.execute(
        text(_AGGREGATE.format(key_expr=key_expr)), {"uid": str(user_id)}
    )
    return [dict(row._mapping) for row in result.all()]


@router.get("/countries", response_model=list[OverviewRow])
async def countries(
    user_id=Depends(current_user_id), session: AsyncSession = Depends(get_session)
) -> list[OverviewRow]:
    rows = await _aggregate(session, user_id, "p.geo_country")
    # A separate pass: counted inside the trip aggregate, a city would be
    # counted once per trip rather than once.
    city_counts = {
        row.country: row.n
        for row in (
            await session.execute(
                text(
                    """
                    SELECT p.geo_country AS country, count(DISTINCT p.geo_city) AS n
                      FROM place p
                     WHERE p.user_id = :uid AND p.geo_city IS NOT NULL
                     GROUP BY p.geo_country
                    """
                ),
                {"uid": str(user_id)},
            )
        ).all()
    }
    return [
        OverviewRow(
            key=row["key"],
            label=row["key"],
            city_count=city_counts.get(row["key"], 0),
            trip_count=row["trip_count"],
            photo_count=row["photo_count"],
            distance_m=row["distance_m"],
            first_day=row["first_day"],
            last_day=row["last_day"],
        )
        for row in rows
    ]


@router.get("/cities", response_model=list[OverviewRow])
async def cities(
    country: str | None = None,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> list[OverviewRow]:
    rows = await _aggregate(session, user_id, "p.geo_city")
    city_country = {
        row.city: row.country
        for row in (
            await session.execute(
                text(
                    """
                    SELECT p.geo_city AS city, min(p.geo_country) AS country
                      FROM place p
                     WHERE p.user_id = :uid
                     GROUP BY p.geo_city
                    """
                ),
                {"uid": str(user_id)},
            )
        ).all()
    }
    out = [
        OverviewRow(
            key=row["key"],
            label=row["key"],
            country=city_country.get(row["key"]),
            trip_count=row["trip_count"],
            photo_count=row["photo_count"],
            distance_m=row["distance_m"],
            first_day=row["first_day"],
            last_day=row["last_day"],
        )
        for row in rows
    ]
    if country is None:
        return out
    # An explicit empty country filters to the unnamed row, which is why this
    # compares against "" rather than treating falsy as "no filter".
    return [row for row in out if (row.country or "") == country]
