from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Order, OrderStatus, OrderType
from app.db.repositories import active_service_for_user


class OrderService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def create_order(
        self,
        session: AsyncSession,
        user_id: int,
        gb_amount: int,
        price_toman: int,
        receipt_file_id: str | None,
        original_price_toman: int | None = None,
        discount_code: str | None = None,
        discount_amount_toman: int = 0,
        payment_method: str = "card",
        crypto_tx_hash: str | None = None,
        crypto_expected_usdt: str | None = None,
    ) -> Order:
        active_service = await active_service_for_user(session, user_id)
        order = Order(
            user_id=user_id,
            order_type=OrderType.renewal.value if active_service else OrderType.new.value,
            gb_amount=gb_amount,
            price_toman=price_toman,
            original_price_toman=original_price_toman,
            discount_code=discount_code,
            discount_amount_toman=discount_amount_toman,
            payment_method=payment_method,
            crypto_tx_hash=crypto_tx_hash,
            crypto_expected_usdt=crypto_expected_usdt,
            status=OrderStatus.pending_admin.value,
            receipt_file_id=receipt_file_id,
        )
        session.add(order)
        await session.flush()
        return order
