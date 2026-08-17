"""Import orchestration.

Engineering constraints this file exists to satisfy:

  memory       fully streaming; nothing accumulates a whole file. Points go out
               in batches of 5,000.
  throughput   batched INSERT ... ON CONFLICT DO NOTHING. The COPY-to-temp-table
               optimisation was cut on purpose: at 240k points it buys nothing.
  idempotence  re-running a task cannot create duplicates - the unique index on
               (user_id, dedup_key) decides, not the application.
  partial fail one bad file is recorded in source_file.error_detail and the
               batch continues. Silence is never an option (P6).
  undo         deleting a source_file cascades its raw_points, then the affected
               window is recomputed locally.

CPU-bound work (EXIF parsing, JPEG decoding) runs in a ProcessPoolExecutor.
Doing it inline would block the event loop, and then progress reporting and
cancellation - the two things a long import needs most - stop working entirely.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from contrail.config import get_settings
from contrail.imaging import render_thumbnails
from contrail.models import Photo, PhotoSource, Place, RawPoint, SourceFile, Trip, TripTag
from contrail.parsers.base import (
    PlaceHint,
    RawPointDTO,
    SkipNote,
    TrackHint,
    UnknownFormatError,
)
from contrail.parsers.photo import IMAGE_SUFFIXES, PhotoMeta
from contrail.parsers.photo import extract as extract_photo_meta
from contrail.parsers.registry import sniff
from contrail.pipeline.dedup import point_dedup_key
from contrail.pipeline.derive import rederive_window
from contrail.storage import file_sha256, get_storage, sharded_name

log = logging.getLogger(__name__)

BATCH_SIZE = 5_000
PHOTO_PROGRESS_EVERY = 25
# The report links to trips that kept their own group. A decade-wide import can
# touch thousands; the list is for a "see those N" link, not a data dump.
UPDATED_TRIP_ID_CAP = 200

ProgressFn = Callable[[str, int, int | None], None]


def _noop(stage: str, processed: int, total: int | None) -> None:  # pragma: no cover
    pass


@dataclass
class ImportReport:
    source_file_id: str | None = None
    kind: str = "unknown"
    display_name: str = ""
    points: int = 0
    photos: int = 0
    duplicates: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    trips_created: int = 0
    trips_updated: int = 0
    places: int = 0
    tracks: int = 0
    time_span: dict[str, str | None] = field(default_factory=dict)
    already_imported: bool = False
    # Days whose events span more than one zone. Reported because the trip was
    # deliberately NOT split at the border, and the report has to say so.
    tz_crossings: int = 0
    # {"detected": bool, "reason": str | None, ...} - whatever refresh_commute
    # concluded for this import. The wizard shows it as a sentence.
    commute: dict = field(default_factory=dict)
    # Trips that already existed and kept their group. Capped: a decade-wide
    # import can touch thousands, and the report only needs enough to link to.
    updated_trip_ids: list[str] = field(default_factory=list)
    updated_trip_ids_truncated: bool = False

    def as_dict(self) -> dict:
        return {
            "source_file_id": self.source_file_id,
            "kind": self.kind,
            "display_name": self.display_name,
            "points": self.points,
            "photos": self.photos,
            "duplicates": self.duplicates,
            "skipped": self.skipped,
            "errors": self.errors,
            "trips_created": self.trips_created,
            "trips_updated": self.trips_updated,
            "places": self.places,
            "tracks": self.tracks,
            "time_span": self.time_span,
            "already_imported": self.already_imported,
            "tz_crossings": self.tz_crossings,
            "commute": self.commute,
            "updated_trip_ids": self.updated_trip_ids,
            "updated_trip_ids_truncated": self.updated_trip_ids_truncated,
        }


# ── track / timeline files ────────────────────────────────
async def import_track_file(
    session: AsyncSession,
    user_id: UUID,
    path: Path,
    display_name: str,
    options: dict | None = None,
    progress: ProgressFn = _noop,
) -> ImportReport:
    """Import one trajectory or timeline file."""
    options = options or {}
    report = ImportReport(display_name=display_name)

    progress("sniffing", 0, None)
    content_hash = file_sha256(path)

    existing = (
        await session.execute(
            select(SourceFile).where(
                SourceFile.user_id == user_id, SourceFile.content_hash == content_hash
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # L1: byte-identical file already imported.
        report.already_imported = True
        report.source_file_id = str(existing.id)
        report.kind = existing.kind
        return report

    try:
        match = sniff(path)
    except UnknownFormatError as exc:
        report.errors.append({"stage": "sniff", "error": str(exc), "sample": str(exc.sample)})
        raise

    report.kind = match.source_kind
    source = SourceFile(
        user_id=user_id,
        kind=match.source_kind,
        display_name=display_name,
        content_hash=content_hash,
        byte_size=path.stat().st_size,
        status="running",
    )
    session.add(source)
    await session.flush()
    report.source_file_id = str(source.id)

    # Retain the original. This is what lets a parser fix be re-applied later
    # and what makes deleting derived data reversible.
    storage = get_storage()
    source.storage_key = storage.put_file(
        "sources", sharded_name(content_hash, path.suffix.lower() or ".bin"), path
    )

    parser = match.parser(match.variant)
    batch: list[dict] = []
    earliest: datetime | None = None
    latest: datetime | None = None

    progress("parsing", 0, None)
    try:
        for item in parser.parse(path):
            if isinstance(item, RawPointDTO):
                earliest = item.ts_utc if earliest is None else min(earliest, item.ts_utc)
                latest = item.ts_utc if latest is None else max(latest, item.ts_utc)
                batch.append(_point_row(user_id, source.id, match.source_kind, item))
                if len(batch) >= BATCH_SIZE:
                    report.points += await _flush_points(session, batch)
                    batch.clear()
                    # Total is unknown while streaming, so report an absolute
                    # count rather than a fabricated percentage.
                    progress("persisting", report.points, None)
            elif isinstance(item, (PlaceHint, TrackHint)):
                # Declared stays and movements are recovered from the retained
                # original during derivation; nothing to persist here.
                earliest = (
                    item.start_utc if earliest is None else min(earliest, item.start_utc)
                )
                latest = item.end_utc if latest is None else max(latest, item.end_utc)
            elif isinstance(item, SkipNote):
                report.skipped[item.reason] = report.skipped.get(item.reason, 0) + item.count
    except UnknownFormatError as exc:
        source.status = "failed"
        source.error_detail = {"error": str(exc), "sample": str(exc.sample)}
        report.errors.append({"stage": "parse", "error": str(exc)})
        await session.flush()
        raise
    except Exception as exc:  # noqa: BLE001
        source.status = "failed"
        source.error_detail = {"error": f"{type(exc).__name__}: {exc}"}
        report.errors.append({"stage": "parse", "error": str(exc)})
        await session.flush()
        raise

    if batch:
        report.points += await _flush_points(session, batch)
        batch.clear()

    report.time_span = {
        "start": earliest.isoformat() if earliest else None,
        "end": latest.isoformat() if latest else None,
    }
    source.status = "done"
    source.stats = {
        "points": report.points,
        "skipped": report.skipped,
        "variant": match.variant,
        "time_span": report.time_span,
    }
    await session.flush()

    if earliest and latest:
        progress("cluster", 0, report.points)
        result = await rederive_window(session, user_id, earliest, latest)
        report.trips_created = result["trips_created"]
        report.trips_updated = result["trips_updated"]
        report.places = result["places"]
        report.tracks = result["tracks"]
        await _apply_group_and_tags(session, user_id, earliest, latest, options, report)
        await _summarise_window(session, user_id, earliest, latest, report)
        progress("cluster", report.points, report.points)

    progress("done", report.points, report.points)
    return report


def _point_row(user_id: UUID, source_id: UUID, kind: str, item: RawPointDTO) -> dict:
    return {
        "user_id": user_id,
        "source_file_id": source_id,
        "source_kind": kind,
        "ts_utc": item.ts_utc,
        "tz_name": item.tz_name,
        "geom": f"SRID=4326;POINT({item.lon} {item.lat})",
        "altitude_m": item.altitude_m,
        "accuracy_m": item.accuracy_m,
        "speed_mps": item.speed_mps,
        "heading_deg": item.heading_deg,
        "confidence": item.confidence,
        "dedup_key": point_dedup_key(user_id, item.ts_utc, item.lat, item.lon),
        "raw": item.raw,
    }


async def _flush_points(session: AsyncSession, batch: list[dict]) -> int:
    """Insert a batch, letting the unique index absorb duplicates.

    DO NOTHING rather than raising: timelinePath contains genuine duplicate
    minute offsets (12 in the measured sample), so a collision is expected data,
    not an error.

    An executemany insert does not always return a usable rowcount, so the batch
    size is the fallback. That counts rows offered rather than rows stored - the
    difference is duplicates, which the unique index has already discarded.
    """
    stmt = pg_insert(RawPoint).on_conflict_do_nothing(index_elements=["user_id", "dedup_key"])
    result = await session.execute(stmt, batch)
    rowcount = getattr(result, "rowcount", None)
    return rowcount if isinstance(rowcount, int) and rowcount >= 0 else len(batch)


# ── photo directories ─────────────────────────────────────
def _scan_images(directory: Path, include_subdirs: bool = True) -> Iterable[Path]:
    entries = directory.rglob("*") if include_subdirs else directory.glob("*")
    for entry in sorted(entries):
        if entry.is_file() and entry.suffix.lower() in IMAGE_SUFFIXES:
            yield entry


# JPEG and HEIC dominate real libraries; the rest are reported under "other" so
# the counts still add up to parsable_count.
_FORMAT_GROUPS = {
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".heic": "heic",
    ".heif": "heic",
    ".png": "png",
    ".tif": "tiff",
    ".tiff": "tiff",
    ".dng": "dng",
}


def prescan_directory(
    directory: Path, sample_size: int = 40, include_subdirs: bool = True
) -> dict:
    """Count files and sample GPS coverage before committing to an import.

    The user picked this directory themselves and could have picked "/". The
    file count and time estimate are what stop that becoming a surprise.

    The GPS figure is a SAMPLE, not a census: reading every header of a 120k
    photo library would cost most of the import it is supposed to precede.
    `gps_estimated` and `sampled` travel with it so the UI can say so instead of
    printing an estimate as though it were counted.
    """
    files = list(_scan_images(directory, include_subdirs))
    by_format: dict[str, int] = {}
    for path in files:
        key = _FORMAT_GROUPS.get(path.suffix.lower(), "other")
        by_format[key] = by_format.get(key, 0) + 1

    sample = files[:: max(1, len(files) // sample_size)][:sample_size] if files else []
    with_gps = 0
    readable = 0
    earliest = latest = None
    for path in sample:
        meta = extract_photo_meta(path)
        readable += 1
        if meta.has_position:
            with_gps += 1
        if meta.ts_utc:
            earliest = meta.ts_utc if earliest is None else min(earliest, meta.ts_utc)
            latest = meta.ts_utc if latest is None else max(latest, meta.ts_utc)

    gps_ratio = (with_gps / len(sample)) if sample else 0.0
    return {
        "file_count": len(files),
        # Every scanned file carries a supported suffix, so the parsable count
        # is the file count until a header actually fails to read.
        "parsable_count": len(files),
        "by_format": by_format,
        "sampled": len(sample),
        "sample_readable": readable,
        "gps_ratio": gps_ratio,
        "gps_estimated": True,
        "gps_count_estimate": round(len(files) * gps_ratio),
        "no_gps_count_estimate": len(files) - round(len(files) * gps_ratio),
        "include_subdirs": include_subdirs,
        "time_span": {
            "start": earliest.isoformat() if earliest else None,
            "end": latest.isoformat() if latest else None,
        },
        # ~7 ms per photo measured with Image.draft() enabled.
        "estimated_seconds": round(len(files) * 0.008, 1),
    }


def _process_photo(path_str: str, want_thumbnails: bool = True) -> dict:
    """Runs in a worker process: EXIF + thumbnails, the CPU-heavy part."""
    path = Path(path_str)
    meta: PhotoMeta = extract_photo_meta(path)
    # Decoding is the expensive half. When the user turned thumbnails off there
    # is nothing to decode for, so skip it rather than render and discard.
    rendered = render_thumbnails(path) if want_thumbnails else None
    return {
        "path": path_str,
        "meta": meta,
        "thumb": rendered[0] if rendered else None,
        "micro": rendered[1] if rendered else None,
        "width": rendered[2] if rendered else meta.width,
        "height": rendered[3] if rendered else meta.height,
        "content_hash": file_sha256(path),
    }


async def import_photo_directory(
    session: AsyncSession,
    user_id: UUID,
    directory: Path,
    display_name: str,
    options: dict | None = None,
    progress: ProgressFn = _noop,
) -> ImportReport:
    """Import every image under a directory, exactly once.

    The directory is read here and never again. `orig_path` is recorded for the
    user's own reference only - it is never returned over HTTP.
    """
    options = options or {}
    settings = get_settings()
    report = ImportReport(kind="photo", display_name=display_name)

    include_subdirs = bool(options.get("include_subdirs", True))
    want_thumbnails = bool(options.get("generate_thumbnails", True))
    skip_duplicates = bool(options.get("skip_duplicates", True))
    infer_missing = bool(options.get("infer_missing_gps", True))
    infer_tolerance = int(options.get("infer_tolerance_s") or settings.photo_infer_tolerance_s)
    range_start, range_end = _date_bounds(options.get("date_range"))

    files = list(_scan_images(directory, include_subdirs))
    progress("scanning", 0, len(files))
    if not files:
        return report

    # The directory itself is the "source file"; its hash is derived from the
    # set of member hashes so re-importing the same directory is detectable.
    source = SourceFile(
        user_id=user_id,
        kind="photo",
        display_name=display_name,
        content_hash=b"\x00" * 32,  # replaced below once members are known
        byte_size=None,
        status="running",
    )
    session.add(source)
    await session.flush()
    report.source_file_id = str(source.id)

    storage = get_storage()
    earliest = latest = None
    member_digest = hashlib.sha256()
    unlocated: list[dict] = []

    thumbs_done = 0
    workers = max(1, min(8, (os.cpu_count() or 4) - 1))
    loop = asyncio.get_running_loop()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        pending = [
            loop.run_in_executor(pool, _process_photo, str(p), want_thumbnails) for p in files
        ]
        for index, future in enumerate(asyncio.as_completed(pending), start=1):
            try:
                item = await future
            except Exception as exc:  # noqa: BLE001 - one bad file, not a failed import
                report.errors.append({"stage": "photo", "error": f"{type(exc).__name__}: {exc}"})
                continue

            meta: PhotoMeta = item["meta"]
            member_digest.update(item["content_hash"])

            if not _within_range(meta, range_start, range_end):
                report.skipped["out_of_range"] = report.skipped.get("out_of_range", 0) + 1
                continue

            duplicate = (
                await session.execute(
                    select(Photo.id).where(
                        Photo.user_id == user_id, Photo.content_hash == item["content_hash"]
                    )
                )
            ).scalar_one_or_none()

            if duplicate is not None:
                # The same photo can sit in two directories. Link it to this
                # source as well, so undoing one import keeps the other's copy.
                #
                # A second row is impossible either way - photo is unique on
                # (user_id, content_hash). What `skip_duplicates=false` buys is
                # a rebuild: the duplicate's timestamp still widens the window
                # that gets re-derived, so a day whose derived layer was lost
                # comes back without deleting and re-importing the source.
                report.duplicates += 1
                await session.execute(
                    pg_insert(PhotoSource)
                    .values(photo_id=duplicate, source_file_id=source.id)
                    .on_conflict_do_nothing()
                )
                if not skip_duplicates and meta.ts_utc:
                    earliest = meta.ts_utc if earliest is None else min(earliest, meta.ts_utc)
                    latest = meta.ts_utc if latest is None else max(latest, meta.ts_utc)
                continue

            thumb_key = micro_key = None
            if item["thumb"]:
                thumb_key = storage.put(
                    "thumbs", sharded_name(item["content_hash"], ".webp"), item["thumb"]
                )
                micro_key = storage.put(
                    "micro", sharded_name(item["content_hash"], ".webp"), item["micro"]
                )
                thumbs_done += 1

            photo = Photo(
                user_id=user_id,
                geom=(
                    f"SRID=4326;POINT({meta.lon} {meta.lat})" if meta.has_position else None
                ),
                taken_at_utc=meta.ts_utc,
                taken_at_local=meta.taken_at_local,
                tz_name=meta.tz_name,
                tz_source=meta.tz_source,
                location_confidence=meta.location_confidence,
                place_centroid=(
                    f"SRID=4326;POINT({meta.lon} {meta.lat})" if meta.has_position else None
                ),
                thumb_key=thumb_key,
                micro_key=micro_key,
                orig_path=str(meta.path),
                orig_filename=meta.path.name,
                content_hash=item["content_hash"],
                width=item["width"],
                height=item["height"],
                camera_make=meta.camera_make,
                camera_model=meta.camera_model,
            )
            session.add(photo)
            await session.flush()
            await session.execute(
                pg_insert(PhotoSource)
                .values(photo_id=photo.id, source_file_id=source.id)
                .on_conflict_do_nothing()
            )
            report.photos += 1

            if meta.ts_utc:
                earliest = meta.ts_utc if earliest is None else min(earliest, meta.ts_utc)
                latest = meta.ts_utc if latest is None else max(latest, meta.ts_utc)
            if not meta.has_position and meta.ts_utc:
                unlocated.append({"id": str(photo.id), "ts": meta.ts_utc})

            if index % PHOTO_PROGRESS_EVERY == 0:
                # Two counters, reported separately: the wizard draws one bar
                # per phase and they do not advance together (a photo can be
                # read but produce no thumbnail).
                progress("read_exif", index, len(files))
                progress("thumbnails", thumbs_done, len(files))

    source.content_hash = member_digest.digest()
    source.status = "done"
    report.time_span = {
        "start": earliest.isoformat() if earliest else None,
        "end": latest.isoformat() if latest else None,
    }
    source.stats = {
        "photos": report.photos,
        "duplicates": report.duplicates,
        "errors": len(report.errors),
        "time_span": report.time_span,
    }
    await session.flush()

    if earliest and latest:
        progress("cluster", 0, report.photos)
        if unlocated and infer_missing:
            await _infer_photo_positions(session, user_id, unlocated, infer_tolerance)
        result = await rederive_window(session, user_id, earliest, latest)
        report.trips_created = result["trips_created"]
        report.trips_updated = result["trips_updated"]
        report.places = result["places"]
        report.tracks = result["tracks"]
        await _link_photos_to_places(session, user_id, earliest, latest, settings)
        await _apply_group_and_tags(session, user_id, earliest, latest, options, report)
        await _summarise_window(session, user_id, earliest, latest, report)
        progress("cluster", report.photos, report.photos)

    progress("done", report.photos, len(files))
    return report


async def _infer_photo_positions(
    session: AsyncSession, user_id: UUID, unlocated: list[dict], tolerance: int
) -> None:
    """Interpolate positions for photos with no GPS, marking them inferred.

    The tolerance is per import: the wizard offers it next to the checkbox, and
    a hiking batch wants a tighter window than a road-trip one.
    """
    from contrail.pipeline.photos import infer_photo_location
    from contrail.pipeline.types import Pt

    for entry in unlocated:
        rows = await session.execute(
            text(
                """
                SELECT ts_utc, ST_Y(geom) AS lat, ST_X(geom) AS lon
                FROM raw_point
                WHERE user_id = :uid
                  AND ts_utc BETWEEN :lo AND :hi
                ORDER BY ts_utc
                """
            ),
            {
                "uid": str(user_id),
                "lo": entry["ts"].astimezone(UTC) - timedelta(seconds=tolerance * 2),
                "hi": entry["ts"].astimezone(UTC) + timedelta(seconds=tolerance * 2),
            },
        )
        points = [Pt(ts=r.ts_utc, lat=r.lat, lon=r.lon) for r in rows]
        guess = infer_photo_location(entry["ts"], points, tolerance)
        if guess is None:
            continue  # stays in the "unlocated photos" list for manual placement
        await session.execute(
            text(
                """
                UPDATE photo
                   SET geom = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                       place_centroid = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                       location_confidence = 'inferred'
                 WHERE id = :id
                """
            ),
            {"lon": guess.lon, "lat": guess.lat, "id": entry["id"]},
        )


async def _link_photos_to_places(
    session: AsyncSession, user_id: UUID, start: datetime, end: datetime, settings
) -> None:
    """Associate photos with same-time, same-place Trip Places.

    This sets trip_place_id and trip_id. It does NOT move the photo's own place
    intelligence into the Place - they stay two separate entities.
    """
    await session.execute(
        text(
            """
            UPDATE photo p
               SET trip_place_id = m.place_id,
                   trip_id       = m.trip_id,
                   place_id      = m.place_id
              FROM (
                    SELECT DISTINCT ON (ph.id)
                           ph.id AS photo_id, pl.id AS place_id, pl.trip_id
                      FROM photo ph
                      JOIN place pl
                        ON pl.user_id = ph.user_id
                       AND ph.taken_at_utc BETWEEN pl.start_utc AND pl.end_utc
                       AND ST_DWithin(ph.geom::geography, pl.centroid::geography, :radius)
                     WHERE ph.user_id = :uid
                       AND ph.taken_at_utc BETWEEN :start AND :end
                       AND ph.geom IS NOT NULL
                     ORDER BY ph.id,
                              ST_DistanceSphere(ph.geom, pl.centroid)
                   ) m
             WHERE p.id = m.photo_id
            """
        ),
        {
            "uid": str(user_id),
            "start": start,
            "end": end,
            "radius": settings.cluster_radius_m,
        },
    )

    # Photos on days with no Place still belong to that day's Trip.
    await session.execute(
        text(
            """
            UPDATE photo p
               SET trip_id = t.id
              FROM trip t
             WHERE p.user_id = :uid
               AND p.trip_id IS NULL
               AND t.user_id = p.user_id
               AND p.taken_at_utc BETWEEN t.start_utc AND t.end_utc
            """
        ),
        {"uid": str(user_id)},
    )

    await session.execute(
        text(
            """
            UPDATE trip t
               SET cover_photo_id = c.id
              FROM (
                    SELECT DISTINCT ON (trip_id) id, trip_id
                      FROM photo
                     WHERE user_id = :uid AND trip_id IS NOT NULL
                     ORDER BY trip_id, taken_at_utc
                   ) c
             WHERE t.id = c.trip_id AND t.cover_photo_id IS NULL
            """
        ),
        {"uid": str(user_id)},
    )


# ── group / tag assignment ────────────────────────────────
def _date_bounds(date_range: dict | None) -> tuple[date | None, date | None]:
    """The wizard's optional "only import this date range", as local dates."""
    if not date_range:
        return None, None

    def parse(value) -> date | None:
        if value is None or value == "":
            return None
        return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])

    return parse(date_range.get("start")), parse(date_range.get("end"))


