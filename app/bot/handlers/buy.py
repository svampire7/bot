from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.keyboards.user import (
    PackageCb,
    back_to_menu_keyboard,
    crypto_payment_keyboard,
    main_menu,
    packages_keyboard,
    payment_method_keyboard,
    payment_keyboard,
)
from app.config import Settings
from app.db.repositories import get_or_create_user, order_by_crypto_tx_hash
from app.services.crypto_service import (
    CryptoPaymentError,
    normalize_tx_hash,
    toman_to_usdt,
    validate_tx_hash,
    verify_usdt_trc20_payment,
)
from app.services.discount_service import apply_discount
from app.services.order_service import OrderService
from app.services.payment_service import PaymentService
from app.utils.formatters import html_code, html_escape, toman
from app.utils.validators import parse_positive_int

router = Router()
logger = logging.getLogger(__name__)


class BuyStates(StatesGroup):
    custom_gb = State()
    payment_method = State()
    receipt = State()
    crypto_tx = State()
    discount_code = State()


async def show_payment(
    callback: CallbackQuery,
    state: FSMContext,
    gb: int,
    sessionmaker,
    settings,
    _,
    package_price: int | None = None,
):
    payment = PaymentService(settings)
    async with sessionmaker() as session:
        price_per_gb = await payment.price_per_gb(session)
        min_gb = await payment.min_custom_gb(session)
        max_gb = await payment.max_custom_gb(session)
        if gb < min_gb or gb > max_gb:
            await callback.message.answer(_("invalid_gb", min_gb=min_gb, max_gb=max_gb))  # type: ignore[union-attr]
            return
        price = package_price if package_price is not None else gb * price_per_gb
        await state.update_data(gb=gb, price=price, original_price=price, discount_code=None, discount_amount=0)
    await state.set_state(BuyStates.payment_method)
    await callback.message.edit_text(  # type: ignore[union-attr]
        _("payment_method_prompt", gb=gb, price=toman(price)),
        reply_markup=payment_method_keyboard(_),
    )
    await callback.answer()


@router.callback_query(F.data.in_({"menu:buy", "menu:renew"}))
async def buy_menu(callback: CallbackQuery, sessionmaker: async_sessionmaker, settings: Settings, _) -> None:
    async with sessionmaker() as session:
        packages = await PaymentService(settings).package_prices(session)
    await callback.message.edit_text(_("select_package"), reply_markup=packages_keyboard(_, packages))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(PackageCb.filter())
async def package_selected(
    callback: CallbackQuery,
    callback_data: PackageCb,
    state: FSMContext,
    sessionmaker: async_sessionmaker,
    settings: Settings,
    _,
) -> None:
    async with sessionmaker() as session:
        package_price = await PaymentService(settings).package_price(session, callback_data.gb)
    if package_price is None:
        await callback.answer(_("package_not_available"), show_alert=True)
        return
    await show_payment(callback, state, callback_data.gb, sessionmaker, settings, _, package_price)


@router.callback_query(F.data == "pkg:custom")
async def custom_package(callback: CallbackQuery, state: FSMContext, _) -> None:
    await state.set_state(BuyStates.custom_gb)
    await callback.message.edit_text(_("enter_custom_gb"), reply_markup=back_to_menu_keyboard(_))  # type: ignore[union-attr]
    await callback.answer()


@router.message(BuyStates.custom_gb)
async def custom_gb(
    message: Message, state: FSMContext, sessionmaker: async_sessionmaker, settings: Settings, _
) -> None:
    gb = parse_positive_int(message.text or "")
    payment = PaymentService(settings)
    async with sessionmaker() as session:
        min_gb = await payment.min_custom_gb(session)
        max_gb = await payment.max_custom_gb(session)
        if gb is None or gb < min_gb or gb > max_gb:
            await message.answer(_("invalid_gb", min_gb=min_gb, max_gb=max_gb))
            return
        price_per_gb = await payment.price_per_gb(session)
        price = gb * price_per_gb
        await state.update_data(
            gb=gb,
            price=price,
            original_price=price,
            discount_code=None,
            discount_amount=0,
        )
    await state.set_state(BuyStates.payment_method)
    await message.answer(
        _("payment_method_prompt", gb=gb, price=toman(price)),
        reply_markup=payment_method_keyboard(_),
    )


