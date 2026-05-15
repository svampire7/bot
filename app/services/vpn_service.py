from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import OrderStatus, VPNService, VPNServiceStatus
from app.db.repositories import active_service_for_user, order_with_user_for_update
from app.marzban.client import MarzbanClient
from app.utils.formatters import bytes_to_gb
from app.utils.validators import sanitize_username

logger = logging.getLogger(__name__)


class DuplicateApprovalError(RuntimeError):
    pass


class VPNProvisioningService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def approve_order(
        self, session: AsyncSession, order_id: int
    ) -> tuple[VPNService, bool, list[str]]:
        order = await order_with_user_for_update(session, order_id)
        if not order:
            raise ValueError("Order not found")
        if order.status != OrderStatus.pending_admin.value:
            raise DuplicateApprovalError("Order is not pending")

        service = await active_service_for_user(session, order.user_id)
        created_new = False
        config_links: list[str] = []
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
                usage = await marzban.get_user_usage(service.marzban_username)
                service.used_traffic_gb = bytes_to_gb(usage.used_traffic)
                service.remaining_traffic_gb = bytes_to_gb(usage.remaining_traffic)
                service.status = VPNServiceStatus.active.value
                order.status = OrderStatus.completed.value
                order.marzban_username = service.marzban_username
        except Exception as exc:
            logger.exception("Failed to provision order", extra={"order_id": order_id})
            order.status = OrderStatus.failed.value
            order.admin_note = str(exc)[:1000]
            raise
        return service, created_new, config_links

    async def sync_service_usage(self, service: VPNService) -> VPNService:
        async with MarzbanClient(self.settings) as marzban:
            usage = await marzban.get_user_usage(service.marzban_username)
            service.used_traffic_gb = bytes_to_gb(usage.used_traffic)
            service.remaining_traffic_gb = bytes_to_gb(usage.remaining_traffic)
            if usage.data_limit is not None:
                service.data_limit_gb = int(bytes_to_gb(usage.data_limit) or service.data_limit_gb)
        return service
