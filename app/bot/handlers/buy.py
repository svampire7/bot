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
    UnlimitedPackageCb,
    back_to_menu_keyboard,
    crypto_payment_keyboard,
    main_menu,
    packages_keyboard,
    payment_keyboard,
    purchase_target_keyboard,
    service_copy_keyboard,
    unlimited_packages_keyboard,
    wallet_keyboard,
    wallet_purchase_keyboard,
)
from app.config import Settings
from app.db.repositories import get_or_create_user, get_or_create_user_by_telegram_id, order_by_crypto_tx_hash
from app.db.models import PackageType, User
from app.services.crypto_service import (
    CryptoPaymentError,
    normalize_tx_hash,
    toman_to_ltc,
    validate_tx_hash,
    verify_ltc_payment,
)
from app.services.discount_service import apply_discount
from app.services.order_service import OrderService
from app.services.payment_service import PaymentService
from app.services.referral_service import notify_referrer_about_reward
from app.services.vpn_service import VPNProvisioningService
from app.services.wallet_service import InsufficientWalletBalance, WalletService
from app.utils.formatters import duration_label, html_code, html_code_lines, html_escape, optional_datetime, optional_gb, toman
from app.utils.validators import parse_positive_int

router = Router()
logger = logging.getLogger(__name__)


class BuyStates(StatesGroup):
    custom_gb = State()
    recipient_telegram_id = State()
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
    package_type: str = PackageType.traffic.value,
    duration_days: int | None = None,
    recipient_telegram_id: int | None = None,
):
    payment = PaymentService(settings)
    assert callback.from_user
    async with sessionmaker() as session:
        user = await get_or_create_user(
            session,
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name,
            settings.default_language,
        )
        price_per_gb = await payment.price_per_gb(session)
        min_gb = await payment.min_custom_gb(session)
        max_gb = await payment.max_custom_gb(session)
        if package_type == PackageType.traffic.value and (gb < min_gb or gb > max_gb):
            await callback.message.answer(_("invalid_gb", min_gb=min_gb, max_gb=max_gb))  # type: ignore[union-attr]
            return
        recipient_telegram_id = recipient_telegram_id or callback.from_user.id
        recipient_user = await get_or_create_user_by_telegram_id(
            session,
            recipient_telegram_id,
            settings.default_language,
        )
        price = package_price if package_price is not None else gb * price_per_gb
        balance = await WalletService().balance(session, user.id)
        await state.update_data(
            gb=gb,
            price=price,
            original_price=price,
            discount_code=None,
            discount_amount=0,
            package_type=package_type,
            duration_days=duration_days,
            buyer_user_id=user.id,
            recipient_user_id=recipient_user.id,
            recipient_telegram_id=recipient_user.telegram_id,
            buying_for_other=recipient_user.telegram_id != user.telegram_id,
        )
        await session.commit()
    await state.set_state(BuyStates.payment_method)
    await callback.message.edit_text(  # type: ignore[union-attr]
        _("wallet_purchase_prompt",
          package=order_package_label(_, package_type, gb, duration_days),
          recipient=recipient_label(_, recipient_telegram_id, recipient_telegram_id != callback.from_user.id),
          gb=gb,
          price=toman(price),
          balance=toman(balance)),
        reply_markup=wallet_purchase_keyboard(_),
    )
    await callback.answer()


def order_package_label(_, package_type: str, gb: int, duration_days: int | None = None) -> str:
    if package_type == PackageType.unlimited_time.value:
        return _("unlimited_time_package_label", duration=duration_label(duration_days))
    return _("traffic_package_label", gb=gb)


def recipient_label(_, telegram_id: int, buying_for_other: bool) -> str:
    if buying_for_other:
        return _("recipient_other_label", telegram_id=telegram_id)
    return _("recipient_self_label")


async def ask_purchase_target(
    callback: CallbackQuery,
    state: FSMContext,
    _,
    *,
    gb: int,
    price: int,
    package_type: str,
    duration_days: int | None = None,
) -> None:
    await state.update_data(
        gb=gb,
        price=price,
        original_price=price,
        discount_code=None,
        discount_amount=0,
        package_type=package_type,
        duration_days=duration_days,
    )
    await callback.message.edit_text(  # type: ignore[union-attr]
        _("select_purchase_target", package=order_package_label(_, package_type, gb, duration_days), price=toman(price)),
        reply_markup=purchase_target_keyboard(_),
    )
    await callback.answer()


