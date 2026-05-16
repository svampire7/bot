from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Order, OrderStatus, User, VPNService, VPNServiceStatus
from app.db.repositories import active_service_for_user, get_discount_code, order_with_user_for_update
from app.marzban.client import MarzbanClient
from app.services.payment_service import PaymentService
from app.utils.formatters import bytes_to_gb
from app.utils.validators import sanitize_username

logger = logging.getLogger(__name__)


class DuplicateApprovalError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReferralRewardResult:
    referred_bonus_gb: int = 0
    pending_bonus_gb: int = 0
    referrer_telegram_id: int | None = None
    referrer_language: str | None = None
    referrer_bonus_gb: int = 0
    referrer_pending: bool = False


class VPNProvisioningService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def approve_order(
        self, session: AsyncSession, order_id: int
    ) -> tuple[VPNService, bool, list[str], ReferralRewardResult]:
        order = await order_with_user_for_update(session, order_id)
        if not order:
            raise ValueError("Order not found")
        if order.status != OrderStatus.pending_admin.value:
            raise DuplicateApprovalError("Order is not pending")

        service = await active_service_for_user(session, order.user_id)
        created_new = False
        config_links: list[str] = []
        referral_result = ReferralRewardResult()
        try:
            async with MarzbanClient(self.settings) as marzban:
                if service:
                    remote_user = await marzban.get_user(service.marzban_username)
                    if remote_user:
                        updated = await marzban.add_traffic_to_user(
                            service.marzban_username, order.gb_amount
                        )
                        username = service.marzban_username
                        service.subscription_url = marzban.get_subscription_url(username, updated)
                        config_links = updated.links
                        service.data_limit_gb += order.gb_amount
                    else:
                        service.status = VPNServiceStatus.deleted.value
                        service = None
                if not service:
                    username = sanitize_username(f"tg_{order.user.telegram_id}_{order.id}")
                    created = await marzban.create_user(username, order.gb_amount)
                    config_links = created.links
                    service = VPNService(
                        user_id=order.user_id,
                        marzban_username=username,
                        subscription_url=marzban.get_subscription_url(username, created),
                        data_limit_gb=order.gb_amount,
                        status=VPNServiceStatus.active.value,
                    )
                    session.add(service)
                    created_new = True
                referral_result = await self._apply_referral_bonuses(session, marzban, order, service)
                usage = await marzban.get_user_usage(service.marzban_username)
                service.used_traffic_gb = bytes_to_gb(usage.used_traffic)
                service.remaining_traffic_gb = bytes_to_gb(usage.remaining_traffic)
                service.status = VPNServiceStatus.active.value
                order.status = OrderStatus.completed.value
                order.marzban_username = service.marzban_username
                if order.discount_code:
                    discount = await get_discount_code(session, order.discount_code)
                    if discount:
                        discount.used_count += 1
        except Exception as exc:
            logger.exception("Failed to provision order", extra={"order_id": order_id})
            order.status = OrderStatus.failed.value
            order.admin_note = str(exc)[:1000]
            raise
        return service, created_new, config_links, referral_result

    async def _apply_referral_bonuses(
        self,
        session: AsyncSession,
        marzban: MarzbanClient,
        order: Order,
        service: VPNService,
    ) -> ReferralRewardResult:
        bonus_gb = await PaymentService(self.settings).referral_bonus_gb(session)
        if bonus_gb <= 0:
            return ReferralRewardResult()

        user = order.user
        pending_bonus = int(user.pending_referral_bonus_gb or 0)
        if pending_bonus > 0:
            updated = await marzban.add_traffic_to_user(service.marzban_username, pending_bonus)
            service.subscription_url = marzban.get_subscription_url(service.marzban_username, updated)
            service.data_limit_gb += pending_bonus
            user.pending_referral_bonus_gb = 0

        completed_before = await session.scalar(
            select(func.count(Order.id)).where(
                Order.user_id == order.user_id,
                Order.status == OrderStatus.completed.value,
                Order.id != order.id,
            )
        )
        if user.referral_bonus_awarded or not user.referred_by_user_id or int(completed_before or 0) > 0:
            return ReferralRewardResult(pending_bonus_gb=pending_bonus)

        updated = await marzban.add_traffic_to_user(service.marzban_username, bonus_gb)
        service.subscription_url = marzban.get_subscription_url(service.marzban_username, updated)
        service.data_limit_gb += bonus_gb
        user.referral_bonus_awarded = True

        referrer = await session.get(User, user.referred_by_user_id)
        if not referrer:
            return ReferralRewardResult(referred_bonus_gb=bonus_gb, pending_bonus_gb=pending_bonus)

        referrer_service = await active_service_for_user(session, referrer.id)
        referrer_pending = True
        if referrer_service:
            updated = await marzban.add_traffic_to_user(referrer_service.marzban_username, bonus_gb)
            referrer_service.subscription_url = marzban.get_subscription_url(
                referrer_service.marzban_username, updated
            )
            referrer_service.data_limit_gb += bonus_gb
            referrer_pending = False
        else:
            referrer.pending_referral_bonus_gb = int(referrer.pending_referral_bonus_gb or 0) + bonus_gb

        return ReferralRewardResult(
            referred_bonus_gb=bonus_gb,
            pending_bonus_gb=pending_bonus,
            referrer_telegram_id=referrer.telegram_id,
            referrer_language=referrer.language,
            referrer_bonus_gb=bonus_gb,
            referrer_pending=referrer_pending,
        )

    async def sync_service_usage(self, service: VPNService) -> VPNService:
        async with MarzbanClient(self.settings) as marzban:
            usage = await marzban.get_user_usage(service.marzban_username)
            service.used_traffic_gb = bytes_to_gb(usage.used_traffic)
            service.remaining_traffic_gb = bytes_to_gb(usage.remaining_traffic)
            if usage.data_limit is not None:
                service.data_limit_gb = int(bytes_to_gb(usage.data_limit) or service.data_limit_gb)
        return service
