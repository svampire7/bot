from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    BotSetting,
    DiscountCode,
    Order,
    OrderStatus,
    SupportMessage,
    SupportTicket,
    SupportTicketStatus,
    User,
    VPNService,
    VPNServiceStatus,
)


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    default_language: str,
) -> User:
    result = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if result:
        result.telegram_username = username
        result.first_name = first_name
        return result
    user = User(
        telegram_id=telegram_id,
        telegram_username=username,
        first_name=first_name,
        language=default_language,
    )
    session.add(user)
    await session.flush()
    return user


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == telegram_id))


async def search_user(session: AsyncSession, query: str) -> User | None:
    clauses = [User.telegram_username.ilike(query.lstrip("@"))]
    if query.isdigit():
        clauses.append(User.telegram_id == int(query))
    user = await session.scalar(select(User).where(or_(*clauses)).limit(1))
    if user:
        return user
    service = await session.scalar(select(VPNService).where(VPNService.marzban_username == query))
    return await session.get(User, service.user_id) if service else None


async def active_service_for_user(session: AsyncSession, user_id: int) -> VPNService | None:
    return await session.scalar(
        select(VPNService)
        .where(VPNService.user_id == user_id, VPNService.status == VPNServiceStatus.active.value)
        .order_by(VPNService.id.desc())
    )