@router.callback_query(F.data.in_({"menu:buy", "menu:renew"}))
async def buy_menu(
    callback: CallbackQuery, state: FSMContext, sessionmaker: async_sessionmaker, settings: Settings, _
) -> None:
    await state.clear()
    async with sessionmaker() as session:
        packages = await PaymentService(settings).package_prices(session)
    await callback.message.edit_text(_("select_package"), reply_markup=packages_keyboard(_, packages))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "menu:buy_unlimited")
async def unlimited_buy_menu(
    callback: CallbackQuery, state: FSMContext, sessionmaker: async_sessionmaker, settings: Settings, _
) -> None:
    await state.clear()
    async with sessionmaker() as session:
        packages = await PaymentService(settings).unlimited_time_packages(session)
    await callback.message.edit_text(  # type: ignore[union-attr]
        _("select_unlimited_package"),
        reply_markup=unlimited_packages_keyboard(_, packages),
    )
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
    await ask_purchase_target(
        callback,
        state,
        _,
        gb=callback_data.gb,
        price=package_price,
        package_type=PackageType.traffic.value,
    )


@router.callback_query(UnlimitedPackageCb.filter())
async def unlimited_package_selected(
    callback: CallbackQuery,
    callback_data: UnlimitedPackageCb,
    state: FSMContext,
    sessionmaker: async_sessionmaker,
    settings: Settings,
    _,
) -> None:
    async with sessionmaker() as session:
        package_price = await PaymentService(settings).unlimited_time_package_price(session, callback_data.days)
    if package_price is None:
        await callback.answer(_("package_not_available"), show_alert=True)
        return
    await ask_purchase_target(
        callback,
        state,
        _,
        gb=0,
        price=package_price,
        package_type=PackageType.unlimited_time.value,
        duration_days=callback_data.days,
    )


@router.callback_query(F.data == "target:self")
async def purchase_for_self(
    callback: CallbackQuery,
    state: FSMContext,
    sessionmaker: async_sessionmaker,
    settings: Settings,
    _,
) -> None:
    data = await state.get_data()
    if "price" not in data or "gb" not in data:
        await callback.answer(_("package_not_available"), show_alert=True)
        return
    await show_payment(
        callback,
        state,
        int(data["gb"]),
        sessionmaker,
        settings,
        _,
        int(data["price"]),
        package_type=str(data.get("package_type") or PackageType.traffic.value),
        duration_days=int(data["duration_days"]) if data.get("duration_days") else None,
        recipient_telegram_id=callback.from_user.id,
    )


@router.callback_query(F.data == "target:other")
async def ask_recipient_telegram_id(callback: CallbackQuery, state: FSMContext, _) -> None:
    data = await state.get_data()
    if "price" not in data or "gb" not in data:
        await callback.answer(_("package_not_available"), show_alert=True)
        return
    await state.set_state(BuyStates.recipient_telegram_id)
    await callback.message.edit_text(_("enter_recipient_telegram_id"), reply_markup=back_to_menu_keyboard(_))  # type: ignore[union-attr]
    await callback.answer()


@router.message(BuyStates.recipient_telegram_id)
async def recipient_telegram_id_entered(
    message: Message,
    state: FSMContext,
    sessionmaker: async_sessionmaker,
    settings: Settings,
    _,
) -> None:
    telegram_id = parse_positive_int(message.text or "")
    if not telegram_id:
        await message.answer(_("invalid_recipient_telegram_id"), reply_markup=back_to_menu_keyboard(_))
        return
    data = await state.get_data()
    await show_payment_from_message(
        message,
        state,
        int(data["gb"]),
        sessionmaker,
        settings,
        _,
        int(data["price"]),
        package_type=str(data.get("package_type") or PackageType.traffic.value),
        duration_days=int(data["duration_days"]) if data.get("duration_days") else None,
        recipient_telegram_id=telegram_id,
    )