@router.callback_query(F.data == "pay:card", BuyStates.payment_method)
async def card_payment_selected(
    callback: CallbackQuery,
    state: FSMContext,
    sessionmaker: async_sessionmaker,
    settings: Settings,
    _,
) -> None:
    data = await state.get_data()
    payment = PaymentService(settings)
    async with sessionmaker() as session:
        card_number = await payment.card_number(session)
        text = _("payment_instructions",
                 gb=int(data["gb"]),
                 price=toman(int(data["price"])),
                 card_number=html_code(card_number),
                 card_holder=html_escape(await payment.card_holder_name(session)),
                 bank=html_escape(await payment.bank_name(session)),
                 support=html_code(await payment.support_username(session)))
    await state.update_data(payment_method="card")
    await state.set_state(BuyStates.receipt)
    await callback.message.edit_text(text, reply_markup=payment_keyboard(_, card_number, allow_discount=False))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "pay:crypto", BuyStates.payment_method)
async def crypto_payment_selected(
    callback: CallbackQuery,
    state: FSMContext,
    sessionmaker: async_sessionmaker,
    settings: Settings,
    _,
) -> None:
    data = await state.get_data()
    payment = PaymentService(settings)
    async with sessionmaker() as session:
        wallet = await payment.crypto_usdt_trc20_wallet(session)
        rate = await payment.usdt_toman_rate(session)
    if not wallet:
        await callback.answer(_("crypto_not_configured"), show_alert=True)
        return
    expected = toman_to_usdt(int(data["price"]), rate)
    await state.update_data(payment_method="crypto_usdt_trc20", crypto_expected_usdt=str(expected))
    await state.set_state(BuyStates.crypto_tx)
    await callback.message.edit_text(  # type: ignore[union-attr]
        _("crypto_payment_instructions",
          gb=int(data["gb"]),
          price=toman(int(data["price"])),
          usdt=str(expected),
          wallet=html_code(wallet),
          rate=toman(rate)),
        reply_markup=crypto_payment_keyboard(_, wallet),
    )
    await callback.answer()


@router.callback_query(F.data == "pay:discount", BuyStates.payment_method)
async def ask_discount_code(callback: CallbackQuery, state: FSMContext, _) -> None:
    await state.set_state(BuyStates.discount_code)
    await callback.message.answer(_("enter_discount_code"))  # type: ignore[union-attr]
    await callback.answer()


@router.message(BuyStates.discount_code)
async def discount_code_entered(
    message: Message,
    state: FSMContext,
    sessionmaker: async_sessionmaker,
    settings: Settings,
    _,
) -> None:
    code = (message.text or "").strip()
    data = await state.get_data()
    original_price = int(data.get("original_price") or data["price"])
    async with sessionmaker() as session:
        discount, amount, final_price = await apply_discount(session, code, original_price)
    if not discount:
        await state.set_state(BuyStates.payment_method)
        await message.answer(_("discount_invalid"), reply_markup=payment_method_keyboard(_))
        return
    await state.update_data(price=final_price, discount_code=discount.code, discount_amount=amount)
    await state.set_state(BuyStates.payment_method)
    await message.answer(
        _("discount_applied", code=discount.code, discount=toman(amount), price=toman(final_price)),
        reply_markup=payment_method_keyboard(_, allow_discount=False),
    )


