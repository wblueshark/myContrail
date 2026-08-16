"""SQLAlchemy 2.0 ORM, mirroring the DDL in docs/design/05-architecture section 4.

Three schema rules that are load-bearing and easy to break:

1. Every spatial column is `geometry(..., 4326)`, never `geography`.
   ST_Simplify / ST_AsMVTGeom / ST_Difference / ST_Transform do not accept
   geography, and - far worse - `geography && geometry` in the tile SQL forces
   an implicit cast that silently disables the GiST index, turning every tile
   request into a sequential scan. Use ST_DistanceSphere when true metric
   distance is needed.
2. `raw_point` is not partitioned. 240k rows for a decade of real data does not
   need it, and partitioning only buys operational complexity.
3. `place.trip_id` / `track.trip_id` are ON DELETE SET NULL, not CASCADE. A Trip
   is a container derived from Places/Tracks; "split trip" is implemented as
   delete-then-recreate, and CASCADE would silently delete a whole day of data.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Enum types are created by the Alembic migration, so the ORM must not try to
# emit CREATE TYPE again (create_type=False).
SOURCE_TYPE_VALUES = (
    "photo",
    "google_records",
    "google_semantic",
    "google_timeline",
    "gpx",
    "tcx",
    "fit",
    "manual",
)
TRAVEL_MODE_VALUES = ("walk", "run", "bike", "car", "transit", "flight", "unknown")
POINT_CONFIDENCE_VALUES = ("measured", "inferred", "manual")
ANCHOR_KIND_VALUES = ("home", "work", "frequent", "other")
COMMUTE_CLASS_VALUES = ("pure", "mixed", "none")
GROUP_KIND_VALUES = ("user", "system_commute")
FENCE_KIND_VALUES = ("home", "work")


def _enum(name: str, values: tuple[str, ...]) -> ENUM:
    return ENUM(*values, name=name, create_type=False)


source_type = _enum("source_type", SOURCE_TYPE_VALUES)
travel_mode = _enum("travel_mode", TRAVEL_MODE_VALUES)
point_confidence = _enum("point_confidence", POINT_CONFIDENCE_VALUES)
anchor_kind = _enum("anchor_kind", ANCHOR_KIND_VALUES)
commute_class = _enum("commute_class", COMMUTE_CLASS_VALUES)
group_kind = _enum("group_kind", GROUP_KIND_VALUES)
fence_kind = _enum("fence_kind", FENCE_KIND_VALUES)

TSTZ = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    default_tz: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'UTC'"))
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=text("now()"))


class SourceFile(Base):
    __tablename__ = "source_file"
    __table_args__ = (UniqueConstraint("user_id", "content_hash"),)  # L1 dedup

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(source_type, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    # The retained original file. Keeping it is what makes "re-run after a
    # parser fix" and "undo a deletion by re-importing" possible.
    storage_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    error_detail: Mapped[dict | None] = mapped_column(JSONB)
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    imported_at: Mapped[datetime] = mapped_column(
        TSTZ, nullable=False, server_default=text("now()")
    )


class Group(Base):
    __tablename__ = "group"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(group_kind, nullable=False, server_default=text("'user'"))
    color: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=text("now()"))


class Tag(Base):
    __tablename__ = "tag"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str | None] = mapped_column(Text)


class RawPoint(Base):
    __tablename__ = "raw_point"
    __table_args__ = (
        Index("ix_raw_point_user_dedup", "user_id", "dedup_key", unique=True),  # L2 dedup
        Index("ix_raw_point_geom", "geom", postgresql_using="gist"),
        Index("ix_raw_point_user_ts", "user_id", "ts_utc"),
        # Required for undo-import; without it the delete is a sequential scan.
        Index("ix_raw_point_user_source", "user_id", "source_file_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_file.id", ondelete="CASCADE"), nullable=False
    )
    source_kind: Mapped[str] = mapped_column(source_type, nullable=False)
    ts_utc: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    # Left NULL by default: resolving a zone per point over 3M points costs
    # 5-50 minutes. Only derived objects get a zone.
    tz_name: Mapped[str | None] = mapped_column(Text)
    geom: Mapped[str] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    altitude_m: Mapped[float | None] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float)
    speed_mps: Mapped[float | None] = mapped_column(Float)
    heading_deg: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(
        point_confidence, nullable=False, server_default=text("'measured'")
    )
    dedup_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    raw: Mapped[dict | None] = mapped_column(JSONB)


class Trip(Base):
    __tablename__ = "trip"
    __table_args__ = (
        UniqueConstraint("user_id", "local_date"),  # one Trip per local day
        Index("ix_trip_user_date", "user_id", text("local_date DESC")),
        Index("ix_trip_bbox", "bbox", postgresql_using="gist"),
        Index("ix_trip_group", "group_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    # The zone used to split days = zone of the day's first event's origin.
    anchor_tz: Mapped[str] = mapped_column(Text, nullable=False)
    start_utc: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    # May exceed 24h on a timezone-crossing day (37h measured on real data).
    end_utc: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("group.id", ondelete="SET NULL")
    )
    commute_class: Mapped[str] = mapped_column(
        commute_class, nullable=False, server_default=text("'none'")
    )
    bbox: Mapped[str | None] = mapped_column(Geometry("POLYGON", srid=4326))
    cover_photo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    is_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class TripTag(Base):
    __tablename__ = "trip_tag"

    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trip.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True
    )


class PlaceAnchor(Base):
    """A derived index, not a storage entity: it aggregates repeated visits to
    one location and keeps only statistics, never an individual visit record.
    Deleting it loses no user data. It is the single landing point for home/work
    inference, commute OD detection and geofence pre-fill."""

    __tablename__ = "place_anchor"
    __table_args__ = (Index("ix_place_anchor_centroid", "centroid", postgresql_using="gist"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    centroid: Mapped[str] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    radius_m: Mapped[float | None] = mapped_column(Float)
    visit_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    first_visit_utc: Mapped[datetime | None] = mapped_column(TSTZ)
    last_visit_utc: Mapped[datetime | None] = mapped_column(TSTZ)
    total_duration_s: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    hour_histogram: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{}'")
    )
    weekday_ratio: Mapped[float | None] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(anchor_kind, nullable=False, server_default=text("'other'"))
    # 'google_confirmed' (Home/Work) | 'google_inferred' | 'heuristic'
    # These three MUST stay separable: measured distance between a confirmed
    # Home and an Inferred Home was 427 m - they are different places.
    kind_source: Mapped[str | None] = mapped_column(Text)
    geo_name: Mapped[str | None] = mapped_column(Text)
    geo_city: Mapped[str | None] = mapped_column(Text)
    geo_region: Mapped[str | None] = mapped_column(Text)
    geo_country: Mapped[str | None] = mapped_column(Text)


class Place(Base):
    __tablename__ = "place"
    __table_args__ = (
        Index("ix_place_centroid", "centroid", postgresql_using="gist"),
        Index("ix_place_user_start", "user_id", "start_utc"),
        Index("ix_place_trip", "trip_id"),
        Index("ix_place_anchor", "anchor_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trip.id", ondelete="SET NULL")
    )
    anchor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("place_anchor.id", ondelete="SET NULL")
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("group.id", ondelete="SET NULL")
    )
    centroid: Mapped[str] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    radius_m: Mapped[float | None] = mapped_column(Float)
    start_utc: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    end_utc: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    duration_s: Mapped[int] = mapped_column(
        Integer, Computed("EXTRACT(EPOCH FROM (end_utc - start_utc))::int", persisted=True)
    )
    # 'track' (normal) | 'photo' (photo-only day, no dwell duration)
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'track'"))
    # A strong merge hint, NOT a stable identity: Google mints a fresh placeID
    # per visit for inferred (non-POI) places.
    google_place_id: Mapped[str | None] = mapped_column(Text)
    # P4: a dwell whose duration is partly inferred from a data gap must say so.
    is_inferred_dwell: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    inferred_ratio: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    tz_name: Mapped[str | None] = mapped_column(Text)
    point_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    name: Mapped[str | None] = mapped_column(Text)
    geo_name: Mapped[str | None] = mapped_column(Text)
    geo_city: Mapped[str | None] = mapped_column(Text)
    geo_region: Mapped[str | None] = mapped_column(Text)
    geo_country: Mapped[str | None] = mapped_column(Text)
    geo_source: Mapped[str | None] = mapped_column(Text)
    source_kinds: Mapped[list[str]] = mapped_column(
        ARRAY(source_type), nullable=False, server_default=text("'{}'")
    )


class PlaceTag(Base):
    __tablename__ = "place_tag"

    place_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("place.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True
    )


class Track(Base):
    __tablename__ = "track"
    __table_args__ = (
        Index("ix_track_geom", "geom", postgresql_using="gist"),
        Index("ix_track_user_start", "user_id", "start_utc"),
        Index("ix_track_trip", "trip_id", postgresql_where=text("NOT is_shadow")),
        Index("ix_track_commute", "user_id", "is_commute", postgresql_where=text("is_commute")),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trip.id", ondelete="SET NULL")
    )
    geom: Mapped[str] = mapped_column(Geometry("LINESTRING", srid=4326), nullable=False)
    start_utc: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    end_utc: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    # Nullable on purpose: 53% of semantic-era segments have no usable distance.
    # Recording 0 would quietly understate lifetime mileage as if it were known.
    distance_m: Mapped[float | None] = mapped_column(Float)
    distance_unknown: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # 'full' | 'endpoints_only' (semantic era gives only start and end)
    geom_quality: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'full'"))
    duration_s: Mapped[int] = mapped_column(Integer, nullable=False)
    speed_median_mps: Mapped[float | None] = mapped_column(Float)
    speed_p95_mps: Mapped[float | None] = mapped_column(Float)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)
    mode: Mapped[str] = mapped_column(travel_mode, nullable=False, server_default=text("'unknown'"))
    mode_source: Mapped[str | None] = mapped_column(Text)
    mode_confidence: Mapped[float | None] = mapped_column(Float)
    point_count: Mapped[int | None] = mapped_column(Integer)
    is_shadow: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_commute: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    commute_od_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Crosses a timezone: must never be split when assigning days.
    crosses_tz: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    source_kind: Mapped[str] = mapped_column(source_type, nullable=False)


class CommuteOD(Base):
    __tablename__ = "commute_od"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    from_anchor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("place_anchor.id", ondelete="CASCADE"), nullable=False
    )
    to_anchor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("place_anchor.id", ondelete="CASCADE"), nullable=False
    )
    occurrence: Mapped[int] = mapped_column(Integer, nullable=False)
    weekday_ratio: Mapped[float | None] = mapped_column(Float)
    depart_hour_mean: Mapped[float | None] = mapped_column(Float)
    depart_hour_circstd: Mapped[float | None] = mapped_column(Float)
    path_jaccard: Mapped[float | None] = mapped_column(Float)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))


class Photo(Base):
    __tablename__ = "photo"
    __table_args__ = (
        UniqueConstraint("user_id", "content_hash"),
        Index("ix_photo_geom", "geom", postgresql_using="gist"),
        Index("ix_photo_user_taken", "user_id", "taken_at_utc"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trip.id", ondelete="SET NULL")
    )
    place_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("place.id", ondelete="SET NULL")
    )
    geom: Mapped[str | None] = mapped_column(Geometry("POINT", srid=4326))
    taken_at_utc: Mapped[datetime | None] = mapped_column(TSTZ)
    taken_at_local: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    tz_name: Mapped[str | None] = mapped_column(Text)
    tz_source: Mapped[str | None] = mapped_column(Text)
    location_confidence: Mapped[str | None] = mapped_column(point_confidence)
    # The photo's OWN place intelligence, stored with the photo - not the Trip's
    # Place. See 04-data-contract section 8.5: association, never a merge.
    place_centroid: Mapped[str | None] = mapped_column(Geometry("POINT", srid=4326))
    place_name: Mapped[str | None] = mapped_column(Text)
    trip_place_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("place.id", ondelete="SET NULL")
    )
    thumb_key: Mapped[str | None] = mapped_column(Text)
    micro_key: Mapped[str | None] = mapped_column(Text)
    # Kept for the user's own reference only. NEVER read again after import and
    # never returned over HTTP (absolute paths must not appear in any request
    # or response - see 05-architecture section 3.2).
    orig_path: Mapped[str | None] = mapped_column(Text)
    orig_filename: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    camera_make: Mapped[str | None] = mapped_column(Text)
    camera_model: Mapped[str | None] = mapped_column(Text)


class PhotoSource(Base):
    """Many-to-many. The same photo may live in directory A and directory B;
    undoing A's import must not delete the copy B also contributed."""

    __tablename__ = "photo_source"

    photo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("photo.id", ondelete="CASCADE"), primary_key=True
    )
    source_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_file.id", ondelete="CASCADE"), primary_key=True
    )


