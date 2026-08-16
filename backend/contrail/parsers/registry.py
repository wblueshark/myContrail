"""Format sniffing registry.

Detection order: extension quick filter -> magic bytes -> structural probe,
reading at most 64 KB. A file that matches nothing raises UnknownFormatError
with the first 200 bytes preserved, so the failure can be diagnosed without
asking the user for the file again (P6).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from contrail.parsers.base import ParserMatch, UnknownFormatError
from contrail.parsers.google_legacy import GoogleRecordsParser, GoogleSemanticParser
from contrail.parsers.google_timeline import GoogleTimelineParser
from contrail.parsers.photo import ExifParser
from contrail.parsers.tracks import FitParser, GpxParser, TcxParser

HEAD_BYTES = 65_536

# Order matters only where two parsers could both claim a file; the highest
# confidence wins, and ties resolve by position here.
REGISTRY: list[type] = [
    GoogleTimelineParser,
    GoogleSemanticParser,
    GoogleRecordsParser,
    GpxParser,
    TcxParser,
    FitParser,
    ExifParser,
]

# Guards against zip bombs: both limits must hold.
MAX_ZIP_RATIO = 100
MAX_ZIP_TOTAL_BYTES = 20 * 1024**3


def sniff(path: Path) -> ParserMatch:
    """Identify a file's format. Raises UnknownFormatError if nothing matches."""
    with path.open("rb") as fh:
        head = fh.read(HEAD_BYTES)

    best: ParserMatch | None = None
    for parser_cls in REGISTRY:
        match = parser_cls.sniff(path, head)
        if match is not None and (best is None or match.confidence > best.confidence):
            best = match
    if best is None:
        raise UnknownFormatError(f"unrecognised format: {path.name}", head[:200])
    return best


def is_archive(path: Path) -> bool:
    return path.suffix.lower() == ".zip" and zipfile.is_zipfile(path)


def safe_zip_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Members that are safe to extract.

    Rejects absolute paths and `..` traversal (a zip is user-supplied data even
    in local mode), and refuses archives whose expansion ratio or total size
    looks like a decompression bomb.
    """
    total_uncompressed = 0
    total_compressed = 0
    members: list[zipfile.ZipInfo] = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in Path(name).parts:
            raise UnknownFormatError(f"unsafe path in archive: {info.filename}")
        total_uncompressed += info.file_size
        total_compressed += max(info.compress_size, 1)
        members.append(info)

    if total_uncompressed > MAX_ZIP_TOTAL_BYTES:
        raise UnknownFormatError("archive expands beyond the size limit")
    if total_compressed and total_uncompressed / total_compressed > MAX_ZIP_RATIO:
        raise UnknownFormatError("archive compression ratio looks like a zip bomb")
    return members
