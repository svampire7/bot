from __future__ import annotations

from app.services.bulk_service import BulkPlanItem
from app.utils.formatters import toman


def bulk_summary_lines(items: list[BulkPlanItem]) -> list[str]:
    return [f"{item.quantity} accounts x {item.gb}GB = {item.quantity * item.gb}GB" for item in items]


def bulk_invoice_text(order_code: str, telegram_id: int, items: list[BulkPlanItem], price: int) -> str:
    total_accounts = sum(item.quantity for item in items)
    total_gb = sum(item.quantity * item.gb for item in items)
    lines = "\n".join(bulk_summary_lines(items))
    return (
        f"Order ID: {order_code}\n"
        f"Reseller Telegram ID: {telegram_id}\n"
        f"{lines}\n"
        f"Total accounts: {total_accounts}\n"
        f"Total traffic: {total_gb}GB\n"
        f"Price: {toman(price)} Toman\n"
        "Status: Pending Payment/Admin Approval"
    )
