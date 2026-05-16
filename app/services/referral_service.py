from __future__ import annotations

import logging

from app.services.vpn_service import ReferralRewardResult

logger = logging.getLogger(__name__)


async def notify_referrer_about_reward(bot, i18n, reward: ReferralRewardResult) -> None:
    if not reward.referrer_telegram_id or not reward.referrer_bonus_gb:
        return
    key = "referral_reward_pending" if reward.referrer_pending else "referral_reward_applied"
    try:
        await bot.send_message(
            reward.referrer_telegram_id,
            i18n.t(
                key,
                reward.referrer_language or "fa",
                bonus_gb=reward.referrer_bonus_gb,
            ),
        )
    except Exception:
        logger.exception(
            "Failed to notify referrer",
            extra={"telegram_id": reward.referrer_telegram_id},
        )
