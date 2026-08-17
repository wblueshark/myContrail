"""Shared test fixtures.

Tests that need PostGIS skip themselves when no database is reachable, so the
pure-algorithm suite still runs anywhere. The privacy regression test is the one
exception worth calling out: it is a CI blocking item, and a CI run where it
SKIPPED is not a passing run. check_db_required() exists for the pipeline to
assert that.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "Sample"


@pytest.fixture(scope="session")
def sample_dir() -> Path:
    return SAMPLE_DIR


@pytest.fixture(scope="session")
def has_samples() -> bool:
    return SAMPLE_DIR.exists()


def utc(year=2024, month=5, day=3, hour=0, minute=0, second=0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def minutes(n: float) -> timedelta:
    return timedelta(minutes=n)


@pytest.fixture(scope="session")
def database_url() -> str | None:
    """The DSN for PostGIS-backed tests, or None to skip them."""
    from contrail.config import get_settings

    url = os.environ.get("CONTRAIL_TEST_DATABASE_URL") or get_settings().database_url
    return url.replace("postgresql+psycopg://", "postgresql://") if url else None


@pytest.fixture(scope="session")
def pg_conn(database_url):
    """A live PostGIS connection with the fence functions installed."""
    if not database_url:
        pytest.skip("no database configured")
    psycopg = pytest.importorskip("psycopg")
    try:
        conn = psycopg.connect(database_url, connect_timeout=3)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    conn.autocommit = True
    with conn.cursor() as cur:
        # Counted rather than resolved by name: to_regproc() returns NULL for an
        # AMBIGUOUS name, and the fence functions are overloaded (per-fence forms
        # were added in 0002). Probing with to_regproc would silently skip this
        # entire file - the one file whose docstring says skipping is not a pass.
        cur.execute("SELECT count(*) > 0 FROM pg_proc WHERE proname = 'contrail_fence_remove'")
        if not cur.fetchone()[0]:
            pytest.skip("fence functions not installed; run alembic upgrade head")
    yield conn
    conn.close()