@router.message(BuyStates.crypto_tx)
async def crypto_tx_submitted(
    message: Message,
    state: FSMContext,
    sessionmaker: async_sessionmaker,
    settings: Settings,
    redis: Redis,
    bot,
    _,
) -> None:
    assert message.from_user
    tx_hash = normalize_tx_hash(message.text or "")
    if not validate_tx_hash(tx_hash):
        await message.answer(_("invalid_crypto_tx"))
        return
    throttle_key = f"crypto_check:{message.from_user.id}"
    if not await redis.set(throttle_key, "1", nx=True, ex=20):
        return
    data = await state.get_data()
    payment = PaymentService(settings)
    async with sessionmaker() as session:
        existing = await order_by_crypto_tx_hash(session, tx_hash)
        wallet = await payment.crypto_usdt_trc20_wallet(session)
        rate = await payment.usdt_toman_rate(session)
    if existing:
        await message.answer(_("crypto_tx_already_used"))
        return
    try:
        transfer = await verify_usdt_trc20_payment(
            settings,
            wallet,
            tx_hash,
            toman_to_usdt(int(data["price"]), rate),
        )
    except CryptoPaymentError as exc:
        await message.answer(_("crypto_check_failed", error=html_escape(str(exc))))
        return
    async with sessionmaker() as session:
        user = await get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            settings.default_language,
        )
        order = await OrderService(settings).create_order(
            session,
            user.id,
            int(data["gb"]),
            int(data["price"]),
            None,
            original_price_toman=int(data.get("original_price") or data["price"]),
            discount_code=data.get("discount_code"),
            discount_amount_toman=int(data.get("discount_amount") or 0),
            payment_method="crypto_usdt_trc20",
            crypto_tx_hash=tx_hash,
            crypto_expected_usdt=str(data.get("crypto_expected_usdt") or transfer.amount_usdt),
        )
        await session.commit()
    await state.clear()
    await message.answer(_("crypto_order_created", order_id=order.id), reply_markup=main_menu(_))
    await notify_admins_about_order(bot, settings, _, order, message.from_user.username, message.from_user.id)


@router.message(BuyStates.receipt)
async def receipt_uploaded(
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
    throttle_key = f"receipt_upload:{message.from_user.id}"
    if not await redis.set(throttle_key, "1", nx=True, ex=20):
        return
    data = await state.get_data()
    async with sessionmaker() as session:
        user = await get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            settings.default_language,
        )
        order = await OrderService(settings).create_order(
            session,
            user.id,
            int(data["gb"]),
            int(data["price"]),
            receipt_file_id,
            original_price_toman=int(data.get("original_price") or data["price"]),
            discount_code=data.get("discount_code"),
            discount_amount_toman=int(data.get("discount_amount") or 0),
            payment_method="card",
        )
        await session.commit()
    await state.clear()
    await message.answer(_("order_created", order_id=order.id), reply_markup=main_menu(_))
    await notify_admins_about_order(
        bot,
        settings,
        _,
        order,
        message.from_user.username,
        message.from_user.id,
        receipt_file_id,
        receipt_is_document,
    )


async def notify_admins_about_order(
    bot,
    settings: Settings,
    _,
    order,
    telegram_username: str | None,
    telegram_id: int,
    receipt_file_id: str | None = None,
    receipt_is_document: bool = False,
) -> None:
    from app.bot.keyboards.admin import pending_order_keyboard
    admin_text = _("admin_order",
                   id=order.id,
                   type=_("order_type_" + order.order_type),
                   status=_("status_" + order.status),
                   username=telegram_username or "-",
                   telegram_id=telegram_id,
                   gb=order.gb_amount,
                   price=toman(order.price_toman),
                   original_price=toman(order.original_price_toman or order.price_toman),
                   discount=toman(order.discount_amount_toman or 0),
                   discount_code=order.discount_code or "-",
                   payment_method=_("payment_method_" + order.payment_method),
                   crypto_tx_hash=order.crypto_tx_hash or "-",
                   crypto_expected_usdt=order.crypto_expected_usdt or "-",
                   service="-",
                   total_orders=1,
                   completed_orders=0,
                   duplicate_pending=0,
                   duplicate_receipts=0,
                   date=order.created_at.strftime("%Y-%m-%d %H:%M"))
    for admin_id in settings.admin_telegram_ids:
        try:
            if not receipt_file_id:
                await bot.send_message(
                    admin_id,
                    admin_text,
                    reply_markup=pending_order_keyboard(order.id, _),
                )
            elif receipt_is_document:
                await bot.send_document(
                    admin_id,
                    receipt_file_id,
                    caption=admin_text,
                    reply_markup=pending_order_keyboard(order.id, _),
                )
            else:
                await bot.send_photo(
                    admin_id,
                    receipt_file_id,
                    caption=admin_text,
                    reply_markup=pending_order_keyboard(order.id, _),
                )
        except Exception:
            logger.exception(
                "Failed to notify admin about order",
                extra={"admin_id": admin_id, "order_id": order.id},
            )
