"""API contract tests that need no database.

The important one: no import-related request body may carry a filesystem path,
and the schema must reject one rather than ignore it.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from contrail.schemas import (
    ExportRequest,
    GroupOut,
    ImportRequest,
    OverviewRow,
    PrescanRequest,
    SettingsIn,
    TagOut,
)
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


# ── redesign contracts (CR-004 / CR-005 / CR-006 / CR-007 / CR-008) ────────
def test_import_options_accept_the_full_wizard_set():
    """Every switch on step 3 of the wizard must survive validation."""
    request = ImportRequest(
        source_ref="tok",
        kind="photo",
        options={
            "include_subdirs": False,
            "infer_missing_gps": True,
            "infer_tolerance_s": 1800,
            "generate_thumbnails": False,
            "skip_duplicates": False,
            "date_range": {"start": "2024-05-01", "end": "2024-05-08"},
        },
    )
    assert request.options.include_subdirs is False
    assert request.options.infer_tolerance_s == 1800
    assert request.options.date_range is not None


def test_import_options_reject_a_path_smuggled_into_the_nested_object():
    """The nested object is `extra="forbid"` too - otherwise `options` would be
    the one place a path could ride along unnoticed."""
    with pytest.raises(ValidationError):
        ImportRequest(source_ref="tok", options={"path": "/Users/someone/Pictures"})


def test_reject_path_fields_walks_nested_bodies():
    with pytest.raises(HTTPException) as caught:
        reject_path_fields({"source_ref": "tok", "options": {"scan_path": "/etc"}})
    assert caught.value.status_code == 400


def test_prescan_carries_the_subfolder_choice():
    assert PrescanRequest(pick_token="tok").include_subdirs is True
    assert PrescanRequest(pick_token="tok", include_subdirs=False).include_subdirs is False


def test_export_request_accepts_a_per_fence_policy_map():
    """"Blur home, remove work" has to be expressible - one global choice cannot
    say it."""
    home = uuid.uuid4()
    work = uuid.uuid4()
    request = ExportRequest(fence_actions={home: "blur", work: "remove"})
    assert request.fence_actions == {home: "blur", work: "remove"}
    with pytest.raises(ValidationError):
        ExportRequest(fence_actions={home: "ignore"})


def test_export_request_defaults_keep_the_credit_and_the_full_layer_set():
    request = ExportRequest()
    assert request.basemap == "light"
    assert request.coarsen_to_city is False
    assert (request.contents.tracks, request.contents.places, request.contents.photos) == (
        True,
        True,
        True,
    )
    # Place labels are the one layer off by default: they crowd a small export.
    assert request.contents.labels is False


def test_settings_schema_bounds_the_new_tunables():
    assert SettingsIn(commute_min_repeats=12).commute_min_repeats == 12
    assert SettingsIn(display_local_time=False).display_local_time is False
    for bad in (2, 61):
        with pytest.raises(ValidationError):
            SettingsIn(commute_min_repeats=bad)


def test_settings_schema_refuses_a_mapbox_token():
    """The token lives in .env. Accepting one here would put a secret in the
    database and, sooner or later, in a log line."""
    with pytest.raises(ValidationError):
        SettingsIn(mapbox_token="pk.eyJ1Ijoi")


def test_overview_row_keeps_the_unnamed_bucket():
    """A place with no geocoded name is reported under a null key, never
    dropped: dropping it makes the rows disagree with the header totals."""
    row = OverviewRow(key=None, label=None, trip_count=3)
    assert row.key is None and row.trip_count == 3


def test_group_and_tag_outputs_carry_both_counts():
    group = GroupOut(id=uuid.uuid4(), name="Kyoto", kind="user", color=None)
    assert (group.trip_count, group.place_count) == (0, 0)
    tag = TagOut(id=uuid.uuid4(), name="photo", color=None, trip_count=2, place_count=5)
    assert (tag.trip_count, tag.place_count) == (2, 5)
