from __future__ import annotations

import asyncio
from collections.abc import Sequence

from aiogram import Bot
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, VPNService, VPNServiceStatus, WalletTransaction, WalletTransactionStatus


def broadcast_recipients_query(segment: str):
    stmt = select(User.telegram_id).where(User.is_blocked.is_(False))
    if segment == "active":
        return stmt.join(VPNService).where(VPNService.status == VPNServiceStatus.active.value)
    if segment == "no_service":
        return stmt.outerjoin(VPNService).where(VPNService.id.is_(None))
    if segment in {"fa", "en"}:
        return stmt.where(User.language == segment)
    if segment == "wallet_positive":
        subq = (
            select(WalletTransaction.user_id)
            .where(WalletTransaction.status == WalletTransactionStatus.completed.value)
            .group_by(WalletTransaction.user_id)
            .having(func.sum(WalletTransaction.amount_toman) > 0)
        )
        return stmt.where(User.id.in_(subq))
    return stmt


async def load_broadcast_recipients(session: AsyncSession, segment: str) -> list[int]:
    return list(await session.scalars(broadcast_recipients_query(segment).distinct()))


async def send_broadcast(
    bot: Bot,
    telegram_ids: Sequence[int],
    text: str,
    *,
    batch_size: int,
    batch_delay_seconds: float,
) -> tuple[int, int]:
    ok = fail = 0
    batch_size = max(1, batch_size)
    for index, telegram_id in enumerate(telegram_ids, start=1):
        try:
            await bot.send_message(telegram_id, text)
            ok += 1
        except Exception:
            fail += 1
        if index % batch_size == 0:
            await asyncio.sleep(max(0.0, batch_delay_seconds))
    return ok, fail
