from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    BotSetting,
    CryptoPaymentQuote,
    CryptoPaymentQuoteStatus,
    DiscountCode,
    Order,
    OrderStatus,
    SupportMessage,
    SupportTicket,
    SupportTicketStatus,
    User,
    VPNService,
    VPNServiceStatus,
    WalletTransaction,
    WalletTransactionStatus,
)
from app.services.settings_cache import settings_cache


async def _generate_card_reference_code(session: AsyncSession) -> str:
    for _ in range(20):
        code = str(100000 + secrets.randbelow(900000))
        exists_code = await session.scalar(select(User.id).where(User.card_reference_code == code))
        if not exists_code:
            return code
    raise RuntimeError("Could not generate unique card reference code")


async def ensure_card_reference_code(session: AsyncSession, user: User) -> str:
    if user.card_reference_code:
        return user.card_reference_code
    user.card_reference_code = await _generate_card_reference_code(session)
    await session.flush()
    return user.card_reference_code


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
        await ensure_card_reference_code(session, result)
        return result
    user = User(
        telegram_id=telegram_id,
        telegram_username=username,
        first_name=first_name,
        language=default_language,
        card_reference_code=await _generate_card_reference_code(session),
    )
    session.add(user)
    await session.flush()
    return user


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == telegram_id))


async def user_count(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count(User.id))) or 0)


