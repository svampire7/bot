from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.marzban.client import MarzbanClient
from app.marzban.schemas import MarzbanUser


async def create_vpn_account(
    marzban: MarzbanClient,
    username: str,
    quota_gb: int,
    expire_days: int | None = None,
) -> MarzbanUser:
    if expire_days is None:
        return await marzban.create_user(username, quota_gb)
    expire_at = datetime.now(timezone.utc) + timedelta(days=expire_days)
    await marzban.create_user(username, quota_gb)
    return await marzban.update_user(username, {"expire": int(expire_at.timestamp()), "status": "active"})
