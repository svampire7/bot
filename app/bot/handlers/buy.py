from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.keyboards.user import PackageCb, back_to_menu_keyboard, main_menu, packages_keyboard
from app.config import Settings
from app.db.repositories import get_or_create_user
from app.services.order_service import OrderService
from app.services.payment_service import PaymentService
from app.utils.formatters import html_code, html_escape, toman
from app.utils.validators import parse_positive_int

router = Router()
logger = logging.getLogger(__name__)


class BuyStates(StatesGroup):
    custom_gb = State()
    receipt = State()


async def show_payment(callback: CallbackQuery, state: FSMContext, gb: int, sessionmaker, settings, _):
    payment = PaymentService(settings)
    async with sessionmaker() as session:
        price_per_gb = await payment.price_per_gb(session)
        min_gb = await payment.min_custom_gb(session)
        max_gb = await payment.max_custom_gb(session)
        if gb < min_gb or gb > max_gb:
            await callback.message.answer(_("invalid_gb", min_gb=min_gb, max_gb=max_gb))  # type: ignore[union-attr]
            return
        await state.update_data(gb=gb, price=gb * price_per_gb)
        text = _("payment_instructions", gb=gb, price=toman(gb * price_per_gb),
                 card_number=html_code(await payment.card_number(session)),
                 card_holder=html_escape(settings.card_holder_name),
                 bank=html_escape(settings.bank_name),
                 support=html_code(await payment.support_username(session)))
    await state.set_state(BuyStates.receipt)
    await callback.message.edit_text(text, reply_markup=back_to_menu_keyboard(_))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data.in_({"menu:buy", "menu:renew"}))
async def buy_menu(callback: CallbackQuery, _) -> None:
    await callback.message.edit_text(_("select_package"), reply_markup=packages_keyboard(_))  # type: ignore[union-attr]
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
    await show_payment(callback, state, callback_data.gb, sessionmaker, settings, _)


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
        await state.update_data(gb=gb, price=gb * price_per_gb)
        text = _("payment_instructions", gb=gb, price=toman(gb * price_per_gb),
                 card_number=html_code(await payment.card_number(session)),
                 card_holder=html_escape(settings.card_holder_name),
                 bank=html_escape(settings.bank_name),
                 support=html_code(await payment.support_username(session)))
    await state.set_state(BuyStates.receipt)
    await message.answer(text, reply_markup=back_to_menu_keyboard(_))


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
    if not message.photo:
        await message.answer(_("receipt_required"))
        return
    throttle_key = f"receipt_upload:{message.from_user.id}"
    if not await redis.set(throttle_key, "1", nx=True, ex=20):
        return
    data = await state.get_data()
    receipt_file_id = message.photo[-1].file_id
    async with sessionmaker() as session:
        user = await get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            settings.default_language,
        )
        order = await OrderService(settings).create_order(
            session, user.id, int(data["gb"]), int(data["price"]), receipt_file_id
        )
        await session.commit()
    await state.clear()
    await message.answer(_("order_created", order_id=order.id), reply_markup=main_menu(_))
    from app.bot.keyboards.admin import pending_order_keyboard
    admin_text = _("admin_order",
                   id=order.id,
                   username=message.from_user.username or "-",
                   telegram_id=message.from_user.id,
                   gb=order.gb_amount,
                   price=toman(order.price_toman),
                   date=order.created_at.strftime("%Y-%m-%d %H:%M"))
    for admin_id in settings.admin_telegram_ids:
        try:
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
