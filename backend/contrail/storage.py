"""Object storage abstraction.

One of the two places where local and cloud mode differ (the other is the
capability declaration). Keys are stored as full URIs - "fs://thumbs/ab/cd.webp"
- so a later migration to S3 does not require rewriting every row.

On encryption: the design calls for AES-256-GCM on retained originals and
thumbnails. That is a CLOUD-mode requirement, where the bucket may be
misconfigured or the backup may walk. In local mode the threat model is a stolen
laptop, which FileVault/LUKS volume encryption already covers, and adding a
`cryptography` dependency would extend the verified dependency set for no gain.
The cipher is therefore pluggable and defaults to a pass-through; wiring a real
AEAD in is a matter of implementing the two methods below.

Database coordinate columns are deliberately NOT encrypted at the application
layer: that would destroy the GiST index and turn every spatial query into
"decrypt the whole table, then filter". The trade-off is stated openly in
05-architecture section 8.1 - an attacker holding database credentials sees
coordinates in the clear.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Protocol

from contrail.config import get_settings


class Cipher(Protocol):
    def encrypt(self, data: bytes) -> bytes: ...
    def decrypt(self, data: bytes) -> bytes: ...


class NullCipher:
    """Local mode: rely on volume encryption rather than app-layer crypto."""

    def encrypt(self, data: bytes) -> bytes:
        return data

    def decrypt(self, data: bytes) -> bytes:
        return data


class FsStorage:
    """Local filesystem backend. Keys look like `fs://<bucket>/<path>`."""

    scheme = "fs"

    def __init__(self, root: Path | None = None, cipher: Cipher | None = None) -> None:
        self.root = Path(root or get_settings().data_dir)
        self.cipher = cipher or NullCipher()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, bucket: str, name: str) -> Path:
        path = (self.root / bucket / name).resolve()
        root = (self.root / bucket).resolve()
        # Defence in depth: bucket/name are internally generated, but a path
        # escaping the data directory must never be writable.
        if not str(path).startswith(str(root)):
            raise ValueError("storage key escapes the data directory")
        return path

    def put(self, bucket: str, name: str, data: bytes) -> str:
        path = self._path_for(bucket, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.cipher.encrypt(data))
        return f"{self.scheme}://{bucket}/{name}"

    def put_file(self, bucket: str, name: str, source: Path) -> str:
        """Copy a file in without reading it into memory (originals can be GB)."""
        path = self._path_for(bucket, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(self.cipher, NullCipher):
            shutil.copyfile(source, path)
        else:
            path.write_bytes(self.cipher.encrypt(source.read_bytes()))
        return f"{self.scheme}://{bucket}/{name}"

    def get(self, key: str) -> bytes:
        bucket, name = self.split(key)
        return self.cipher.decrypt(self._path_for(bucket, name).read_bytes())

    def exists(self, key: str) -> bool:
        try:
            bucket, name = self.split(key)
            return self._path_for(bucket, name).exists()
        except ValueError:
            return False

    def delete(self, key: str) -> None:
        try:
            bucket, name = self.split(key)
            self._path_for(bucket, name).unlink(missing_ok=True)
        except ValueError:
            pass

    def local_path(self, key: str) -> Path:
        bucket, name = self.split(key)
        return self._path_for(bucket, name)

    @staticmethod
    def split(key: str) -> tuple[str, str]:
        if "://" not in key:
            raise ValueError(f"malformed storage key: {key!r}")
        _, rest = key.split("://", 1)
        bucket, _, name = rest.partition("/")
        if not bucket or not name:
            raise ValueError(f"malformed storage key: {key!r}")
        return bucket, name


def sharded_name(digest: bytes, suffix: str) -> str:
    """ab/cd/abcdef... - keeps directories small at 100k+ photos."""
    hexed = digest.hex()
    return f"{hexed[:2]}/{hexed[2:4]}/{hexed}{suffix}"


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> bytes:
    """L1 dedup key. Streamed: source files reach gigabyte scale."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)
    return digest.digest()


_storage: FsStorage | None = None


def get_storage() -> FsStorage:
    global _storage
    if _storage is None:
        _storage = FsStorage()
    return _storage