def _within_range(meta: PhotoMeta, start: date | None, end: date | None) -> bool:
    """Compare against the photo's LOCAL day.

    The user typed "2024-05-01 to 2024-05-08" meaning the days they lived, not a
    UTC window: a 23:30 photo in Tokyo belongs to that local day, not the one
    UTC would file it under.
    """
    if start is None and end is None:
        return True
    stamp = meta.taken_at_local or meta.ts_utc
    if stamp is None:
        return True  # no timestamp to judge by; never silently dropped
    day = stamp.date()
    if start and day < start:
        return False
    return not (end and day > end)


async def _summarise_window(
    session: AsyncSession,
    user_id: UUID,
    start: datetime,
    end: datetime,
    report: ImportReport,
) -> None:
    """How many days in this window cross a time zone.

    Computed here rather than left for the frontend to infer: the report claims
    "6 timezone crossings, trips kept whole", and a claim like that has to come
    from the data. The commute conclusion is filled in by the caller, after the
    post-import refresh has actually run.
    """
    report.tz_crossings = int(
        (
            await session.execute(
                text(
                    """
                    SELECT count(*) FROM trip t
                     WHERE t.user_id = :uid AND t.start_utc <= :end AND t.end_utc >= :start
                       AND EXISTS (SELECT 1 FROM track tr
                                    WHERE tr.trip_id = t.id AND tr.crosses_tz)
                    """
                ),
                {"uid": str(user_id), "start": start, "end": end},
            )
        ).scalar_one()
    )


