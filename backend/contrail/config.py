"""Runtime configuration and capability declaration.

Both run modes share one codebase; the differences are confined to two places:
the capability declaration below and the file-access layer (see storage.py).

v2.3: there is deliberately NO `allowed_scan_roots` setting. The system never
persists a scan root, which makes "the original directory is read exactly once"
a structural guarantee rather than a promise. See docs/design/05-architecture
section 3.1.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Run mode ──────────────────────────────────────────
    mode: Literal["local", "cloud"] = Field("local", validation_alias="CONTRAIL_MODE")
    enable_auth: bool = Field(False, validation_alias="CONTRAIL_ENABLE_AUTH")
    storage_backend: Literal["fs", "s3"] = Field("fs", validation_alias="CONTRAIL_STORAGE_BACKEND")

    # ── Infrastructure ────────────────────────────────────
    database_url: str = Field(
        "postgresql+psycopg://localhost:5432/mycontrail", validation_alias="DATABASE_URL"
    )
    redis_url: str = Field("redis://localhost:6379/0", validation_alias="REDIS_URL")
    data_dir: Path = Field(ROOT / "data", validation_alias="CONTRAIL_DATA_DIR")

    # ── Mapbox ────────────────────────────────────────────
    mapbox_token: str = Field("", validation_alias="MAPBOX_TOKEN")

    # ── Local-mode security ───────────────────────────────
    # Binding to 127.0.0.1 is NOT enough. All four guards from
    # 05-architecture section 10 are required.
    local_token: str = Field("", validation_alias="CONTRAIL_LOCAL_TOKEN")
    allowed_origins: str = Field(
        "http://localhost:5173,http://127.0.0.1:5173", validation_alias="CONTRAIL_ALLOWED_ORIGINS"
    )
    allowed_hosts: str = Field(
        "localhost,127.0.0.1,[::1],::1", validation_alias="CONTRAIL_ALLOWED_HOSTS"
    )

    # ── Privacy ───────────────────────────────────────────
    # When off, no reverse-geocoding request ever leaves this machine.
    geocoding_enabled: bool = Field(True, validation_alias="CONTRAIL_GEOCODING_ENABLED")

    # ── Derivation defaults (overridable per user in app_user.settings) ──
    cluster_radius_m: float = 150.0
    cluster_min_dwell_s: int = 900
    cluster_gap_s: int = 3600
    cluster_max_inferred_stay_s: int = 86400
    accuracy_max_m: float = 500.0
    photo_infer_tolerance_s: int = 1800

    @field_validator("data_dir")
    @classmethod
    def _resolve_data_dir(cls, v: Path) -> Path:
        p = Path(v).expanduser()
        return p if p.is_absolute() else (ROOT / p).resolve()

    @property
    def sync_database_url(self) -> str:
        """Alembic runs synchronously; the psycopg3 dialect serves both."""
        return self.database_url

    @property
    def async_database_url(self) -> str:
        return self.database_url

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def hosts(self) -> set[str]:
        return {h.strip().lower() for h in self.allowed_hosts.split(",") if h.strip()}


# MVP ships "local" only. `serve_original` is permanently False: after import
# the product never touches the source directory again, so it holds no originals.
CAPABILITIES: dict[str, dict[str, object]] = {
    "local": {
        "scan_local_path": True,
        "directory_picker": "native",
        "serve_original": False,
        "multi_user": False,
        "sharing": False,
    },
    "cloud": {
        "scan_local_path": False,
        "directory_picker": None,
        "serve_original": False,
        "multi_user": True,
        "sharing": False,
    },
}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s


def resolve_local_token(settings: Settings) -> str:
    """Return the local API token, generating ~/.contrail/token on first start.

    Guards against other processes on this machine calling the API. Nearly free,
    and it removes the bulk of the local attack surface.
    """
    if settings.local_token:
        return settings.local_token
    token_path = Path.home() / ".contrail" / "token"
    if token_path.exists():
        existing = token_path.read_text().strip()
        if existing:
            return existing
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    token_path.write_text(token + "\n")
    token_path.chmod(0o600)
    return token