class Geofence(Base):
    """Privacy fence.

    No time window, by design. 13 years of real data contained 24 distinct Home
    coordinates and 37 Work coordinates - the user moved house and changed jobs.
    Every historical address is a fence that applies at ALL times: an off-by-one
    in a time window is a leak, and a leak is the one unacceptable bug here.
    There is no `policy` column either - blur vs. remove is chosen per export."""

    __tablename__ = "geofence"
    __table_args__ = (Index("ix_geofence_center", "center", postgresql_using="gist"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(fence_kind, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    visit_count: Mapped[int | None] = mapped_column(Integer)
    first_visit_utc: Mapped[datetime | None] = mapped_column(TSTZ)
    last_visit_utc: Mapped[datetime | None] = mapped_column(TSTZ)
    center: Mapped[str] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    radius_m: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("500"))
    # Fixed seed so repeated exports of the same fence produce identical
    # break-point jitter. Varying it across exports would let an attacker
    # average many exports back to the true circle.
    jitter_seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    buffer_geom: Mapped[str | None] = mapped_column(Geometry("POLYGON", srid=4326))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class GeocodeCache(Base):
    __tablename__ = "geocode_cache"

    geohash7: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=text("now()"))


class ImportTask(Base):
    """Task state machine. Progress ticks live in memory / Redis; this table is
    the durable record so a restart does not lose the import history."""

    __tablename__ = "import_task"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    stage: Mapped[str | None] = mapped_column(Text)
    processed: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    total: Mapped[int | None] = mapped_column(BigInteger)
    options: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    error_detail: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=text("now()"))
    finished_at: Mapped[datetime | None] = mapped_column(TSTZ)


class ExportTask(Base):
    __tablename__ = "export_task"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    storage_key: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=text("now()"))
    finished_at: Mapped[datetime | None] = mapped_column(TSTZ)
