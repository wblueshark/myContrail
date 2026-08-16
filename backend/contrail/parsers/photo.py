"""Photo EXIF extraction.

Hard rules, all measured rather than assumed:

* NEVER use macOS Spotlight (`mdls`) or filesystem metadata as a substitute.
  kMDItemContentCreationDate was measured 13 HOURS away from EXIF
  DateTimeOriginal on this machine. EXIF must be parsed directly.
* exifread's tag names differ from the EXIF specification:
      GPSDateStamp         (0x001D) -> "GPS GPSDate"
      GPSHPositioningError (0x001F) -> unnamed; must be read as "GPS Tag 0x001F"
  That last one matters: horizontal accuracy is precisely the advantage a photo
  has over the Google timeline (which has no accuracy field at all), and it is
  the one tag exifread refuses to name.
* GPSLatitude = 0, GPSLongitude = 0 is the Gulf of Guinea, i.e. "no fix". Taking
  it literally piles points onto the west coast of Africa.
* Some Android models write GPSTimeStamp as LOCAL time instead of UTC. Detect
  it: if |GPSDateTime - DateTimeOriginal| equals the zone offset the pair is
  consistent; if it is 0, the GPS clock was written local and needs correcting.

Measured on the four real iPhone samples in Sample/Photo: every one carries
DateTimeOriginal, OffsetTimeOriginal, GPSDateStamp+GPSTimeStamp and
GPSHPositioningError, and the two time sources agree to within one second. For
iPhone photos, levels 3-6 of the fallback chain are effectively dead code - but
they still have to exist for everything else.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from contrail.core.geo import is_valid_coord
from contrail.core.timezones import tz_at, zone
from contrail.parsers.base import ParsedItem, ParserMatch, RawPointDTO

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".dng"}

# tz_source values, ordered by how much they can be trusted.
TZ_EXIF_OFFSET = "exif_offset"
TZ_GPS_LOOKUP = "gps_lookup"
TZ_NEAREST_TRACK = "nearest_track"
TZ_USER_DEFAULT = "user_default"
TZ_FILE_MTIME = "file_mtime"


@dataclass(slots=True)
class PhotoMeta:
    path: Path
    lat: float | None = None
    lon: float | None = None
    altitude_m: float | None = None
    accuracy_m: float | None = None
    speed_mps: float | None = None
    heading_deg: float | None = None
    ts_utc: datetime | None = None
    taken_at_local: datetime | None = None
    tz_name: str | None = None
    tz_source: str | None = None
    location_confidence: str | None = None
    width: int | None = None
    height: int | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    # Set when only a naive local timestamp could be recovered. The pipeline
    # finishes the job with a nearby track point or the user's default zone
    # (levels 4 and 5 of the fallback chain).
    unresolved_local: datetime | None = None

    @property
    def has_position(self) -> bool:
        return self.lat is not None and self.lon is not None


def _ratio(value: Any) -> float | None:
    try:
        return float(value.num) / float(value.den) if value.den else None
    except AttributeError:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def _dms_to_degrees(values: Any, ref: str | None) -> float | None:
    try:
        parts = [_ratio(v) for v in values]
    except TypeError:
        return None
    if len(parts) < 2 or any(p is None for p in parts):
        return None
    deg = parts[0] + parts[1] / 60.0 + (parts[2] / 3600.0 if len(parts) > 2 else 0.0)
    if ref and ref.upper().startswith(("S", "W")):
        deg = -deg
    return deg


def _parse_exif_datetime(text: str | None) -> datetime | None:
    if not text:
        return None
    text = text.strip().replace("/", ":")
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def _parse_offset(text: str | None) -> timedelta | None:
    """EXIF 2.31+ OffsetTimeOriginal, e.g. '+09:00'."""
    if not text:
        return None
    text = text.strip()
    if len(text) < 6 or text[0] not in "+-":
        return None
    try:
        hours, minutes = int(text[1:3]), int(text[4:6])
    except ValueError:
        return None
    delta = timedelta(hours=hours, minutes=minutes)
    return -delta if text[0] == "-" else delta


def _read_tags(path: Path) -> dict[str, Any]:
    """exifread for everything it can handle; pillow-heif for HEIC containers,
    where the EXIF lives inside a metadata box exifread cannot reach."""
    import exifread

    with path.open("rb") as fh:
        tags = exifread.process_file(fh, details=False)
    if tags:
        return {k: v for k, v in tags.items()}

    if path.suffix.lower() in {".heic", ".heif"}:
        return _read_heic_tags(path)
    return {}


def _read_heic_tags(path: Path) -> dict[str, Any]:
    import io

    import exifread
    import pillow_heif

    heif = pillow_heif.open_heif(str(path), convert_hdr_to_8bit=False)
    blob = (heif.info or {}).get("exif")
    if not blob:
        return {}
    # The blob may or may not carry the "Exif\0\0" preamble.
    if blob[:6] == b"Exif\x00\x00":
        blob = blob[6:]
    return dict(exifread.process_file(io.BytesIO(blob), details=False))


class ExifParser:
    """Registry entry for image files.

    Photos do not become raw_point rows - they become `photo` rows, which carry
    their own place intelligence (04-data-contract section 8.5). `parse` exists
    to satisfy the parser protocol; the photo pipeline calls extract() directly.
    """

    source_kind = "photo"

    def __init__(self, variant: str = "exif") -> None:
        self.variant = variant

    @classmethod
    def sniff(cls, path: Path, head: bytes) -> ParserMatch | None:
        if path.suffix.lower() in IMAGE_SUFFIXES:
            return ParserMatch(cls, 0.9, "exif", cls.source_kind)
        if head[:3] == b"\xff\xd8\xff" or head[4:12] == b"ftypheic":
            return ParserMatch(cls, 0.95, "exif", cls.source_kind)
        return None

    def parse(self, path: Path) -> Iterator[ParsedItem]:
        meta = extract(path)
        if meta.has_position and meta.ts_utc:
            yield RawPointDTO(
                ts_utc=meta.ts_utc,
                lat=meta.lat,
                lon=meta.lon,
                altitude_m=meta.altitude_m,
                accuracy_m=meta.accuracy_m,
                speed_mps=meta.speed_mps,
                heading_deg=meta.heading_deg,
                confidence="measured",
                tz_name=meta.tz_name,
            )


def extract(path: Path) -> PhotoMeta:
    """Read one photo's metadata. Never raises for a malformed file: a photo we
    cannot read is still a photo, it just has no position."""
    meta = PhotoMeta(path=path)
    try:
        tags = _read_tags(path)
    except Exception:  # noqa: BLE001 - a corrupt file must not abort a 100k-photo import
        tags = {}

    def text(key: str) -> str | None:
        value = tags.get(key)
        return str(value) if value is not None else None

    meta.camera_make = text("Image Make")
    meta.camera_model = text("Image Model")
    for key in ("EXIF ExifImageWidth", "Image ImageWidth"):
        if tags.get(key) is not None:
            meta.width = int(str(tags[key]))
            break
    for key in ("EXIF ExifImageLength", "Image ImageLength"):
        if tags.get(key) is not None:
            meta.height = int(str(tags[key]))
            break
    # Orientation 5-8 mean the image is stored rotated by 90 degrees.
    orientation = text("Image Orientation") or ""
    if "90" in orientation or "270" in orientation:
        meta.width, meta.height = meta.height, meta.width

    # ── position ──────────────────────────────────────────
    lat = _dms_to_degrees(
        getattr(tags.get("GPS GPSLatitude"), "values", None), text("GPS GPSLatitudeRef")
    )
    lon = _dms_to_degrees(
        getattr(tags.get("GPS GPSLongitude"), "values", None), text("GPS GPSLongitudeRef")
    )
    if lat is not None and lon is not None and is_valid_coord(lat, lon):
        meta.lat, meta.lon = lat, lon
        meta.location_confidence = "measured"

        altitude = _ratio(getattr(tags.get("GPS GPSAltitude"), "values", [None])[0])
        if altitude is not None:
            ref = text("GPS GPSAltitudeRef") or "0"
            meta.altitude_m = -altitude if ref.strip().startswith("1") else altitude

        # exifread does not name GPSHPositioningError; read it by tag number.
        accuracy = tags.get("GPS Tag 0x001F")
        if accuracy is not None:
            meta.accuracy_m = _ratio(getattr(accuracy, "values", [None])[0])

        speed = _ratio(getattr(tags.get("GPS GPSSpeed"), "values", [None])[0])
        if speed is not None:
            unit = (text("GPS GPSSpeedRef") or "K").strip().upper()
            factor = {"K": 1000 / 3600, "M": 1609.344 / 3600, "N": 1852 / 3600}.get(unit, 1.0)
            meta.speed_mps = speed * factor
        meta.heading_deg = _ratio(getattr(tags.get("GPS GPSImgDirection"), "values", [None])[0])

    # ── time, strictly by the fallback chain ──────────────
    local_naive = _parse_exif_datetime(
        text("EXIF DateTimeOriginal") or text("Image DateTime") or text("EXIF DateTimeDigitized")
    )
    meta.taken_at_local = local_naive
    offset = _parse_offset(text("EXIF OffsetTimeOriginal") or text("EXIF OffsetTime"))

    gps_utc = _gps_datetime(tags, text)
    if gps_utc is not None and local_naive is not None:
        gps_utc = _correct_android_local_gps_clock(gps_utc, local_naive, offset, meta)

    if gps_utc is not None:
        # Level 1: GPS date + time is UTC straight from the satellites.
        meta.ts_utc = gps_utc
        if offset is not None:
            meta.tz_name = _fixed_zone_name(offset)
            meta.tz_source = TZ_EXIF_OFFSET
        elif meta.has_position:
            meta.tz_name = tz_at(meta.lat, meta.lon)
            meta.tz_source = TZ_GPS_LOOKUP
        if meta.taken_at_local is None and meta.tz_name:
            meta.taken_at_local = gps_utc.astimezone(zone(meta.tz_name)).replace(tzinfo=None)

    elif local_naive is not None and offset is not None:
        # Level 2: local time plus a declared offset.
        meta.ts_utc = (local_naive - offset).replace(tzinfo=UTC)
        meta.tz_name = _fixed_zone_name(offset)
        meta.tz_source = TZ_EXIF_OFFSET

    elif local_naive is not None and meta.has_position:
        # Level 3: local time plus a zone resolved offline from the coordinates.
        tz_name = tz_at(meta.lat, meta.lon)
        meta.tz_name = tz_name
        meta.tz_source = TZ_GPS_LOOKUP
        meta.ts_utc = local_naive.replace(tzinfo=zone(tz_name)).astimezone(UTC)

    elif local_naive is not None:
        # Levels 4-5 need the database (nearest track point, then the user's
        # default zone). Hand the naive value back and let the pipeline finish.
        meta.unresolved_local = local_naive

    else:
        # Level 6: file mtime. Explicitly low confidence.
        try:
            meta.ts_utc = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            meta.tz_source = TZ_FILE_MTIME
        except OSError:
            pass

    return meta


def _gps_datetime(tags: dict[str, Any], text) -> datetime | None:
    """GPSDateStamp + GPSTimeStamp -> UTC. exifread calls the date tag
    'GPS GPSDate', not 'GPS GPSDateStamp'."""
    date_text = text("GPS GPSDate") or text("GPS GPSDateStamp")
    time_tag = tags.get("GPS GPSTimeStamp")
    if not date_text or time_tag is None:
        return None
    try:
        parts = [_ratio(v) for v in time_tag.values]
        year, month, day = (int(p) for p in date_text.strip().replace("-", ":").split(":")[:3])
    except (AttributeError, TypeError, ValueError):
        return None
    if len(parts) < 3 or any(p is None for p in parts):
        return None
    hour, minute = int(parts[0]), int(parts[1])
    second = int(parts[2])
    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=UTC)
    except ValueError:
        return None


def _correct_android_local_gps_clock(
    gps_utc: datetime, local_naive: datetime, offset: timedelta | None, meta: PhotoMeta
) -> datetime:
    """Some Android models write GPSTimeStamp in local time.

    Test: the gap between GPS time and DateTimeOriginal should equal the zone
    offset. A gap of ~0 in a zone that is not UTC means the GPS clock was
    written local, so it has to be shifted back.
    """
    gap = (local_naive - gps_utc.replace(tzinfo=None)).total_seconds()
    expected = offset.total_seconds() if offset is not None else None
    if expected is None and meta.has_position:
        tz_name = tz_at(meta.lat, meta.lon)
        expected = zone(tz_name).utcoffset(local_naive).total_seconds()
    if expected is None or abs(expected) < 60:
        return gps_utc
    if abs(gap) < 120 <= abs(expected):
        return gps_utc - timedelta(seconds=expected)
    return gps_utc


def _fixed_zone_name(offset: timedelta) -> str:
    total = int(offset.total_seconds())
    if total == 0:
        return "UTC"
    sign = "+" if total > 0 else "-"
    total = abs(total)
    return f"UTC{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}"
