from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    WalletTransaction,
    WalletTransactionStatus,
    WalletTransactionType,
)
from app.db.repositories import wallet_balance


class InsufficientWalletBalance(RuntimeError):
    pass


class WalletService:
    async def balance(self, session: AsyncSession, user_id: int) -> int:
        return await wallet_balance(session, user_id)

    async def create_card_topup(
        self,
        session: AsyncSession,
        user_id: int,
        amount_toman: int,
        receipt_file_id: str,
    ) -> WalletTransaction:
        tx = WalletTransaction(
            user_id=user_id,
            transaction_type=WalletTransactionType.topup_card.value,
            amount_toman=amount_toman,
            status=WalletTransactionStatus.pending_admin.value,
            payment_method="card",
            receipt_file_id=receipt_file_id,
        )
        session.add(tx)
        await session.flush()
        return tx

    async def create_ltc_topup(
        self,
        session: AsyncSession,
        user_id: int,
        amount_toman: int,
        tx_hash: str,
        crypto_amount: str,
    ) -> WalletTransaction:
        tx = WalletTransaction(
            user_id=user_id,
            transaction_type=WalletTransactionType.topup_ltc.value,
            amount_toman=amount_toman,
            status=WalletTransactionStatus.completed.value,
            payment_method="crypto_ltc",
            crypto_tx_hash=tx_hash,
            crypto_amount=crypto_amount,
        )
        session.add(tx)
        await session.flush()
        return tx

    async def spend(
        self,
        session: AsyncSession,
        user_id: int,
        amount_toman: int,
        order_id: int,
    ) -> WalletTransaction:
        balance = await wallet_balance(session, user_id)
        if balance < amount_toman:
            raise InsufficientWalletBalance
        tx = WalletTransaction(
            user_id=user_id,
            order_id=order_id,
            transaction_type=WalletTransactionType.purchase.value,
            amount_toman=-amount_toman,
            status=WalletTransactionStatus.completed.value,
            payment_method="wallet",
        )
        session.add(tx)
        await session.flush()
        return tx

    async def refund(
        self,
        session: AsyncSession,
        user_id: int,
        amount_toman: int,
        order_id: int,
        note: str | None = None,
    ) -> WalletTransaction:
        tx = WalletTransaction(
            user_id=user_id,
            order_id=order_id,
            transaction_type=WalletTransactionType.refund.value,
            amount_toman=amount_toman,
            status=WalletTransactionStatus.completed.value,
            payment_method="wallet",
            admin_note=note,
        )
        session.add(tx)
        await session.flush()
        return tx
