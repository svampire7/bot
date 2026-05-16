from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.keyboards.admin import pending_wallet_keyboard
from app.bot.keyboards.user import (
    back_to_menu_keyboard,
    main_menu,
    wallet_card_keyboard,
    wallet_crypto_keyboard,
    wallet_keyboard,
)
from app.config import Settings
from app.db.repositories import (
    get_or_create_user,
    order_by_crypto_tx_hash,
    wallet_history,
    wallet_transaction_by_crypto_tx_hash,
)
from app.services.crypto_service import (
    CryptoPaymentError,
    normalize_tx_hash,
    toman_to_ltc,
    validate_tx_hash,
    verify_ltc_payment,
)
from app.services.payment_service import PaymentService
from app.services.wallet_service import WalletService
from app.utils.formatters import html_code, html_escape, toman
from app.utils.validators import parse_positive_int

router = Router()
logger = logging.getLogger(__name__)


class WalletStates(StatesGroup):
    amount = State()
    receipt = State()
    crypto_tx = State()


def wallet_history_text(_, rows) -> str:
    if not rows:
        return _("wallet_empty_history")
    return "\n".join(
        _(
            "wallet_history_line",
            id=row.id,
            type=_("wallet_type_" + row.transaction_type),
            amount=toman(row.amount_toman),
            status=_("status_" + row.status),
            date=row.created_at.strftime("%Y-%m-%d %H:%M"),
        )
        for row in rows
    )


@router.callback_query(F.data == "menu:wallet")
async def wallet_menu(
    callback: CallbackQuery, state: FSMContext, sessionmaker: async_sessionmaker, settings: Settings, _
) -> None:
    assert callback.from_user
    await state.clear()
    async with sessionmaker() as session:
        user = await get_or_create_user(
            session,
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name,
            settings.default_language,
        )
        balance = await WalletService().balance(session, user.id)
        history = await wallet_history(session, user.id, limit=6)
        await session.commit()
    text = _("wallet_text", balance=toman(balance), history=wallet_history_text(_, history))
    try:
        await callback.message.edit_text(text, reply_markup=wallet_keyboard(_))  # type: ignore[union-attr]
    except TelegramBadRequest:
        await callback.message.edit_caption(caption=text, reply_markup=wallet_keyboard(_))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data.in_({"wallet:topup:card", "wallet:topup:ltc"}))
async def ask_wallet_amount(callback: CallbackQuery, state: FSMContext, _) -> None:
    method = "card" if callback.data == "wallet:topup:card" else "crypto_ltc"
    await state.update_data(wallet_payment_method=method)
    await state.set_state(WalletStates.amount)
    await callback.message.edit_text(_("enter_topup_amount"), reply_markup=back_to_menu_keyboard(_))  # type: ignore[union-attr]
    await callback.answer()


@router.message(WalletStates.amount)
async def wallet_amount_entered(
    message: Message,
    state: FSMContext,
    sessionmaker: async_sessionmaker,
    settings: Settings,
    _,
) -> None:
    amount = parse_positive_int(message.text or "")
    if not amount:
        await message.answer(_("invalid_topup_amount"))
        return
    data = await state.get_data()
    payment = PaymentService(settings)
    async with sessionmaker() as session:
        if data.get("wallet_payment_method") == "card":
            card_number = await payment.card_number(session)
            text = _(
                "wallet_card_instructions",
                amount=toman(amount),
                card_number=html_code(card_number),
                card_holder=html_escape(await payment.card_holder_name(session)),
                bank=html_escape(await payment.bank_name(session)),
                support=html_code(await payment.support_username(session)),
            )
            await state.update_data(amount_toman=amount)
            await state.set_state(WalletStates.receipt)
            await message.answer(text, reply_markup=wallet_card_keyboard(_, card_number))
            return
        wallet = await payment.crypto_ltc_wallet(session)
        qr_file_id = await payment.crypto_ltc_qr_file_id(session)
        rate = await payment.ltc_toman_rate(session)
    if not wallet:
        await message.answer(_("crypto_not_configured"), reply_markup=main_menu(_))
        await state.clear()
        return
    expected = toman_to_ltc(amount, rate)
    await state.update_data(amount_toman=amount, crypto_expected_ltc=str(expected))
    await state.set_state(WalletStates.crypto_tx)
    text = _(
        "wallet_ltc_instructions",
        amount=toman(amount),
        ltc=str(expected),
        wallet=html_code(wallet),
        rate=toman(rate),
    )
    if qr_file_id:
        await message.answer_photo(qr_file_id, caption=text, reply_markup=wallet_crypto_keyboard(_, wallet))
    else:
        await message.answer(text, reply_markup=wallet_crypto_keyboard(_, wallet))