async def pending_orders(session: AsyncSession, limit: int = 10, offset: int = 0) -> list[Order]:
    result = await session.scalars(
        select(Order)
        .options(selectinload(Order.user))
        .where(Order.status == OrderStatus.pending_admin.value)
        .order_by(Order.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    return list(result)


async def order_with_user_for_update(session: AsyncSession, order_id: int) -> Order | None:
    stmt: Select[tuple[Order]] = (
        select(Order)
        .options(selectinload(Order.user))
        .where(Order.id == order_id)
        .with_for_update()
    )
    return await session.scalar(stmt)


async def user_order_history(session: AsyncSession, user_id: int, limit: int = 10) -> list[Order]:
    result = await session.scalars(
        select(Order).where(Order.user_id == user_id).order_by(Order.id.desc()).limit(limit)
    )
    return list(result)


async def order_for_user(session: AsyncSession, user_id: int, order_id: int) -> Order | None:
    return await session.scalar(select(Order).where(Order.id == order_id, Order.user_id == user_id))


async def order_context(session: AsyncSession, order: Order) -> dict[str, int | str]:
    total_orders = await session.scalar(select(func.count(Order.id)).where(Order.user_id == order.user_id))
    completed_orders = await session.scalar(
        select(func.count(Order.id)).where(
            Order.user_id == order.user_id, Order.status == OrderStatus.completed.value
        )
    )
    duplicate_pending = await session.scalar(
        select(func.count(Order.id)).where(
            Order.user_id == order.user_id,
            Order.status == OrderStatus.pending_admin.value,
            Order.id != order.id,
        )
    )
    duplicate_receipts = await session.scalar(
        select(func.count(Order.id)).where(
            Order.receipt_file_id == order.receipt_file_id,
            Order.id != order.id,
        )
    )
    service = await active_service_for_user(session, order.user_id)
    return {
        "total_orders": int(total_orders or 0),
        "completed_orders": int(completed_orders or 0),
        "duplicate_pending": int(duplicate_pending or 0),
        "duplicate_receipts": int(duplicate_receipts or 0),
        "service": service.marzban_username if service else "-",
    }


async def latest_support_ticket(session: AsyncSession, user_id: int) -> SupportTicket | None:
    return await session.scalar(
        select(SupportTicket)
        .where(SupportTicket.user_id == user_id)
        .order_by(SupportTicket.id.desc())
        .limit(1)
    )


async def get_or_create_support_ticket(session: AsyncSession, user_id: int) -> SupportTicket:
    ticket = await latest_support_ticket(session, user_id)
    if ticket and ticket.status != SupportTicketStatus.closed.value:
        return ticket
    ticket = SupportTicket(user_id=user_id, status=SupportTicketStatus.open.value)
    session.add(ticket)
    await session.flush()
    return ticket


async def add_support_message(
    session: AsyncSession,
    ticket: SupportTicket,
    sender_type: str,
    sender_telegram_id: int,
    message_type: str,
    telegram_message_id: int | None,
    text: str | None,
) -> SupportMessage:
    preview = (text or message_type or "")[:500]
    ticket.status = (
        SupportTicketStatus.open.value if sender_type == "user" else SupportTicketStatus.answered.value
    )
    ticket.last_message_preview = preview
    message = SupportMessage(
        ticket_id=ticket.id,
        sender_type=sender_type,
        sender_telegram_id=sender_telegram_id,
        message_type=message_type,
        telegram_message_id=telegram_message_id,
        text=text,
    )
    session.add(message)
    await session.flush()
    return message


async def support_history(session: AsyncSession, user_id: int, limit: int = 6) -> list[SupportMessage]:
    ticket = await latest_support_ticket(session, user_id)
    if not ticket:
        return []
    result = await session.scalars(
        select(SupportMessage)
        .where(SupportMessage.ticket_id == ticket.id)
        .order_by(SupportMessage.id.desc())
        .limit(limit)
    )
    return list(reversed(list(result)))


def normalize_discount_code(code: str) -> str:
    return code.strip().upper().replace(" ", "")


async def get_discount_code(session: AsyncSession, code: str) -> DiscountCode | None:
    return await session.scalar(select(DiscountCode).where(DiscountCode.code == normalize_discount_code(code)))


async def active_discount_code(session: AsyncSession, code: str) -> DiscountCode | None:
    discount = await get_discount_code(session, code)
    if not discount or not discount.is_active:
        return None
    if discount.max_uses is not None and discount.used_count >= discount.max_uses:
        return None
    return discount


async def list_discount_codes(session: AsyncSession, limit: int = 10) -> list[DiscountCode]:
    result = await session.scalars(select(DiscountCode).order_by(DiscountCode.id.desc()).limit(limit))
    return list(result)


async def get_setting(session: AsyncSession, key: str, default: str) -> str:
    setting = await session.get(BotSetting, key)
    return setting.value if setting else default


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    setting = await session.get(BotSetting, key)
    if setting:
        setting.value = value
    else:
        session.add(BotSetting(key=key, value=value))


async def stats(session: AsyncSession) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    total_users = await session.scalar(select(func.count(User.id)))
    active_services = await session.scalar(
        select(func.count(VPNService.id)).where(VPNService.status == VPNServiceStatus.active.value)
    )
    completed_orders = await session.scalar(
        select(func.count(Order.id)).where(Order.status == OrderStatus.completed.value)
    )
    pending = await session.scalar(
        select(func.count(Order.id)).where(Order.status == OrderStatus.pending_admin.value)
    )
    revenue = await session.scalar(
        select(func.coalesce(func.sum(Order.price_toman), 0)).where(
            Order.status == OrderStatus.completed.value
        )
    )
    sold_gb = await session.scalar(
        select(func.coalesce(func.sum(Order.gb_amount), 0)).where(
            Order.status == OrderStatus.completed.value
        )
    )
    today_revenue = await session.scalar(
        select(func.coalesce(func.sum(Order.price_toman), 0)).where(
            Order.status == OrderStatus.completed.value, Order.updated_at >= day_start
        )
    )
    month_revenue = await session.scalar(
        select(func.coalesce(func.sum(Order.price_toman), 0)).where(
            Order.status == OrderStatus.completed.value, Order.updated_at >= month_start
        )
    )
    return {
        "total_users": int(total_users or 0),
        "active_services": int(active_services or 0),
        "completed_orders": int(completed_orders or 0),
        "pending_orders": int(pending or 0),
        "total_revenue": int(revenue or 0),
        "sold_gb": int(sold_gb or 0),
        "today_revenue": int(today_revenue or 0),
        "month_revenue": int(month_revenue or 0),
    }
