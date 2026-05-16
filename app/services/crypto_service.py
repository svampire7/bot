from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_UP

import aiohttp

from app.config import Settings

TX_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
SATOSHI_PER_LTC = Decimal("100000000")


class CryptoPaymentError(RuntimeError):
    pass


@dataclass(frozen=True)
class CryptoTransfer:
    tx_hash: str
    to_address: str
    amount_ltc: Decimal
    confirmations: int


def toman_to_ltc(price_toman: int, ltc_toman_rate: int) -> Decimal:
    if ltc_toman_rate <= 0:
        raise ValueError("LTC rate must be positive")
    return (Decimal(price_toman) / Decimal(ltc_toman_rate)).quantize(
        Decimal("0.00000001"), rounding=ROUND_UP
    )


def normalize_tx_hash(tx_hash: str) -> str:
    return tx_hash.strip().lower()


def validate_tx_hash(tx_hash: str) -> bool:
    return bool(TX_HASH_RE.fullmatch(normalize_tx_hash(tx_hash)))


class LitecoinClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_transfer_to_wallet(self, wallet: str, tx_hash: str) -> CryptoTransfer | None:
        tx_hash = normalize_tx_hash(tx_hash)
        if not validate_tx_hash(tx_hash):
            raise CryptoPaymentError("Invalid transaction hash")
        url = f"{self.settings.litecoin_api_base_url.rstrip('/')}/txs/{tx_hash}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as response:
                if response.status == 404:
                    return None
                if response.status >= 500:
                    raise CryptoPaymentError("Temporary Litecoin API error")
                if response.status >= 400:
                    text = await response.text()
                    raise CryptoPaymentError(f"Litecoin API error {response.status}: {text[:200]}")
                payload = await response.json()

        confirmations = int(payload.get("confirmations") or 0)
        total_satoshi = 0
        for output in payload.get("outputs", []):
            if wallet in (output.get("addresses") or []):
                total_satoshi += int(output.get("value") or 0)
        if total_satoshi <= 0:
            return None
        return CryptoTransfer(
            tx_hash=tx_hash,
            to_address=wallet,
            amount_ltc=(Decimal(total_satoshi) / SATOSHI_PER_LTC),
            confirmations=confirmations,
        )


async def verify_ltc_payment(
    settings: Settings,
    wallet: str,
    tx_hash: str,
    expected_ltc: Decimal,
) -> CryptoTransfer:
    transfer = await LitecoinClient(settings).get_transfer_to_wallet(wallet, tx_hash)
    if not transfer:
        raise CryptoPaymentError("Transaction not found for the configured wallet")
    if transfer.confirmations < 1:
        raise CryptoPaymentError("Transaction is not confirmed yet")
    if transfer.amount_ltc < expected_ltc:
        raise CryptoPaymentError("Transaction amount is lower than required")
    return transfer
