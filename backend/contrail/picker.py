"""Native directory picker and the one-shot pick_token registry.

The security model here is structural, not defensive:

    the path the user chooses NEVER appears in any HTTP request

    frontend                backend                     macOS
    ---------------------------------------------------------------
    [choose folder] --POST /fs/pick-->
                            opens the native chooser --> Finder
                            <--------- user picks a folder --------+
                            stores the absolute path in a
                            process-memory, one-shot table
    <-- { pick_token, display_name, prescan }
    POST /imports { pick_token, options }     <- no path field, ever

What this actually stops:

  path traversal (../../etc)   structurally impossible - the request has no
                               path field to poison
  DNS rebinding / CSRF         the worst outcome is a Finder dialog the user did
                               not ask for. The attacker cannot choose what gets
                               scanned; a user seeing an unexpected dialog
                               cancels it
  scanning something huge      still possible by mistake, which is why the
                               prescan returns a file count and time estimate
                               and the UI asks again above a threshold

The registry lives in this process's memory only: never written to a database,
never written to a log, and gone on restart. This is also why photo imports run
in-process rather than through the ARQ worker - handing the path to a worker
would mean serialising it through Redis.
"""

from __future__ import annotations

import platform
import secrets
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

TOKEN_TTL_S = 1800  # 30 minutes, or one use - whichever comes first
PICKER_TIMEOUT_S = 300


@dataclass(slots=True)
class Pick:
    path: Path
    display_name: str
    created_at: float


# token -> Pick. Process memory only.
_PICKS: dict[str, Pick] = {}


def picker_available() -> bool:
    """A native chooser requires a GUI session on the host.

    Not available in a container, which is one of the reasons this product is
    installed natively: without it, photo import has no entry point at all.
    """
    return platform.system() == "Darwin"


def open_native_picker(prompt: str = "Choose a photo folder to import") -> Path | None:
    """Block until the user picks a folder or cancels. None means cancelled.

    Reading ~/Pictures, ~/Desktop or ~/Documents triggers macOS TCC. Whether the
    grant implied by choosing a folder in the native dialog extends to reading
    its contents has to be confirmed on a real machine; if it does not, the user
    must add the host process under Full Disk Access.
    """
    if not picker_available():
        return None
    script = f'POSIX path of (choose folder with prompt "{prompt}")'
    try:
        completed = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=PICKER_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    if completed.returncode != 0:
        return None  # user cancelled
    chosen = completed.stdout.strip()
    if not chosen:
        return None
    path = Path(chosen)
    return path if path.is_dir() else None


def register(path: Path) -> tuple[str, str]:
    """Store a picked path and return (pick_token, display_name).

    display_name is the LAST path component only. The absolute path is never
    returned to the client - not in the pick response, not in a photo record.
    """
    _expire()
    token = secrets.token_urlsafe(16)  # 128 bits
    display_name = path.name or str(path)
    _PICKS[token] = Pick(path=path, display_name=display_name, created_at=time.monotonic())
    return token, display_name


def peek(token: str) -> Path | None:
    """Resolve without consuming - used by prescan, which runs before import."""
    _expire()
    pick = _PICKS.get(token)
    return pick.path if pick else None


def consume(token: str) -> Path | None:
    """Resolve and invalidate. Called once, when the import actually starts."""
    _expire()
    pick = _PICKS.pop(token, None)
    return pick.path if pick else None


def display_name(token: str) -> str | None:
    pick = _PICKS.get(token)
    return pick.display_name if pick else None


def _expire() -> None:
    now = time.monotonic()
    for token in [t for t, p in _PICKS.items() if now - p.created_at > TOKEN_TTL_S]:
        _PICKS.pop(token, None)
