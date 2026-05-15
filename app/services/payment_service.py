from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.repositories import get_setting


def parse_package_prices(value: str) -> list[tuple[int, int]]:
    packages: list[tuple[int, int]] = []
    for item in value.split(","):
        if not item.strip() or ":" not in item:
            continue
        gb_text, price_text = item.split(":", 1)
        gb = int(gb_text.strip())
        price = int(price_text.strip())
        if gb <= 0 or price <= 0:
            raise ValueError("Package GB and price must be positive")
        packages.append((gb, price))
    if not packages:
        raise ValueError("At least one package is required")
    return sorted(packages, key=lambda item: item[0])


def format_package_prices(packages: list[tuple[int, int]]) -> str:
    return ",".join(f"{gb}:{price}" for gb, price in packages)


class PaymentService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def price_per_gb(self, session: AsyncSession) -> int:
        return int(await get_setting(session, "price_per_gb_toman", str(self.settings.price_per_gb_toman)))

    async def package_prices(self, session: AsyncSession) -> list[tuple[int, int]]:
        value = await get_setting(session, "package_prices_toman", self.settings.package_prices_toman)
        return parse_package_prices(value)

    async def package_price(self, session: AsyncSession, gb: int) -> int | None:
        return dict(await self.package_prices(session)).get(gb)

    async def card_number(self, session: AsyncSession) -> str:
        return await get_setting(session, "card_number", self.settings.card_number)

    async def support_username(self, session: AsyncSession) -> str:
        return await get_setting(session, "support_username", self.settings.support_username)

    async def min_custom_gb(self, session: AsyncSession) -> int:
        return int(await get_setting(session, "min_custom_gb", str(self.settings.min_custom_gb)))

    async def max_custom_gb(self, session: AsyncSession) -> int:
        return int(await get_setting(session, "max_custom_gb", str(self.settings.max_custom_gb)))
