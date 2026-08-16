"""Request and response models.

Two contracts are enforced by the types themselves rather than by review:

  * import-related request bodies have no `path` field of any kind, and
    `extra="forbid"` makes sending one a 422 rather than an ignored extra.
  * ExportRequest carries fence_actions, and the export route rejects a request
    whose scope intersects a fence without them. The frontend dialog can be
    bypassed; the server's refusal cannot.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Strict = ConfigDict(extra="forbid")


# ── system ────────────────────────────────────────────────
class Capabilities(BaseModel):
    mode: str
    scan_local_path: bool
    directory_picker: str | None
    serve_original: bool
    multi_user: bool
    sharing: bool
    geocoding_enabled: bool
    mapbox_token_configured: bool


# ── import ────────────────────────────────────────────────
class PickResponse(BaseModel):
    pick_token: str
    display_name: str
    prescan: dict


class PrescanRequest(BaseModel):
    """Accepts a pick_token or an upload_id. Never a path."""

    model_config = Strict
    pick_token: str | None = None
    upload_id: str | None = None
    # Re-scanning the same token with a different recursion setting is how the
    # wizard's "include subfolders" checkbox stays truthful about the counts.
    include_subdirs: bool = True


class DateRange(BaseModel):
    model_config = Strict
    # Local dates, as the user typed them; the importer resolves them against
    # each record's own zone rather than a server default.
    start: date | None = None
    end: date | None = None


class ImportOptions(BaseModel):
    """Per-import choices from step 3 of the wizard.

    Deliberately has no path field of any kind: `reject_path_fields()` walks the
    whole body, and `extra="forbid"` makes a stray one a 422 rather than a
    silently ignored extra.
    """

    model_config = Strict
    include_subdirs: bool = True
    infer_missing_gps: bool = True
    # None means "use the user's stored photo_infer_tolerance_s".
    infer_tolerance_s: int | None = Field(default=None, ge=300, le=10800)
    generate_thumbnails: bool = True
    skip_duplicates: bool = True
    date_range: DateRange | None = None


class ImportRequest(BaseModel):
    model_config = Strict
    # For photos this is a pick_token; for trajectory files, an upload_id.
    source_ref: str
    kind: Literal["photo", "file"] = "photo"
    group_id: UUID | None = None
    tag_ids: list[UUID] = Field(default_factory=list)
    options: ImportOptions = Field(default_factory=ImportOptions)


class TaskStage(BaseModel):
    """One phase of an import, reported alongside the others.

    The wizard shows three bars at once (EXIF / thumbnails / clustering), so a
    single current-stage field is not enough. `total` stays None while the total
    is genuinely unknown - a percentage would have to be invented.
    """

    key: str
    processed: int = 0
    total: int | None = None


class TaskResponse(BaseModel):
    id: str
    kind: str
    display_name: str
    status: str
    stage: str | None = None
    processed: int = 0
    total: int | None = None
    stages: list[TaskStage] = Field(default_factory=list)
    eta_seconds: int | None = None
    result: dict = Field(default_factory=dict)
    error: dict | None = None
    created_at: str | None = None
    finished_at: str | None = None


class SourceOut(BaseModel):
    id: UUID
    kind: str
    display_name: str
    status: str
    byte_size: int | None = None
    stats: dict = Field(default_factory=dict)
    error_detail: dict | None = None
    imported_at: datetime
    has_original: bool = False


# ── query ─────────────────────────────────────────────────
class TripOut(BaseModel):
    id: UUID
    title: str
    local_date: date
    anchor_tz: str
    start_utc: datetime
    end_utc: datetime
    group_id: UUID | None = None
    commute_class: str
    stats: dict = Field(default_factory=dict)
    tag_ids: list[UUID] = Field(default_factory=list)
    cover_photo_id: UUID | None = None
    # True when the day crosses zones - the UI must label every event with its
    # own zone abbreviation or the times look wrong.
    crosses_tz: bool = False


class PlaceOut(BaseModel):
    id: UUID
    trip_id: UUID | None
    lat: float
    lon: float
    radius_m: float | None
    start_utc: datetime
    end_utc: datetime
    duration_s: int
    origin: str
    is_inferred_dwell: bool
    inferred_ratio: float
    tz_name: str | None
    name: str | None
    geo_name: str | None
    geo_city: str | None
    geo_country: str | None
    point_count: int
    source_kinds: list[str] = Field(default_factory=list)
    photo_count: int = 0


class TrackOut(BaseModel):
    id: UUID
    trip_id: UUID | None
    start_utc: datetime
    end_utc: datetime
    distance_m: float | None
    # Explicit, because 53% of semantic-era segments have no distance and
    # showing that as 0 km would understate every total silently.
    distance_unknown: bool
    geom_quality: str
    duration_s: int
    mode: str
    mode_source: str | None
    mode_confidence: float | None
    is_commute: bool
    crosses_tz: bool
    source_kind: str


class PhotoOut(BaseModel):
    id: UUID
    trip_id: UUID | None
    place_id: UUID | None
    lat: float | None
    lon: float | None
    taken_at_utc: datetime | None
    taken_at_local: datetime | None
    tz_name: str | None
    tz_source: str | None
    location_confidence: str | None
    # orig_path is deliberately absent: absolute paths never travel over HTTP.
    orig_filename: str | None
    width: int | None
    height: int | None
    camera_make: str | None
    camera_model: str | None


class AnchorOut(BaseModel):
    id: UUID
    lat: float
    lon: float
    kind: str
    kind_source: str | None
    visit_count: int
    total_duration_s: int
    weekday_ratio: float | None
    first_visit_utc: datetime | None
    last_visit_utc: datetime | None
    geo_name: str | None
    geo_city: str | None
    geo_country: str | None = None
    # How many trips visited this anchor. The overview's place dimension ranks
    # on visit_count and shows this next to it.
    trip_count: int = 0
    hour_histogram: list[int] = Field(default_factory=list)


# ── groups and tags ───────────────────────────────────────
class GroupIn(BaseModel):
    model_config = Strict
    name: str
    color: str | None = None


class GroupOut(BaseModel):
    id: UUID
    name: str
    kind: str
    color: str | None
    trip_count: int = 0
    # Counted with the same inheritance rule the members list uses: a place with
    # no group of its own belongs to its trip's group. Two different rules would
    # put a number on screen that the list below it contradicts.
    place_count: int = 0


class TagIn(BaseModel):
    model_config = Strict
    name: str
    color: str | None = None


class TagOut(BaseModel):
    id: UUID
    name: str
    color: str | None
    trip_count: int = 0
    place_count: int = 0


class BulkAssign(BaseModel):
    model_config = Strict
    trip_ids: list[UUID] = Field(default_factory=list)
    place_ids: list[UUID] = Field(default_factory=list)
    group_id: UUID | None = None
    add_tags: list[UUID] = Field(default_factory=list)
    remove_tags: list[UUID] = Field(default_factory=list)


class TripPatch(BaseModel):
    """Metadata only. Trip CONTENT is produced by the algorithms and cannot be
    edited (P7); the correction endpoints exist but return 501."""

    model_config = Strict
    title: str | None = None
    group_id: UUID | None = None
    tag_ids: list[UUID] | None = None


# ── commute ───────────────────────────────────────────────
class CommuteAction(BaseModel):
    model_config = Strict
    trip_ids: list[UUID]
    action: Literal["collapse", "to_normal", "delete"]


# ── settings and fences ───────────────────────────────────
class SettingsIn(BaseModel):
    model_config = Strict
    cluster_radius_m: float | None = Field(default=None, ge=10, le=2000)
    cluster_min_dwell_s: int | None = Field(default=None, ge=60, le=86400)
    cluster_gap_s: int | None = Field(default=None, ge=300, le=86400)
    accuracy_max_m: float | None = Field(default=None, ge=10, le=5000)
    default_tz: str | None = None
    geocoding_enabled: bool | None = None
    photo_infer_tolerance_s: int | None = Field(default=None, ge=300, le=10800)
    # How many times an origin-destination pair must repeat before it counts as
    # a commute. Was a module constant in pipeline/commute.py; the commute page
    # offers "wrong call? adjust the parameters", which needs it tunable.
    commute_min_repeats: int | None = Field(default=None, ge=3, le=60)
    # Display only: timestamps are stored as UTC plus a zone name, always.
    display_local_time: bool | None = None


class GeofenceIn(BaseModel):
    model_config = Strict
    kind: Literal["home", "work"]
    label: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_m: float = Field(default=500, ge=50, le=20000)
    enabled: bool = True


class GeofenceOut(BaseModel):
    id: UUID
    kind: str
    label: str
    lat: float
    lon: float
    radius_m: float
    enabled: bool
    visit_count: int | None = None
    first_visit_utc: datetime | None = None
    last_visit_utc: datetime | None = None


# ── export ────────────────────────────────────────────────
class FenceCheckRequest(BaseModel):
    model_config = Strict
    trip_ids: list[UUID] = Field(default_factory=list)
    place_ids: list[UUID] = Field(default_factory=list)


class FenceHit(BaseModel):
    fence_id: UUID
    label: str
    kind: str
    affected_places: int
    affected_tracks: int


class FenceCheckResponse(BaseModel):
    intersects: bool
    fences: list[FenceHit] = Field(default_factory=list)
    affected_places: int = 0
    affected_tracks: int = 0


class ExportContents(BaseModel):
    """Which layers the image carries. Everything on except place labels."""

    model_config = Strict
    tracks: bool = True
    places: bool = True
    photos: bool = True
    labels: bool = False
    stats: bool = True


class ExportRequest(BaseModel):
    model_config = Strict
    trip_ids: list[UUID] = Field(default_factory=list)
    place_ids: list[UUID] = Field(default_factory=list)
    template: Literal["map", "poster", "collage"] = "map"
    width: int = Field(default=1080, ge=200, le=6000)
    height: int = Field(default=1920, ge=200, le=6000)
    theme: Literal["light", "dark"] = "light"
    # 'none' renders on transparency and draws no basemap credit - there is no
    # basemap to credit. Every other value keeps the credit, always.
    basemap: Literal["light", "dark", "terrain", "none"] = "light"
    contents: ExportContents = Field(default_factory=ExportContents)
    # Snaps every coordinate to a city-scale grid. Grid snapping, never noise:
    # noise averages out across several exports of the same trip.
    coarsen_to_city: bool = False
    title: str | None = Field(default=None, max_length=120)
    subtitle: str | None = Field(default=None, max_length=160)
    # Required whenever the scope intersects a fence. Missing -> 422, refused
    # server-side. A frontend dialog can be bypassed; this cannot.
    #
    # The dict form is per fence: {fence_id: action}. A fence that is hit but
    # absent from the dict is also a 422 - defaulting it to 'blur' would decide
    # a privacy question on the user's behalf.
    fence_actions: Literal["blur", "remove"] | dict[UUID, Literal["blur", "remove"]] | None = None


# ── overview ──────────────────────────────────────────────
class OverviewRow(BaseModel):
    """One country or city in the overview.

    `key` is None for the "no place name" row: places whose reverse geocoding
    never ran, or produced nothing. They are reported rather than dropped -
    dropping them makes the rows stop adding up to the totals in the header.

    `distance_m` sums the trips attributed to this row. A trip that crossed a
    border is counted once per country, so the rows deliberately add up to MORE
    than the overall total; the page says so.
    """

    key: str | None
    label: str | None
    country: str | None = None
    city_count: int = 0
    trip_count: int = 0
    photo_count: int = 0
    distance_m: float = 0
    first_day: date | None = None
    last_day: date | None = None