async def show_payment_from_message(
    message: Message,
    state: FSMContext,
    gb: int,
    sessionmaker,
    settings,
    _,
    package_price: int,
    package_type: str,
    duration_days: int | None,
    recipient_telegram_id: int,
) -> None:
    assert message.from_user
    payment = PaymentService(settings)
    async with sessionmaker() as session:
        user = await get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            settings.default_language,
        )
        min_gb = await payment.min_custom_gb(session)
        max_gb = await payment.max_custom_gb(session)
        if package_type == PackageType.traffic.value and (gb < min_gb or gb > max_gb):
            await message.answer(_("invalid_gb", min_gb=min_gb, max_gb=max_gb))
            return
        recipient_user = await get_or_create_user_by_telegram_id(
            session,
            recipient_telegram_id,
            settings.default_language,
        )
        balance = await WalletService().balance(session, user.id)
        await state.update_data(
            gb=gb,
            price=package_price,
            original_price=package_price,
            discount_code=None,
            discount_amount=0,
            package_type=package_type,
            duration_days=duration_days,
            buyer_user_id=user.id,
            recipient_user_id=recipient_user.id,
            recipient_telegram_id=recipient_user.telegram_id,
            buying_for_other=recipient_user.telegram_id != user.telegram_id,
        )
        await session.commit()
    await state.set_state(BuyStates.payment_method)
    await message.answer(
        _("wallet_purchase_prompt",
          package=order_package_label(_, package_type, gb, duration_days),
          recipient=recipient_label(_, recipient_telegram_id, recipient_telegram_id != message.from_user.id),
          gb=gb,
          price=toman(package_price),
          balance=toman(balance)),
        reply_markup=wallet_purchase_keyboard(_),
    )


@router.callback_query(F.data == "pkg:custom")
async def custom_package(callback: CallbackQuery, state: FSMContext, _) -> None:
    await state.set_state(BuyStates.custom_gb)
    await callback.message.edit_text(_("enter_custom_gb"), reply_markup=back_to_menu_keyboard(_))  # type: ignore[union-attr]
    await callback.answer()


@router.message(BuyStates.custom_gb)
async def custom_gb(
    message: Message, state: FSMContext, sessionmaker: async_sessionmaker, settings: Settings, _
) -> None:
    assert message.from_user
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
        user = await get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            settings.default_language,
        )
        balance = await WalletService().balance(session, user.id)
        await state.update_data(
            gb=gb,
            price=price,
            original_price=price,
            discount_code=None,
            discount_amount=0,
            package_type=PackageType.traffic.value,
            duration_days=None,
        )
    await message.answer(
        _("select_purchase_target", package=order_package_label(_, PackageType.traffic.value, gb), price=toman(price)),
        reply_markup=purchase_target_keyboard(_),
    )


