"""API contract tests that need no database.

The important one: no import-related request body may carry a filesystem path,
and the schema must reject one rather than ignore it.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from contrail.schemas import ExportRequest, ImportRequest, PrescanRequest
from contrail.security import reject_path_fields


@pytest.mark.parametrize(
    "field", ["path", "directory", "root", "scan_path", "abs_path"]
)
def test_path_fields_are_rejected_outright(field):
    """Path traversal is impossible by construction: there is no path field to
    poison. A request that supplies one is a 400, not a sanitisation problem."""
    with pytest.raises(HTTPException) as caught:
        reject_path_fields({field: "/Users/someone/Pictures/../../etc"})
    assert caught.value.status_code == 400


def test_clean_payloads_pass():
    reject_path_fields({"pick_token": "abc", "group_id": None})
    reject_path_fields(None)


def test_import_schema_forbids_unknown_fields():
    ImportRequest(source_ref="tok", kind="photo")
    with pytest.raises(ValidationError):
        ImportRequest(source_ref="tok", kind="photo", path="/Users/someone/Pictures")


def test_prescan_schema_forbids_unknown_fields():
    PrescanRequest(pick_token="tok")
    with pytest.raises(ValidationError):
        PrescanRequest(path="/Users/someone/Pictures")


def test_export_request_defaults_to_no_fence_action():
    """fence_actions is absent by default, so an export whose scope intersects a
    fence is refused unless the caller made an explicit choice."""
    request = ExportRequest(trip_ids=[])
    assert request.fence_actions is None


def test_export_request_only_accepts_the_two_policies():
    assert ExportRequest(fence_actions="blur").fence_actions == "blur"
    assert ExportRequest(fence_actions="remove").fence_actions == "remove"
    with pytest.raises(ValidationError):
        ExportRequest(fence_actions="ignore")


def test_capabilities_hide_unavailable_features_rather_than_erroring():
    """An unavailable capability must be reported as unavailable so the UI omits
    the entry point entirely - never renders one that fails when clicked."""
    from contrail.config import CAPABILITIES

    assert CAPABILITIES["local"]["directory_picker"] == "native"
    assert CAPABILITIES["cloud"]["directory_picker"] is None
    # serve_original is permanently False: after import the original directory
    # is never read again, so the product holds no originals to serve.
    assert CAPABILITIES["local"]["serve_original"] is False
    assert CAPABILITIES["cloud"]["serve_original"] is False


def test_photo_output_never_exposes_an_absolute_path():
    """orig_path exists in the database for the user's own reference, and must
    not be reachable over HTTP."""
    from contrail.schemas import PhotoOut

    assert "orig_path" not in PhotoOut.model_fields
    assert "orig_filename" in PhotoOut.model_fields


def test_pick_token_registry_is_single_use():
    from pathlib import Path

    from contrail import picker

    token, name = picker.register(Path("/tmp/example-folder"))
    assert name == "example-folder"
    # Prescan may look without consuming...
    assert picker.peek(token) is not None
    assert picker.peek(token) is not None
    # ...but the import consumes it, and a replay fails.
    assert picker.consume(token) is not None
    assert picker.consume(token) is None
    assert picker.peek(token) is None


def test_log_redaction_never_emits_a_usable_position():
    """Coordinates are never logged. geohash4 is ~20 km: enough to tell two
    continents apart, useless for locating anyone."""
    from contrail.logging_config import redact_position

    redacted = redact_position(35.681236, 139.767125)
    assert "35.68" not in redacted and "139.76" not in redacted
    assert redacted.startswith("gh4:") and len(redacted) == 8
