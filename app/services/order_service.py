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
        receipt_file_id: str,
    ) -> Order:
        active_service = await active_service_for_user(session, user_id)
        order = Order(
            user_id=user_id,
            order_type=OrderType.renewal.value if active_service else OrderType.new.value,
            gb_amount=gb_amount,
            price_toman=price_toman,
            status=OrderStatus.pending_admin.value,
            receipt_file_id=receipt_file_id,
        )
        session.add(order)
        await session.flush()
        return order