@router.callback_query(F.data == "pay:wallet", BuyStates.payment_method)
async def wallet_payment_selected(
    callback: CallbackQuery,
    state: FSMContext,
    sessionmaker: async_sessionmaker,
    settings: Settings,
    bot,
    i18n,
    _,
) -> None:
    assert callback.from_user
    data = await state.get_data()
    order_id = None
    failure_error = None
    try:
        async with sessionmaker.begin() as session:
            buyer = await get_or_create_user(
                session,
                callback.from_user.id,
                callback.from_user.username,
                callback.from_user.first_name,
                settings.default_language,
            )
            recipient_user_id = int(data.get("recipient_user_id") or buyer.id)
            recipient = await session.get(User, recipient_user_id)
            if recipient is None:
                recipient = buyer
            final_price = int(data["price"])
            balance = await WalletService().balance(session, buyer.id)
            if balance < final_price:
                await callback.answer(
                    _(
                        "insufficient_wallet_balance_detail",
                        balance=toman(balance),
                        required=toman(final_price),
                    ),
                    show_alert=True,
                )
                return
            order = await OrderService(settings).create_order(
                session,
                recipient.id,
                int(data["gb"]),
                final_price,
                None,
                original_price_toman=int(data.get("original_price") or final_price),
                discount_code=data.get("discount_code"),
                discount_amount_toman=int(data.get("discount_amount") or 0),
                payment_method="wallet",
                package_type=str(data.get("package_type") or PackageType.traffic.value),
                duration_days=int(data["duration_days"]) if data.get("duration_days") else None,
                purchased_by_user_id=buyer.id,
            )
            order_id = order.id
            await WalletService().spend(session, buyer.id, final_price, order.id)
            try:
                service, _created, config_links, referral_reward = await VPNProvisioningService(settings).approve_order(
                    session, order.id
                )
            except Exception as exc:
                failure_error = str(exc)
                await WalletService().refund(
                    session,
                    buyer.id,
                    final_price,
                    order.id,
                    note=f"Provisioning failed: {exc}",
                )
                text = ""
                subscription_url = None
            else:
                text = service_ready_text(i18n.t, recipient.language, order, service, config_links)
                subscription_url = service.subscription_url
                recipient_telegram_id = recipient.telegram_id
                recipient_language = recipient.language
                buyer_telegram_id = buyer.telegram_id
    except InsufficientWalletBalance:
        await callback.answer(_("insufficient_wallet_balance"), show_alert=True)
        return
    except Exception as exc:
        logger.exception("Wallet purchase failed", extra={"order_id": order_id})
        await callback.answer(_("wallet_purchase_failed", error=str(exc)), show_alert=True)
        return
    if failure_error:
        logger.error("Wallet purchase provisioning failed", extra={"order_id": order_id, "error": failure_error})
        await callback.answer(_("wallet_purchase_failed", error=failure_error), show_alert=True)
        return
    if referral_reward.referred_bonus_gb:
        text += "\n\n" + _("referral_friend_bonus_applied", bonus_gb=referral_reward.referred_bonus_gb)
    if referral_reward.pending_bonus_gb:
        text += "\n" + _("referral_pending_bonus_applied", bonus_gb=referral_reward.pending_bonus_gb)
    await state.clear()
    delivery_note = ""
    if recipient_telegram_id != buyer_telegram_id:
        try:
            await bot.send_message(
                recipient_telegram_id,
                text,
                reply_markup=service_copy_keyboard(_, subscription_url),
            )
        except Exception:
            logger.exception("Failed to deliver gifted service", extra={"order_id": order_id, "recipient": recipient_telegram_id})
            delivery_note = "\n\n" + _("gift_delivery_failed", telegram_id=recipient_telegram_id)
        else:
            delivery_note = "\n\n" + _("gift_delivered", telegram_id=recipient_telegram_id)
    await callback.message.edit_text(  # type: ignore[union-attr]
        text + delivery_note,
        reply_markup=service_copy_keyboard(_, subscription_url),
    )
    await notify_referrer_about_reward(bot, i18n, referral_reward)
    await callback.answer()


def service_ready_text(t, language: str, order, service, config_links: list[str]) -> str:
    if order.package_type == PackageType.unlimited_time.value:
        return t(
            "service_ready_unlimited",
            language,
            duration=duration_label(order.duration_days),
            expire_at=optional_datetime(service.expire_at),
            used=optional_gb(service.used_traffic_gb),
            subscription_url=html_code(service.subscription_url or "-"),
            config_links=html_code_lines(config_links)
            if config_links
            else t("configs_not_available", language),
        )
    return t(
        "service_ready",
        language,
        purchased_gb=order.gb_amount,
        total_gb=optional_gb(service.data_limit_gb),
        used=optional_gb(service.used_traffic_gb),
        remaining=optional_gb(service.remaining_traffic_gb),
        subscription_url=html_code(service.subscription_url or "-"),
        config_links=html_code_lines(config_links)
        if config_links
        else t("configs_not_available", language),
    )


