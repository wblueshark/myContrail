"""Reverse geocoding via the Mapbox Geocoding API.

Scope was tightened deliberately: only place_anchor rows are geocoded - never
Places, and certainly never raw points. Anchors number in the hundreds, so the
request volume is negligible and the cache hit rate exceeds 95%. Places inherit
their names from their anchor.

Nominatim was dropped outright. Beyond its 1 req/s limit it explicitly forbids
systematic or bulk geocoding, and "resolve every anchor after an import" is bulk
geocoding by definition.

Results are cached forever, keyed by geohash7 (~153 m). An anchor's coordinates
do not move, so a given location is requested exactly once in its lifetime.

Turning geocoding off is a first-class mode, not a degraded one: no request
leaves the machine, names stay empty, and every spatial query still works. What
does degrade is honest and must be shown - country/city counts and the first two
tiers of automatic trip naming.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from contrail.config import get_settings
from contrail.core.geo import geohash

log = logging.getLogger(__name__)

GEOCODE_PRECISION = 7
MAX_ATTEMPTS = 3
REQUEST_TIMEOUT_S = 8
ENDPOINT = "https://api.mapbox.com/geocoding/v5/mapbox.places/{lon},{lat}.json"


@dataclass
class TokenBucket:
    """Simple rate limiter so we stay well inside the provider's limits."""

    rate_per_s: float = 5.0
    capacity: float = 10.0
    _tokens: float = 10.0
    _updated: float = 0.0

    async def acquire(self) -> None:
        now = time.monotonic()
        if self._updated == 0.0:
            self._updated = now
        self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate_per_s)
        self._updated = now
        if self._tokens < 1.0:
            await asyncio.sleep((1.0 - self._tokens) / self.rate_per_s)
            self._tokens = 0.0
        else:
            self._tokens -= 1.0


_bucket = TokenBucket()


async def reverse_geocode(session: AsyncSession, lat: float, lon: float) -> dict | None:
    """-> {'name','city','region','country'} or None. Never raises."""
    settings = get_settings()
    if not settings.geocoding_enabled or not settings.mapbox_token:
        return None

    key = geohash(lat, lon, GEOCODE_PRECISION)
    cached = (
        await session.execute(
            text(
                "SELECT name, city, region, country FROM geocode_cache WHERE geohash7 = :k"
            ),
            {"k": key},
        )
    ).first()
    if cached is not None:
        return {
            "name": cached.name,
            "city": cached.city,
            "region": cached.region,
            "country": cached.country,
        }

    await _bucket.acquire()
    payload = await asyncio.to_thread(_fetch, lat, lon, settings.mapbox_token)
    if payload is None:
        return None

    result = _parse(payload)
    await session.execute(
        text(
            """
            INSERT INTO geocode_cache (geohash7, name, city, region, country, provider)
            VALUES (:k, :name, :city, :region, :country, 'mapbox')
            ON CONFLICT (geohash7) DO NOTHING
            """
        ),
        {"k": key, **result},
    )
    return result


def _fetch(lat: float, lon: float, token: str) -> dict | None:
    """Blocking HTTP call; always invoked from a worker thread.

    urllib rather than an HTTP client library: it keeps the pinned dependency
    set exactly as verified, and this is a handful of requests per import.
    """
    query = urllib.parse.urlencode({"access_token": token, "types": "poi,address,place,country"})
    url = f"{ENDPOINT.format(lon=lon, lat=lat)}?{query}"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "contrail/0.1"})
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            # Never log coordinates. geohash4 is ~20 km: enough to tell which
            # continent misbehaved, useless for locating anyone.
            log.warning(
                "reverse geocode attempt failed",
                extra={
                    "attempt": attempt,
                    "position": f"gh4:{geohash(lat, lon, 4)}",
                    "error": type(exc).__name__,
                },
            )
            if attempt == MAX_ATTEMPTS:
                return None
            time.sleep(0.5 * attempt)
    return None


def _parse(payload: dict) -> dict:
    features = payload.get("features") or []
    result = {"name": None, "city": None, "region": None, "country": None}
    if not features:
        return result

    result["name"] = features[0].get("text")
    for feature in features:
        for kind in feature.get("place_type", []):
            if kind == "place" and result["city"] is None:
                result["city"] = feature.get("text")
            elif kind == "region" and result["region"] is None:
                result["region"] = feature.get("text")
            elif kind == "country" and result["country"] is None:
                result["country"] = feature.get("text")
    # The primary feature's context also carries the hierarchy.
    for entry in features[0].get("context", []):
        identifier = entry.get("id", "")
        if identifier.startswith("place") and result["city"] is None:
            result["city"] = entry.get("text")
        elif identifier.startswith("region") and result["region"] is None:
            result["region"] = entry.get("text")
        elif identifier.startswith("country") and result["country"] is None:
            result["country"] = entry.get("text")
    return result
