from __future__ import annotations

import secrets
import string
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Order, OrderStatus, OrderType, User
from app.db.repositories import active_service_for_user, order_by_gift_delivery_token_for_update
from app.services.vpn_service import ReferralRewardResult, VPNProvisioningService
from app.services.wallet_service import WalletService


class GiftRedeemError(RuntimeError):
    pass


class GiftRedeemInvalid(GiftRedeemError):
    pass


class GiftRedeemUsed(GiftRedeemError):
    pass


class GiftRedeemNotReady(GiftRedeemError):
    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


@dataclass(frozen=True)
class GiftRedeemResult:
    order: Order
    service: object
    config_links: list[str]
    referral_reward: ReferralRewardResult


def normalize_redeem_code(value: str) -> str:
    if "gift_" in value:
        value = value.rsplit("gift_", 1)[-1]
    if "start=" in value:
        value = value.rsplit("start=", 1)[-1]
    return "".join(ch for ch in value.upper() if ch.isalnum())


async def generate_redeem_code(session: AsyncSession) -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(30):
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        exists_code = await session.scalar(select(Order.id).where(Order.gift_delivery_token == code))
        if not exists_code:
            return code
    raise RuntimeError("Could not generate unique redeem code")


async def redeem_gift_order(
    session: AsyncSession,
    settings: Settings,
    user: User,
    raw_code: str,
) -> GiftRedeemResult:
    code = normalize_redeem_code(raw_code)
    order = await order_by_gift_delivery_token_for_update(session, code)
    if not order:
        raise GiftRedeemInvalid("Gift code not found")
    if order.status == OrderStatus.completed.value:
        if order.user_id == user.id:
            service = await active_service_for_user(session, user.id)
            if service:
                return GiftRedeemResult(order, service, [], ReferralRewardResult())
        raise GiftRedeemUsed("Gift code already used")
    if order.status != OrderStatus.approved.value:
        raise GiftRedeemNotReady(order.status)

    buyer_id = order.purchased_by_user_id or order.user_id
    order.user_id = user.id
    order.user = user
    order.order_type = OrderType.renewal.value if await active_service_for_user(session, user.id) else OrderType.new.value
    order.status = OrderStatus.pending_admin.value
    await session.flush()

    try:
        service, _created, config_links, referral_reward = await VPNProvisioningService(settings).approve_order(
            session, order.id
        )
    except Exception as exc:
        if buyer_id:
            await WalletService().refund(
                session,
                buyer_id,
                order.price_toman,
                order.id,
                note=f"Gift activation failed: {exc}",
            )
        raise
    return GiftRedeemResult(order, service, config_links, referral_reward)
