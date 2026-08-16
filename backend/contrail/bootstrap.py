"""First-run bootstrap: the single local user and the default groups."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from contrail.db import session_scope
from contrail.models import AppUser, Group

LOCAL_USER_EMAIL = "local@contrail.invalid"
SYSTEM_COMMUTE_GROUP = "Commute"

_cached_user_id: uuid.UUID | None = None


async def get_local_user_id() -> uuid.UUID:
    """Return (creating on first call) the MVP's single user.

    The user_id foreign keys exist everywhere already; multi-user mode only
    needs a real authentication middleware, not a data-model change.
    """
    global _cached_user_id
    if _cached_user_id is not None:
        return _cached_user_id

    async with session_scope() as session:
        user = (
            await session.execute(select(AppUser).where(AppUser.email == LOCAL_USER_EMAIL))
        ).scalar_one_or_none()
        if user is None:
            user = AppUser(email=LOCAL_USER_EMAIL, display_name="Local", default_tz="UTC")
            session.add(user)
            await session.flush()
            # The commute group is created by the system and cannot be deleted.
            session.add(
                Group(user_id=user.id, name=SYSTEM_COMMUTE_GROUP, kind="system_commute")
            )
        _cached_user_id = user.id
    return _cached_user_id


def reset_cache() -> None:
    """Test hook."""
    global _cached_user_id
    _cached_user_id = None
