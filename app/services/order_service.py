from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Order, OrderStatus, OrderType, PackageType
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
        package_type: str = PackageType.traffic.value,
        duration_days: int | None = None,
        purchased_by_user_id: int | None = None,
        gift_delivery_token: str | None = None,
    ) -> Order:
        active_service = await active_service_for_user(session, user_id)
        order = Order(
            user_id=user_id,
            purchased_by_user_id=purchased_by_user_id,
            order_type=OrderType.renewal.value if active_service else OrderType.new.value,
            package_type=package_type,
            gb_amount=gb_amount,
            duration_days=duration_days,
            gift_delivery_token=gift_delivery_token,
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
