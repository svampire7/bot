from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DiscountCode
from app.db.repositories import active_discount_code, normalize_discount_code


def discount_amount(price_toman: int, discount: DiscountCode) -> int:
    percent_amount = price_toman * discount.percent // 100 if discount.percent else 0
    amount = max(percent_amount, discount.amount_toman or 0)
    return min(price_toman, max(0, amount))


async def apply_discount(
    session: AsyncSession,
    code: str,
    price_toman: int,
) -> tuple[DiscountCode | None, int, int]:
    discount = await active_discount_code(session, code)
    if not discount:
        return None, 0, price_toman
    amount = discount_amount(price_toman, discount)
    return discount, amount, price_toman - amount


def parse_discount_definition(text: str) -> tuple[str, int, int, int | None]:
    parts = text.split()
    if len(parts) < 3:
        raise ValueError("Expected: CODE percent amount_toman [max_uses]")
    code = normalize_discount_code(parts[0])
    percent = int(parts[1])
    amount = int(parts[2])
    max_uses = int(parts[3]) if len(parts) >= 4 else None
    if not code or percent < 0 or percent > 100 or amount < 0 or (max_uses is not None and max_uses < 1):
        raise ValueError("Invalid discount values")
    if percent == 0 and amount == 0:
        raise ValueError("Discount must be greater than zero")
    return code, percent, amount, max_uses