def commute_summary(outcome: dict) -> dict:
    """Turn a refresh_commute result into the report's commute conclusion."""
    return {
        "detected": bool(outcome.get("ran")) and bool(outcome.get("ods")),
        "reason": outcome.get("reason"),
        "workdays": outcome.get("workdays"),
        "required_workdays": outcome.get("required_workdays"),
        "ods": outcome.get("ods", 0),
    }


async def _apply_group_and_tags(
    session: AsyncSession,
    user_id: UUID,
    start: datetime,
    end: datetime,
    options: dict,
    report: ImportReport,
) -> None:
    """A newly created Trip takes the batch's group; an existing one keeps its
    own. Tags are always appended - they are non-exclusive annotations.

    A day can be assembled from several sources across several imports (a Google
    timeline plus a GPX for the same afternoon). "Last write wins" would let an
    unrelated GPX import silently re-file an entire holiday.
    """
    group_id = options.get("group_id")
    tag_ids = options.get("tag_ids") or []
    if not group_id and not tag_ids:
        return

    trip_ids = (
        await session.execute(
            select(Trip.id, Trip.group_id).where(
                Trip.user_id == user_id, Trip.start_utc <= end, Trip.end_utc >= start
            )
        )
    ).all()

    kept: list[str] = []
    for trip_id, existing_group in trip_ids:
        if group_id and existing_group is None:
            await session.execute(
                text("UPDATE trip SET group_id = :g WHERE id = :id"),
                {"g": group_id, "id": trip_id},
            )
        elif group_id:
            # Kept its own group. The report links to these so the user can see
            # which days were left alone rather than wonder.
            kept.append(str(trip_id))
        for tag_id in tag_ids:
            await session.execute(
                pg_insert(TripTag).values(trip_id=trip_id, tag_id=tag_id).on_conflict_do_nothing()
            )

    report.updated_trip_ids = kept[:UPDATED_TRIP_ID_CAP]
    report.updated_trip_ids_truncated = len(kept) > UPDATED_TRIP_ID_CAP