async def users_with_referral_overview(
    session: AsyncSession, limit: int = 10, offset: int = 0
) -> list[tuple[User, int | None, int]]:
    invited_counts = (
        select(
            User.referred_by_user_id.label("referrer_id"),
            func.count(User.id).label("invited_count"),
        )
        .where(User.referred_by_user_id.is_not(None))
        .group_by(User.referred_by_user_id)
        .subquery()
    )
    referrer = User.__table__.alias("referrer")
    rows = await session.execute(
        select(
            User,
            referrer.c.telegram_id.label("referrer_telegram_id"),
            func.coalesce(invited_counts.c.invited_count, 0).label("invited_count"),
        )
        .outerjoin(referrer, referrer.c.id == User.referred_by_user_id)
        .outerjoin(invited_counts, invited_counts.c.referrer_id == User.id)
        .order_by(User.created_at.desc(), User.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return [(user, referrer_id, int(invited or 0)) for user, referrer_id, invited in rows.all()]


async def set_referrer_if_allowed(session: AsyncSession, user: User, referrer_telegram_id: int) -> bool:
    if user.referred_by_user_id or user.telegram_id == referrer_telegram_id:
        return False
    referrer = await get_user_by_telegram_id(session, referrer_telegram_id)
    if not referrer or referrer.id == user.id:
        return False
    user.referred_by_user_id = referrer.id
    return True


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


async def pending_order_count(session: AsyncSession) -> int:
    return int(
        await session.scalar(select(func.count(Order.id)).where(Order.status == OrderStatus.pending_admin.value))
        or 0
    )


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


async def order_by_crypto_tx_hash(session: AsyncSession, tx_hash: str) -> Order | None:
    return await session.scalar(select(Order).where(Order.crypto_tx_hash == tx_hash))


async def wallet_transaction_by_crypto_tx_hash(session: AsyncSession, tx_hash: str) -> WalletTransaction | None:
    return await session.scalar(select(WalletTransaction).where(WalletTransaction.crypto_tx_hash == tx_hash))


async def wallet_balance(session: AsyncSession, user_id: int) -> int:
    value = await session.scalar(
        select(func.coalesce(func.sum(WalletTransaction.amount_toman), 0)).where(
            WalletTransaction.user_id == user_id,
            WalletTransaction.status == WalletTransactionStatus.completed.value,
        )
    )
    return int(value or 0)


async def wallet_user_count(session: AsyncSession) -> int:
    return int(
        await session.scalar(
            select(func.count(func.distinct(WalletTransaction.user_id))).where(
                WalletTransaction.status == WalletTransactionStatus.completed.value
            )
        )
        or 0
    )


async def wallet_users_with_balances(
    session: AsyncSession, limit: int = 10, offset: int = 0
) -> list[tuple[User, int]]:
    balance_expr = func.coalesce(func.sum(WalletTransaction.amount_toman), 0).label("balance")
    result = await session.execute(
        select(User, balance_expr)
        .join(WalletTransaction, WalletTransaction.user_id == User.id)
        .where(WalletTransaction.status == WalletTransactionStatus.completed.value)
        .group_by(User.id)
        .order_by(balance_expr.desc(), User.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return [(user, int(balance or 0)) for user, balance in result.all()]


async def pending_wallet_topups(session: AsyncSession, limit: int = 10, offset: int = 0) -> list[WalletTransaction]:
    result = await session.scalars(
        select(WalletTransaction)
        .options(selectinload(WalletTransaction.user))
        .where(WalletTransaction.status == WalletTransactionStatus.pending_admin.value)
        .order_by(WalletTransaction.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    return list(result)


async def pending_wallet_topup_count(session: AsyncSession) -> int:
    return int(
        await session.scalar(
            select(func.count(WalletTransaction.id)).where(
                WalletTransaction.status == WalletTransactionStatus.pending_admin.value
            )
        )
        or 0
    )


async def wallet_transaction_for_update(session: AsyncSession, tx_id: int) -> WalletTransaction | None:
    return await session.scalar(
        select(WalletTransaction)
        .options(selectinload(WalletTransaction.user))
        .where(WalletTransaction.id == tx_id)
        .with_for_update()
    )


async def wallet_history(session: AsyncSession, user_id: int, limit: int = 10) -> list[WalletTransaction]:
    result = await session.scalars(
        select(WalletTransaction)
        .where(WalletTransaction.user_id == user_id)
        .order_by(WalletTransaction.id.desc())
        .limit(limit)
    )
    return list(result)


async def referral_stats(session: AsyncSession, user_id: int) -> dict[str, int]:
    invited = await session.scalar(select(func.count(User.id)).where(User.referred_by_user_id == user_id))
    paid = await session.scalar(
        select(func.count(User.id)).where(
            User.referred_by_user_id == user_id,
            User.referral_bonus_awarded.is_(True),
        )
    )
    user = await session.get(User, user_id)
    return {
        "invited": int(invited or 0),
        "paid": int(paid or 0),
        "pending_bonus_gb": int(user.pending_referral_bonus_gb or 0) if user else 0,
    }


async def user_is_known_for_card_access(session: AsyncSession, user_id: int) -> bool:
    user = await session.get(User, user_id)
    if not user:
        return False
    if user.card_access_unlocked:
        return True
    completed_order = await session.scalar(
        select(exists().where(Order.user_id == user_id, Order.status == OrderStatus.completed.value))
    )
    if completed_order:
        return True
    active_service = await session.scalar(
        select(exists().where(VPNService.user_id == user_id, VPNService.status == VPNServiceStatus.active.value))
    )
    if active_service:
        return True
    completed_topup = await session.scalar(
        select(
            exists().where(
                WalletTransaction.user_id == user_id,
                WalletTransaction.status == WalletTransactionStatus.completed.value,
            )
        )
    )
    return bool(completed_topup)


async def unlock_card_access_with_reference(
    session: AsyncSession, user: User, reference_code: str
) -> User | None:
    code = "".join(ch for ch in reference_code.strip() if ch.isdigit())
    if not code:
        return None
    referrer = await session.scalar(
        select(User).where(User.card_reference_code == code, User.id != user.id)
    )
    if not referrer or not await user_is_known_for_card_access(session, referrer.id):
        return None
    user.card_access_unlocked = True
    if not user.referred_by_user_id:
        user.referred_by_user_id = referrer.id
    await session.flush()
    return referrer


async def create_crypto_quote(
    session: AsyncSession,
    user_id: int,
    amount_toman: int,
    expected_ltc: str,
    ltc_toman_rate: int,
    wallet_address: str,
    ttl_minutes: int = 30,
) -> CryptoPaymentQuote:
    quote = CryptoPaymentQuote(
        user_id=user_id,
        amount_toman=amount_toman,
        expected_ltc=expected_ltc,
        ltc_toman_rate=ltc_toman_rate,
        wallet_address=wallet_address,
        status=CryptoPaymentQuoteStatus.pending.value,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
    )
    session.add(quote)
    await session.flush()
    return quote


async def crypto_quote_for_update(session: AsyncSession, quote_id: int) -> CryptoPaymentQuote | None:
    return await session.scalar(
        select(CryptoPaymentQuote).where(CryptoPaymentQuote.id == quote_id).with_for_update()
    )


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
    duplicate_receipts = 0
    if order.receipt_file_id:
        duplicate_receipts = await session.scalar(
            select(func.count(Order.id)).where(
                Order.receipt_file_id == order.receipt_file_id,
                Order.id != order.id,
            )
        )
    duplicate_crypto = 0
    if order.crypto_tx_hash:
        duplicate_crypto = await session.scalar(
            select(func.count(Order.id)).where(
                Order.crypto_tx_hash == order.crypto_tx_hash,
                Order.id != order.id,
            )
        )
    service = await active_service_for_user(session, order.user_id)
    return {
        "total_orders": int(total_orders or 0),
        "completed_orders": int(completed_orders or 0),
        "duplicate_pending": int(duplicate_pending or 0),
        "duplicate_receipts": int(duplicate_receipts or 0),
        "duplicate_crypto": int(duplicate_crypto or 0),
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


async def support_tickets(session: AsyncSession, limit: int = 10, offset: int = 0) -> list[SupportTicket]:
    result = await session.scalars(
        select(SupportTicket)
        .options(selectinload(SupportTicket.user))
        .order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result)


async def support_ticket_count(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count(SupportTicket.id))) or 0)


async def support_ticket_by_id(session: AsyncSession, ticket_id: int) -> SupportTicket | None:
    return await session.scalar(
        select(SupportTicket)
        .options(selectinload(SupportTicket.user))
        .where(SupportTicket.id == ticket_id)
    )


async def support_ticket_messages(
    session: AsyncSession, ticket_id: int, limit: int = 10
) -> list[SupportMessage]:
    result = await session.scalars(
        select(SupportMessage)
        .where(SupportMessage.ticket_id == ticket_id)
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
    cached = settings_cache.get(key)
    if cached is not None:
        return cached
    setting = await session.get(BotSetting, key)
    value = setting.value if setting else default
    settings_cache.set(key, value)
    return value


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    setting = await session.get(BotSetting, key)
    if setting:
        setting.value = value
    else:
        session.add(BotSetting(key=key, value=value))
    settings_cache.invalidate(key)


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


async def advanced_stats(session: AsyncSession) -> dict[str, int]:
    data = await stats(session)
    topups = await session.scalar(
        select(func.count(WalletTransaction.id)).where(
            WalletTransaction.transaction_type.in_(["topup_card", "topup_ltc"]),
            WalletTransaction.status == WalletTransactionStatus.completed.value,
        )
    )
    wallet_purchases = await session.scalar(
        select(func.count(Order.id)).where(
            Order.status == OrderStatus.completed.value,
            Order.payment_method == "wallet",
        )
    )
    referral_purchases = await session.scalar(
        select(func.count(User.id)).where(User.referral_bonus_awarded.is_(True))
    )
    no_service_users = await session.scalar(
        select(func.count(User.id)).outerjoin(VPNService).where(VPNService.id.is_(None))
    )
    data.update(
        {
            "completed_topups": int(topups or 0),
            "wallet_purchases": int(wallet_purchases or 0),
            "referral_purchases": int(referral_purchases or 0),
            "no_service_users": int(no_service_users or 0),
        }
    )
    return data


async def daily_sales_series(session: AsyncSession, days: int = 30) -> list[dict[str, int | str]]:
    days = max(1, min(days, 120))
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) - timedelta(days=days - 1)
    day_expr = func.date(Order.updated_at)
    result = await session.execute(
        select(
            day_expr.label("day"),
            func.coalesce(func.sum(Order.price_toman), 0).label("revenue"),
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.gb_amount), 0).label("gb"),
        )
        .where(Order.status == OrderStatus.completed.value, Order.updated_at >= start)
        .group_by(day_expr)
        .order_by(day_expr)
    )
    rows = {str(day): (int(revenue or 0), int(orders or 0), int(gb or 0)) for day, revenue, orders, gb in result.all()}
    series: list[dict[str, int | str]] = []
    for index in range(days):
        day = (start + timedelta(days=index)).date().isoformat()
        revenue, orders, gb = rows.get(day, (0, 0, 0))
        series.append({"date": day, "revenue": revenue, "orders": orders, "gb": gb})
    return series
