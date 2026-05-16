from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import BulkAccount, BulkBatch, BulkBatchStatus, VPNServiceStatus
from app.marzban.client import MarzbanClient
from app.utils.validators import sanitize_username


class BulkPlanError(ValueError):
    pass


@dataclass(frozen=True)
class BulkPlanItem:
    quantity: int
    gb: int


@dataclass(frozen=True)
class BulkCreateResult:
    batch: BulkBatch
    accounts: list[BulkAccount]
    txt: str
    csv: str


def parse_bulk_plan(text: str, max_accounts: int = 200) -> list[BulkPlanItem]:
    items: list[BulkPlanItem] = []
    for raw_line in text.splitlines():
        line = raw_line.strip().lower()
        if not line:
            continue
        numbers = [int(value) for value in re.findall(r"\d+", line)]
        if len(numbers) < 2:
            raise BulkPlanError(f"Invalid line: {raw_line}")
        quantity, gb = numbers[0], numbers[1]
        if quantity <= 0 or gb <= 0:
            raise BulkPlanError(f"Invalid line: {raw_line}")
        items.append(BulkPlanItem(quantity=quantity, gb=gb))
    total = sum(item.quantity for item in items)
    if not items:
        raise BulkPlanError("Empty plan")
    if total > max_accounts:
        raise BulkPlanError(f"Too many accounts: {total}. Max is {max_accounts}.")
    return items


def _links(account: BulkAccount) -> list[str]:
    if not account.config_links_json:
        return []
    try:
        value = json.loads(account.config_links_json)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def export_bulk_txt(batch: BulkBatch, accounts: list[BulkAccount]) -> str:
    lines = [
        f"Batch #{batch.id}: {batch.name}",
        f"Accounts: {batch.total_accounts}",
        f"Total traffic: {batch.total_gb} GB",
        f"Status: {batch.status}",
        "",
    ]
    for index, account in enumerate(accounts, start=1):
        lines.extend(
            [
                f"{index}) {account.marzban_username}",
                f"Traffic: {account.gb_amount} GB",
                f"Subscription: {account.subscription_url or '-'}",
                "Configs:",
            ]
        )
        links = _links(account)
        lines.extend(links if links else ["-"])
        if account.error_message:
            lines.append(f"Error: {account.error_message}")
        lines.append("")
    return "\n".join(lines)


def export_bulk_csv(batch: BulkBatch, accounts: list[BulkAccount]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["batch_id", "batch_name", "username", "gb", "subscription_url", "configs", "status", "error"])
    for account in accounts:
        writer.writerow(
            [
                batch.id,
                batch.name,
                account.marzban_username,
                account.gb_amount,
                account.subscription_url or "",
                "\n".join(_links(account)),
                account.status,
                account.error_message or "",
            ]
        )
    return output.getvalue()


class BulkService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def create_batch(
        self,
        session: AsyncSession,
        *,
        name: str,
        plan: list[BulkPlanItem],
        admin_telegram_id: int,
    ) -> BulkCreateResult:
        clean_name = " ".join(name.strip().split())[:128]
        batch = BulkBatch(
            name=clean_name,
            admin_telegram_id=admin_telegram_id,
            total_accounts=sum(item.quantity for item in plan),
            total_gb=sum(item.quantity * item.gb for item in plan),
            status=BulkBatchStatus.completed.value,
        )
        session.add(batch)
        await session.flush()

        accounts: list[BulkAccount] = []
        sequence = 1
        async with MarzbanClient(self.settings) as marzban:
            for item in plan:
                for _ in range(item.quantity):
                    username = sanitize_username(f"bulk_{batch.id}_{sequence:03d}_{item.gb}g")
                    account = BulkAccount(
                        batch_id=batch.id,
                        marzban_username=username,
                        gb_amount=item.gb,
                        status=VPNServiceStatus.active.value,
                    )
                    try:
                        remote = await marzban.create_user(username, item.gb)
                        account.subscription_url = marzban.get_subscription_url(username, remote)
                        account.config_links_json = json.dumps(remote.links, ensure_ascii=False)
                    except Exception as exc:
                        account.status = VPNServiceStatus.failed.value
                        account.error_message = str(exc)[:1000]
                        batch.status = BulkBatchStatus.partial.value
                    session.add(account)
                    accounts.append(account)
                    sequence += 1
                    await session.flush()

        if accounts and all(account.status == VPNServiceStatus.failed.value for account in accounts):
            batch.status = BulkBatchStatus.failed.value
            batch.error_message = "All account creations failed"
        await session.flush()
        return BulkCreateResult(
            batch=batch,
            accounts=accounts,
            txt=export_bulk_txt(batch, accounts),
            csv=export_bulk_csv(batch, accounts),
        )