# ── undo ──────────────────────────────────────────────────
async def undo_source(session: AsyncSession, user_id: UUID, source_file_id: UUID) -> dict:
    """Delete an import and locally recompute what it touched.

    Photos linked to another source survive: photo_source is many-to-many
    precisely so that undoing directory A does not delete photos that directory
    B also contributed.
    """
    source = (
        await session.execute(
            select(SourceFile).where(
                SourceFile.id == source_file_id, SourceFile.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if source is None:
        return {"deleted": False}

    span = (source.stats or {}).get("time_span") or {}
    start = datetime.fromisoformat(span["start"]) if span.get("start") else None
    end = datetime.fromisoformat(span["end"]) if span.get("end") else None

    if source.kind == "photo":
        result = await session.execute(
            text(
                """
                SELECT ps.photo_id
                  FROM photo_source ps
                 WHERE ps.source_file_id = :sid
                   AND NOT EXISTS (
                        SELECT 1 FROM photo_source o
                         WHERE o.photo_id = ps.photo_id
                           AND o.source_file_id <> :sid)
                """
            ),
            {"sid": str(source_file_id)},
        )
        orphans = list(result.scalars().all())
        if orphans:
            storage = get_storage()
            keys = (
                await session.execute(
                    select(Photo.thumb_key, Photo.micro_key).where(Photo.id.in_(orphans))
                )
            ).all()
            for thumb_key, micro_key in keys:
                for key in (thumb_key, micro_key):
                    if key:
                        storage.delete(key)
            await session.execute(delete(Photo).where(Photo.id.in_(orphans)))

    if source.storage_key:
        get_storage().delete(source.storage_key)

    await session.delete(source)  # raw_point cascades
    await session.flush()

    if start and end:
        await rederive_window(session, user_id, start, end)
    return {"deleted": True, "window": {"start": span.get("start"), "end": span.get("end")}}


async def import_summary(session: AsyncSession, user_id: UUID, start: datetime, end: datetime):
    """The "42 trips created / 3 already existed" report shown after an import."""
    rows = (
        await session.execute(
            select(Trip.id, Trip.title, Trip.local_date, Trip.group_id)
            .where(Trip.user_id == user_id, Trip.start_utc <= end, Trip.end_utc >= start)
            .order_by(Trip.local_date)
        )
    ).all()
    place_count = (
        await session.execute(
            select(func.count(Place.id)).where(
                Place.user_id == user_id, Place.start_utc <= end, Place.end_utc >= start
            )
        )
    ).scalar_one()
    return {
        "trips": [
            {
                "id": str(r[0]),
                "title": r[1],
                "local_date": r[2].isoformat(),
                "group_id": str(r[3]) if r[3] else None,
            }
            for r in rows
        ],
        "place_count": place_count,
    }