@router.callback_query(F.data == "pay:card", BuyStates.payment_method)
async def card_payment_selected(
    callback: CallbackQuery,
    state: FSMContext,
    sessionmaker: async_sessionmaker,
    settings: Settings,
    _,
) -> None:
    await state.clear()
    await callback.message.edit_text(_("wallet_required_payment"), reply_markup=wallet_keyboard(_))  # type: ignore[union-attr]
    await callback.answer()
    return
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
    await state.clear()
    await callback.message.edit_text(_("wallet_required_payment"), reply_markup=wallet_keyboard(_))  # type: ignore[union-attr]
    await callback.answer()
    return
    data = await state.get_data()
    payment = PaymentService(settings)
    async with sessionmaker() as session:
        wallet = await payment.crypto_ltc_wallet(session)
        qr_file_id = await payment.crypto_ltc_qr_file_id(session)
        rate = await payment.ltc_toman_rate(session)
    if not wallet:
        await callback.answer(_("crypto_not_configured"), show_alert=True)
        return
    expected = toman_to_ltc(int(data["price"]), rate)
    await state.update_data(payment_method="crypto_ltc", crypto_expected_usdt=str(expected))
    await state.set_state(BuyStates.crypto_tx)
    text = _("crypto_payment_instructions",
             gb=int(data["gb"]),
             price=toman(int(data["price"])),
             ltc=str(expected),
             wallet=html_code(wallet),
             rate=toman(rate))
    if qr_file_id:
        await callback.message.answer_photo(  # type: ignore[union-attr]
            qr_file_id,
            caption=text,
            reply_markup=crypto_payment_keyboard(_, wallet),
        )
    else:
        await callback.message.edit_text(text, reply_markup=crypto_payment_keyboard(_, wallet))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "pay:discount", BuyStates.payment_method)
async def ask_discount_code(callback: CallbackQuery, state: FSMContext, _) -> None:
    await state.set_state(BuyStates.discount_code)
    await callback.message.answer(_("enter_discount_code"), reply_markup=back_to_menu_keyboard(_))  # type: ignore[union-attr]
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
        await message.answer(_("discount_invalid"), reply_markup=wallet_purchase_keyboard(_))
        return
    await state.update_data(price=final_price, discount_code=discount.code, discount_amount=amount)
    await state.set_state(BuyStates.payment_method)
    assert message.from_user
    async with sessionmaker() as session:
        user = await get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            settings.default_language,
        )
        balance = await WalletService().balance(session, user.id)
        await session.commit()
    await message.answer(
        _("discount_applied", code=discount.code, discount=toman(amount), price=toman(final_price)),
        reply_markup=wallet_purchase_keyboard(_, allow_discount=False),
    )
    await message.answer(
        _("wallet_purchase_prompt",
          package=order_package_label(
              _,
              str(data.get("package_type") or PackageType.traffic.value),
              int(data["gb"]),
              int(data["duration_days"]) if data.get("duration_days") else None,
          ),
          recipient=recipient_label(
              _,
              int(data.get("recipient_telegram_id") or message.from_user.id),
              bool(data.get("buying_for_other")),
          ),
          gb=int(data["gb"]),
          price=toman(final_price),
          balance=toman(balance)),
        reply_markup=wallet_purchase_keyboard(_, allow_discount=False),
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
        wallet = await payment.crypto_ltc_wallet(session)
        rate = await payment.ltc_toman_rate(session)
    if existing:
        await message.answer(_("crypto_tx_already_used"))
        return
    try:
        transfer = await verify_ltc_payment(
            settings,
            wallet,
            tx_hash,
            toman_to_ltc(int(data["price"]), rate),
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
            payment_method="crypto_ltc",
            crypto_tx_hash=tx_hash,
            crypto_expected_usdt=str(data.get("crypto_expected_usdt") or transfer.amount_ltc),
            package_type=str(data.get("package_type") or PackageType.traffic.value),
            duration_days=int(data["duration_days"]) if data.get("duration_days") else None,
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
            package_type=str(data.get("package_type") or PackageType.traffic.value),
            duration_days=int(data["duration_days"]) if data.get("duration_days") else None,
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
                   package=order_package_label(_, order.package_type, order.gb_amount, order.duration_days),
                   crypto_tx_hash=order.crypto_tx_hash or "-",
                   crypto_expected_usdt=order.crypto_expected_usdt or "-",
                   service="-",
                   total_orders=1,
                   completed_orders=0,
                   duplicate_pending=0,
                   duplicate_receipts=0,
                   duplicate_crypto=0,
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
