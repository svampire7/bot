from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import User, VPNService, VPNServiceStatus
from app.marzban.client import MarzbanClient
from app.utils.formatters import bytes_to_gb
from app.utils.validators import sanitize_username

logger = logging.getLogger(__name__)


class TrialAlreadyUsedError(RuntimeError):
    pass


class ActiveServiceExistsError(RuntimeError):
    pass


@dataclass(frozen=True)
class TrialActivationResult:
    service: VPNService
    config_links: list[str]


class TrialService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def activate_trial(self, session: AsyncSession, user_id: int) -> TrialActivationResult:
        user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
        if not user:
            raise ValueError("User not found")
        if user.has_used_trial:
            raise TrialAlreadyUsedError("Trial already used")

        active_service = await session.scalar(
            select(VPNService)
            .where(VPNService.user_id == user.id, VPNService.status == VPNServiceStatus.active.value)
            .with_for_update()
        )
        if active_service:
            raise ActiveServiceExistsError("User already has an active service")

        created_at = datetime.now(timezone.utc)
        expire_at = created_at + timedelta(hours=self.settings.trial_duration_hours)
        username = sanitize_username(f"trial_{user.telegram_id}")

        async with MarzbanClient(self.settings) as marzban:
            remote = await marzban.get_user(username)
            if remote:
                remote = await marzban.update_user(
                    username,
                    {
                        "data_limit": self.settings.trial_traffic_mb * 1024 * 1024,
                        "data_limit_reset_strategy": "no_reset",
                        "expire": int(expire_at.timestamp()),
                        "status": "active",
                    },
                )
            else:
                remote = await marzban.create_trial_user(
                    username,
                    self.settings.trial_traffic_mb,
                    expire_at,
                )
            usage = await marzban.get_user_usage(username)

        service = VPNService(
            user_id=user.id,
            marzban_username=username,
            subscription_url=MarzbanClient(self.settings).get_subscription_url(username, remote),
            data_limit_gb=bytes_to_gb(usage.data_limit) or round(self.settings.trial_traffic_mb / 1024, 2),
            used_traffic_gb=bytes_to_gb(usage.used_traffic),
            remaining_traffic_gb=bytes_to_gb(usage.remaining_traffic),
            status=VPNServiceStatus.active.value,
            is_trial=True,
            trial_expire_at=expire_at,
        )
        user.has_used_trial = True
        user.trial_created_at = created_at
        user.trial_expire_at = expire_at
        session.add(service)
        await session.flush()
        return TrialActivationResult(service=service, config_links=remote.links)

    async def cleanup_expired_trials(self, sessionmaker: async_sessionmaker) -> int:
        now = datetime.now(timezone.utc)
        async with sessionmaker.begin() as session:
            services = list(
                await session.scalars(
                    select(VPNService)
                    .where(
                        VPNService.is_trial.is_(True),
                        VPNService.status == VPNServiceStatus.active.value,
                        VPNService.trial_expire_at <= now,
                    )
                    .with_for_update()
                )
            )
            if not services:
                return 0
            async with MarzbanClient(self.settings) as marzban:
                for service in services:
                    try:
                        if self.settings.trial_expire_action == "delete":
                            await marzban.delete_user(service.marzban_username)
                            service.status = VPNServiceStatus.deleted.value
                        else:
                            await marzban.disable_user(service.marzban_username)
                            service.status = VPNServiceStatus.disabled.value
                    except Exception:
                        logger.exception(
                            "Failed to expire trial service",
                            extra={"marzban_username": service.marzban_username},
                        )
        return len(services)
