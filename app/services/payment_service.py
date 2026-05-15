from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.repositories import get_setting


class PaymentService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def price_per_gb(self, session: AsyncSession) -> int:
        return int(await get_setting(session, "price_per_gb_toman", str(self.settings.price_per_gb_toman)))

    async def card_number(self, session: AsyncSession) -> str:
        return await get_setting(session, "card_number", self.settings.card_number)

    async def support_username(self, session: AsyncSession) -> str:
        return await get_setting(session, "support_username", self.settings.support_username)

    async def min_custom_gb(self, session: AsyncSession) -> int:
        return int(await get_setting(session, "min_custom_gb", str(self.settings.min_custom_gb)))

    async def max_custom_gb(self, session: AsyncSession) -> int:
        return int(await get_setting(session, "max_custom_gb", str(self.settings.max_custom_gb)))

