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
    main_menu,
    packages_keyboard,
    payment_keyboard,
)
from app.config import Settings
from app.db.repositories import get_or_create_user
from app.services.discount_service import apply_discount
from app.services.order_service import OrderService
from app.services.payment_service import PaymentService
from app.utils.formatters import html_code, html_escape, toman
from app.utils.validators import parse_positive_int

router = Router()
logger = logging.getLogger(__name__)


class BuyStates(StatesGroup):
    custom_gb = State()
    receipt = State()
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
        card_number = await payment.card_number(session)
        price = package_price if package_price is not None else gb * price_per_gb
        await state.update_data(gb=gb, price=price, original_price=price, discount_code=None, discount_amount=0)
        text = _("payment_instructions", gb=gb, price=toman(price),
                 card_number=html_code(card_number),
                 card_holder=html_escape(settings.card_holder_name),
                 bank=html_escape(settings.bank_name),
                 support=html_code(await payment.support_username(session)))
    await state.set_state(BuyStates.receipt)
    await callback.message.edit_text(text, reply_markup=payment_keyboard(_, card_number))  # type: ignore[union-attr]
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
        card_number = await payment.card_number(session)
        price = gb * price_per_gb
        await state.update_data(
            gb=gb,
            price=price,
            original_price=price,
            discount_code=None,
            discount_amount=0,
        )
        text = _("payment_instructions", gb=gb, price=toman(gb * price_per_gb),
                 card_number=html_code(card_number),
                 card_holder=html_escape(settings.card_holder_name),
                 bank=html_escape(settings.bank_name),
                 support=html_code(await payment.support_username(session)))
    await state.set_state(BuyStates.receipt)
    await message.answer(text, reply_markup=payment_keyboard(_, card_number))


@router.callback_query(F.data == "pay:discount", BuyStates.receipt)
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
        card_number = await PaymentService(settings).card_number(session)
    if not discount:
        await state.set_state(BuyStates.receipt)
        await message.answer(_("discount_invalid"), reply_markup=payment_keyboard(_, card_number))
        return
    await state.update_data(price=final_price, discount_code=discount.code, discount_amount=amount)
    await state.set_state(BuyStates.receipt)
    await message.answer(
        _("discount_applied", code=discount.code, discount=toman(amount), price=toman(final_price)),
        reply_markup=payment_keyboard(_, card_number, allow_discount=False),
    )


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
        )
        await session.commit()
    await state.clear()
    await message.answer(_("order_created", order_id=order.id), reply_markup=main_menu(_))
    from app.bot.keyboards.admin import pending_order_keyboard
    admin_text = _("admin_order",
                   id=order.id,
                   type=_("order_type_" + order.order_type),
                   status=_("status_" + order.status),
                   username=message.from_user.username or "-",
                   telegram_id=message.from_user.id,
                   gb=order.gb_amount,
                   price=toman(order.price_toman),
                   original_price=toman(order.original_price_toman or order.price_toman),
                   discount=toman(order.discount_amount_toman or 0),
                   discount_code=order.discount_code or "-",
                   service="-",
                   total_orders=1,
                   completed_orders=0,
                   duplicate_pending=0,
                   duplicate_receipts=0,
                   date=order.created_at.strftime("%Y-%m-%d %H:%M"))
    for admin_id in settings.admin_telegram_ids:
        try:
            if receipt_is_document:
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
