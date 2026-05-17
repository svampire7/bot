from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.db.models import (
    ResellerBulkOrder,
    ResellerBulkOrderAccount,
    ResellerBulkOrderStatus,
)
from app.marzban.client import MarzbanClient
from app.services.bulk_service import BulkPlanItem, export_bulk_csv, parse_bulk_plan
from app.services.payment_service import PaymentService
from app.services.vpn_account_service import create_vpn_account
from app.utils.validators import sanitize_username


@dataclass(frozen=True)
class ResellerBulkPlan:
    items: list[BulkPlanItem]
    total_accounts: int
    total_gb: int
    total_price: int


async def parse_reseller_bulk_request(session: AsyncSession, settings: Settings, text: str) -> ResellerBulkPlan:
    items = parse_bulk_plan(text)
    total_accounts = sum(item.quantity for item in items)
    total_gb = sum(item.quantity * item.gb for item in items)
    payment = PaymentService(settings)
    min_total_gb = await payment.min_reseller_bulk_gb(session)
    if total_gb < min_total_gb:
        raise ValueError(f"Minimum reseller bulk order is {min_total_gb}GB.")
    price = total_gb * await payment.reseller_price_per_gb(session)
    return ResellerBulkPlan(items=items, total_accounts=total_accounts, total_gb=total_gb, total_price=price)


def _items_json(items: list[BulkPlanItem]) -> str:
    return json.dumps([{"quantity": item.quantity, "gb": item.gb} for item in items])


def _items_from_json(value: str) -> list[BulkPlanItem]:
    parsed = json.loads(value)
    return [BulkPlanItem(quantity=int(item["quantity"]), gb=int(item["gb"])) for item in parsed]


async def create_reseller_bulk_order(
    session: AsyncSession,
    reseller_telegram_id: int,
    raw_text: str,
    plan: ResellerBulkPlan,
) -> ResellerBulkOrder:
    order = ResellerBulkOrder(
        order_code="PENDING",
        reseller_telegram_id=reseller_telegram_id,
        raw_request_text=raw_text,
        parsed_items_json=_items_json(plan.items),
        total_accounts=plan.total_accounts,
        total_gb=plan.total_gb,
        total_price=plan.total_price,
        status=ResellerBulkOrderStatus.pending_payment.value,
    )
    session.add(order)
    await session.flush()
    order.order_code = f"BULK-{order.id:06d}"
    await session.flush()
    return order


async def reseller_orders(session: AsyncSession, telegram_id: int, limit: int = 10) -> list[ResellerBulkOrder]:
    result = await session.scalars(
        select(ResellerBulkOrder)
        .where(ResellerBulkOrder.reseller_telegram_id == telegram_id)
        .order_by(ResellerBulkOrder.id.desc())
        .limit(limit)
    )
    return list(result)


async def pending_reseller_bulk_orders(session: AsyncSession, limit: int = 10) -> list[ResellerBulkOrder]:
    result = await session.scalars(
        select(ResellerBulkOrder)
        .where(ResellerBulkOrder.status == ResellerBulkOrderStatus.pending_admin.value)
        .order_by(ResellerBulkOrder.id.asc())
        .limit(limit)
    )
    return list(result)


async def recent_reseller_bulk_orders(session: AsyncSession, limit: int = 10) -> list[ResellerBulkOrder]:
    result = await session.scalars(
        select(ResellerBulkOrder).order_by(ResellerBulkOrder.id.desc()).limit(limit)
    )
    return list(result)


async def reseller_bulk_order_with_accounts(session: AsyncSession, order_id: int) -> ResellerBulkOrder | None:
    return await session.scalar(
        select(ResellerBulkOrder)
        .options(selectinload(ResellerBulkOrder.accounts))
        .where(ResellerBulkOrder.id == order_id)
    )


def generated_reseller_txt(order: ResellerBulkOrder, accounts: list[ResellerBulkOrderAccount]) -> str:
    lines = [
        f"Order ID: {order.order_code}",
        f"Reseller Telegram ID: {order.reseller_telegram_id}",
        f"Total Accounts: {order.total_accounts}",
        f"Total Traffic: {order.total_gb}GB",
        "",
    ]
    for account in accounts:
        lines.extend(
            [
                "--------------------------------",
                f"Username: {account.username}",
                f"Quota: {account.quota_gb}GB",
                f"Config: {account.config_link or '-'}",
                f"Subscription: {account.subscription_link or '-'}",
            ]
        )
    lines.append("--------------------------------")
    return "\n".join(lines)


async def generate_reseller_accounts(
    session: AsyncSession,
    settings: Settings,
    order: ResellerBulkOrder,
    admin_id: int,
) -> tuple[bool, str]:
    items = _items_from_json(order.parsed_items_json)
    created: list[ResellerBulkOrderAccount] = list(order.accounts)
    existing = {account.username for account in created}
    errors: list[str] = []
    async with MarzbanClient(settings) as marzban:
        for item in items:
            for sequence in range(1, item.quantity + 1):
                next_sequence = sequence
                while True:
                    username = sanitize_username(
                        f"reseller{order.reseller_telegram_id}-{item.gb}gb-{next_sequence:03d}"
                    )
                    if username not in existing and not await session.scalar(
                        select(ResellerBulkOrderAccount.id).where(
                            ResellerBulkOrderAccount.username == username
                        )
                    ):
                        break
                    next_sequence += 1
                if username in existing:
                    continue
                account = ResellerBulkOrderAccount(
                    bulk_order_id=order.id,
                    username=username,
                    quota_gb=item.gb,
                )
                try:
                    remote = await create_vpn_account(marzban, username, item.gb)
                    account.subscription_link = marzban.get_subscription_url(username, remote)
                    account.config_link = "\n".join(remote.links)
                except Exception as exc:
                    account.error_message = str(exc)[:1000]
                    errors.append(f"{username}: {exc}")
                session.add(account)
                created.append(account)
                existing.add(username)
                await session.flush()

    successful = [account for account in created if not account.error_message]
    order.approved_by_admin_id = admin_id
    order.approved_at = datetime.now(timezone.utc)
    if errors:
        order.status = ResellerBulkOrderStatus.partially_failed.value if successful else ResellerBulkOrderStatus.failed.value
        order.error_message = "\n".join(errors)[:3000]
        return False, order.error_message
    order.status = ResellerBulkOrderStatus.completed.value
    order.error_message = None
    return True, generated_reseller_txt(order, successful)
