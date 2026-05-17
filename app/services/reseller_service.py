from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Reseller


async def get_reseller(session: AsyncSession, telegram_id: int) -> Reseller | None:
    return await session.scalar(select(Reseller).where(Reseller.telegram_id == telegram_id))


async def is_active_reseller(session: AsyncSession, telegram_id: int) -> bool:
    reseller = await get_reseller(session, telegram_id)
    return bool(reseller and reseller.is_active)


async def add_reseller(session: AsyncSession, telegram_id: int, name: str | None = None) -> Reseller:
    reseller = await get_reseller(session, telegram_id)
    if reseller:
        reseller.name = name or reseller.name
        reseller.is_active = True
        return reseller
    reseller = Reseller(telegram_id=telegram_id, name=name, is_active=True)
    session.add(reseller)
    await session.flush()
    return reseller


async def set_reseller_active(session: AsyncSession, telegram_id: int, active: bool) -> bool:
    reseller = await get_reseller(session, telegram_id)
    if not reseller:
        return False
    reseller.is_active = active
    return True


async def list_resellers(session: AsyncSession, limit: int = 30) -> list[Reseller]:
    result = await session.scalars(select(Reseller).order_by(Reseller.id.desc()).limit(limit))
    return list(result)
