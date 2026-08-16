"""Format parsers.

Every parser implements the same contract and yields items lazily. Nothing here
may accumulate a whole file in memory: Google exports reach gigabyte scale.
"""

from contrail.parsers.base import (
    ParsedItem,
    Parser,
    ParserMatch,
    PlaceHint,
    RawPointDTO,
    SkipNote,
    TrackHint,
    UnknownFormatError,
)
from contrail.parsers.registry import REGISTRY, sniff

__all__ = [
    "ParsedItem",
    "Parser",
    "ParserMatch",
    "PlaceHint",
    "RawPointDTO",
    "SkipNote",
    "TrackHint",
    "UnknownFormatError",
    "REGISTRY",
    "sniff",
]