@router.message(WalletStates.receipt)
async def wallet_receipt_uploaded(
    message: Message,
    state: FSMContext,
    sessionmaker: async_sessionmaker,
    settings: Settings,
    redis: Redis,
    bot,
    _,
) -> None:
    assert message.from_user
    receipt_file_id = None
    receipt_is_document = False
    if message.photo:
        receipt_file_id = message.photo[-1].file_id
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        receipt_file_id = message.document.file_id
        receipt_is_document = True
    if not receipt_file_id:
        await message.answer(_("receipt_required"))
        return
    if not await redis.set(f"wallet_receipt:{message.from_user.id}", "1", nx=True, ex=20):
        return
    data = await state.get_data()
    async with sessionmaker.begin() as session:
        user = await get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            settings.default_language,
        )
        tx = await WalletService().create_card_topup(
            session, user.id, int(data["amount_toman"]), receipt_file_id
        )
    await state.clear()
    await message.answer(_("wallet_receipt_created", tx_id=tx.id), reply_markup=main_menu(_))
    await notify_admins_about_wallet_topup(
        bot,
        settings,
        _,
        tx.id,
        int(data["amount_toman"]),
        message.from_user.username,
        message.from_user.id,
        receipt_file_id,
        receipt_is_document,
    )


@router.message(WalletStates.crypto_tx)
async def wallet_crypto_tx_submitted(
    message: Message,
    state: FSMContext,
    sessionmaker: async_sessionmaker,
    settings: Settings,
    redis: Redis,
    _,
) -> None:
    assert message.from_user
    tx_hash = normalize_tx_hash(message.text or "")
    if not validate_tx_hash(tx_hash):
        await message.answer(_("invalid_crypto_tx"))
        return
    if not await redis.set(f"wallet_crypto_check:{message.from_user.id}", "1", nx=True, ex=20):
        return
    data = await state.get_data()
    payment = PaymentService(settings)
    async with sessionmaker() as session:
        order_existing = await order_by_crypto_tx_hash(session, tx_hash)
        wallet_existing = await wallet_transaction_by_crypto_tx_hash(session, tx_hash)
        wallet = await payment.crypto_ltc_wallet(session)
        rate = await payment.ltc_toman_rate(session)
    if order_existing or wallet_existing:
        await message.answer(_("crypto_tx_already_used"))
        return
    try:
        transfer = await verify_ltc_payment(
            settings,
            wallet,
            tx_hash,
            toman_to_ltc(int(data["amount_toman"]), rate),
        )
    except CryptoPaymentError as exc:
        await message.answer(_("crypto_check_failed", error=html_escape(str(exc))))
        return
    async with sessionmaker.begin() as session:
        user = await get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            settings.default_language,
        )
        tx = await WalletService().create_ltc_topup(
            session,
            user.id,
            int(data["amount_toman"]),
            tx_hash,
            str(transfer.amount_ltc),
        )
        balance = await WalletService().balance(session, user.id)
    await state.clear()
    await message.answer(
        _("wallet_ltc_topup_done", amount=toman(tx.amount_toman), balance=toman(balance)),
        reply_markup=main_menu(_),
    )


async def notify_admins_about_wallet_topup(
    bot,
    settings: Settings,
    _,
    tx_id: int,
    amount_toman: int,
    telegram_username: str | None,
    telegram_id: int,
    receipt_file_id: str,
    receipt_is_document: bool,
) -> None:
    text = _(
        "wallet_topup_admin",
        id=tx_id,
        username=telegram_username or "-",
        telegram_id=telegram_id,
        amount=toman(amount_toman),
    )
    for admin_id in settings.admin_telegram_ids:
        try:
            if receipt_is_document:
                await bot.send_document(
                    admin_id,
                    receipt_file_id,
                    caption=text,
                    reply_markup=pending_wallet_keyboard(tx_id, _),
                )
            else:
                await bot.send_photo(
                    admin_id,
                    receipt_file_id,
                    caption=text,
                    reply_markup=pending_wallet_keyboard(tx_id, _),
                )
        except Exception:
            logger.exception(
                "Failed to notify admin about wallet topup",
                extra={"admin_id": admin_id, "wallet_tx_id": tx_id},
            )
