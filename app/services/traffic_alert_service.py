from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.middlewares.i18n import I18n
from app.config import Settings
from app.db.models import PackageType, User, VPNService, VPNServiceStatus
from app.marzban.client import MarzbanClient
from app.utils.formatters import bytes_to_gb, optional_gb

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrafficAlertsDue:
    low_traffic: bool = False
    depleted: bool = False


def traffic_alerts_due(service: VPNService) -> TrafficAlertsDue:
    total = float(service.data_limit_gb or 0)
    if service.package_type == PackageType.unlimited_time.value:
        return TrafficAlertsDue()
    remaining = service.remaining_traffic_gb
    if total <= 0 or remaining is None:
        return TrafficAlertsDue()

    remaining_value = float(remaining)
    if remaining_value <= 0 and not service.traffic_depleted_alert_sent:
        return TrafficAlertsDue(depleted=True)

    threshold = total * 0.2
    if 0 < remaining_value <= threshold and not service.low_traffic_alert_sent:
        return TrafficAlertsDue(low_traffic=True)
    return TrafficAlertsDue()


class TrafficAlertService:
    def __init__(self, settings: Settings, bot: Bot, i18n: I18n) -> None:
        self.settings = settings
        self.bot = bot
        self.i18n = i18n

    async def check_paid_services(self, sessionmaker: async_sessionmaker) -> int:
        notifications: list[tuple[int, str]] = []
        async with sessionmaker() as session:
            rows = (
                await session.execute(
                    select(VPNService, User)
                    .join(User, User.id == VPNService.user_id)
                    .where(
                        VPNService.status == VPNServiceStatus.active.value,
                        VPNService.is_trial.is_(False),
                    )
                    .order_by(VPNService.id)
                )
            ).all()
            async with MarzbanClient(self.settings) as marzban:
                for service, user in rows:
                    try:
                        usage = await marzban.get_user_usage(service.marzban_username)
                    except Exception:
                        logger.exception(
                            "Failed to check VPN usage for traffic alert",
                            extra={"marzban_username": service.marzban_username},
                        )
                        continue

                    service.used_traffic_gb = bytes_to_gb(usage.used_traffic)
                    service.remaining_traffic_gb = (
                        None
                        if service.package_type == PackageType.unlimited_time.value
                        else bytes_to_gb(usage.remaining_traffic)
                    )
                    if usage.data_limit is not None:
                        service.data_limit_gb = bytes_to_gb(usage.data_limit) or service.data_limit_gb

                    due = traffic_alerts_due(service)
                    if due.depleted:
                        # A depletion alert already means the user passed the 80% mark.
                        service.low_traffic_alert_sent = True
                        service.traffic_depleted_alert_sent = True
                        notifications.append(
                            (
                                user.telegram_id,
                                self.i18n.t("traffic_depleted_notification", user.language),
                            )
                        )
                    elif due.low_traffic:
                        service.low_traffic_alert_sent = True
                        notifications.append(
                            (
                                user.telegram_id,
                                self.i18n.t(
                                    "traffic_80_notification",
                                    user.language,
                                    remaining=optional_gb(service.remaining_traffic_gb),
                                ),
                            )
                        )
            await session.commit()

        for telegram_id, text in notifications:
            try:
                await self.bot.send_message(telegram_id, text)
            except Exception:
                # The alert is intentionally one-shot. Do not keep retrying and
                # risk duplicate notices after a Telegram delivery ambiguity.
                logger.exception("Failed to send traffic alert", extra={"telegram_id": telegram_id})
        return len(notifications)
