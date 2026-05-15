from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_UP

import aiohttp

from app.config import Settings

USDT_TRC20_CONTRACT = "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"
TX_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class CryptoPaymentError(RuntimeError):
    pass


@dataclass(frozen=True)
class CryptoTransfer:
    tx_hash: str
    to_address: str
    amount_usdt: Decimal
    confirmed: bool


def toman_to_usdt(price_toman: int, usdt_toman_rate: int) -> Decimal:
    if usdt_toman_rate <= 0:
        raise ValueError("USDT rate must be positive")
    return (Decimal(price_toman) / Decimal(usdt_toman_rate)).quantize(
        Decimal("0.01"), rounding=ROUND_UP
    )


def normalize_tx_hash(tx_hash: str) -> str:
    return tx_hash.strip().lower()


def validate_tx_hash(tx_hash: str) -> bool:
    return bool(TX_HASH_RE.fullmatch(normalize_tx_hash(tx_hash)))


class TronGridClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_usdt_transfer(self, wallet: str, tx_hash: str) -> CryptoTransfer | None:
        tx_hash = normalize_tx_hash(tx_hash)
        if not validate_tx_hash(tx_hash):
            raise CryptoPaymentError("Invalid transaction hash")
        headers = {}
        if self.settings.trongrid_api_key:
            headers["TRON-PRO-API-KEY"] = self.settings.trongrid_api_key
        url = f"{self.settings.trongrid_base_url.rstrip('/')}/v1/accounts/{wallet}/transactions/trc20"
        params = {
            "only_confirmed": "true",
            "limit": "50",
            "contract_address": USDT_TRC20_CONTRACT,
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=20)) as response:
                if response.status >= 500:
                    raise CryptoPaymentError("Temporary TronGrid error")
                if response.status >= 400:
                    text = await response.text()
                    raise CryptoPaymentError(f"TronGrid error {response.status}: {text[:200]}")
                payload = await response.json()
        for item in payload.get("data", []):
            if normalize_tx_hash(item.get("transaction_id", "")) != tx_hash:
                continue
            value = Decimal(item.get("value", "0")) / Decimal("1000000")
            return CryptoTransfer(
                tx_hash=tx_hash,
                to_address=item.get("to", ""),
                amount_usdt=value,
                confirmed=True,
            )
        return None


async def verify_usdt_trc20_payment(
    settings: Settings,
    wallet: str,
    tx_hash: str,
    expected_usdt: Decimal,
) -> CryptoTransfer:
    transfer = await TronGridClient(settings).get_usdt_transfer(wallet, tx_hash)
    if not transfer:
        raise CryptoPaymentError("Transaction not found or not confirmed yet")
    if transfer.to_address != wallet:
        raise CryptoPaymentError("Transaction was not sent to the configured wallet")
    if transfer.amount_usdt < expected_usdt:
        raise CryptoPaymentError("Transaction amount is lower than required")
    return transfer
