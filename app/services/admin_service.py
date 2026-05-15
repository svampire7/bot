from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AdminActionLog


async def log_admin_action(
    session: AsyncSession,
    admin_telegram_id: int,
    action: str,
    order_id: int | None = None,
    details: str | None = None,
) -> None:
    session.add(
        AdminActionLog(
            admin_telegram_id=admin_telegram_id,
            order_id=order_id,
            action=action,
            details=details,
        )
    )

