from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.keyboards.user import invite_keyboard, language_keyboard, main_menu
from app.bot.handlers.services import service_info_text
from app.config import Settings
from app.db.models import OrderStatus
from app.db.repositories import (
    active_service_for_user,
    ensure_card_reference_code,
    get_or_create_user,
    order_by_gift_delivery_token,
    referral_stats,
    set_referrer_if_allowed,
)
from app.services.payment_service import PaymentService

router = Router()


@router.message(CommandStart())
async def start(
    message: Message, command: CommandObject, sessionmaker: async_sessionmaker, settings: Settings, _
) -> None:
    assert message.from_user
    payload = (command.args or "").strip()
    async with sessionmaker() as session:
        user = await get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            settings.default_language,
        )
        if payload.startswith("ref_") and payload[4:].isdigit():
            await set_referrer_if_allowed(session, user, int(payload[4:]))
        if payload.startswith("gift_"):
            token = payload[5:].strip()
            order = await order_by_gift_delivery_token(session, token)
            if not order or order.user.telegram_id != user.telegram_id:
                await session.commit()
                await message.answer(_("gift_claim_invalid"), reply_markup=main_menu(_))
                return
            if order.status != OrderStatus.completed.value:
                await session.commit()
                await message.answer(
                    _("gift_claim_not_ready", status=_("status_" + order.status)),
                    reply_markup=main_menu(_),
                )
                return
            service = await active_service_for_user(session, user.id)
            await session.commit()
            if not service:
                await message.answer(_("no_service"), reply_markup=main_menu(_))
                return
            await message.answer(
                _("gift_claim_ready") + "\n\n" + service_info_text(_, service),
                reply_markup=main_menu(_),
            )
            return
        await session.commit()
    await message.answer(_("start"), reply_markup=language_keyboard())


@router.message(Command("menu"))
async def menu(message: Message, state: FSMContext, sessionmaker: async_sessionmaker, settings: Settings, _) -> None:
    assert message.from_user
    await state.clear()
    async with sessionmaker() as session:
        await get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            settings.default_language,
        )
        await session.commit()
    await message.answer(_("main_menu"), reply_markup=main_menu(_))


@router.message(Command("id"))
async def show_telegram_id(message: Message, _) -> None:
    assert message.from_user
    await message.answer(_("your_telegram_id", telegram_id=message.from_user.id))


@router.callback_query(F.data == "menu:main")
async def show_main_menu(callback: CallbackQuery, state: FSMContext, _) -> None:
    await state.clear()
    try:
        await callback.message.edit_text(_("main_menu"), reply_markup=main_menu(_))  # type: ignore[union-attr]
    except TelegramBadRequest:
        await callback.message.edit_caption(caption=_("main_menu"), reply_markup=main_menu(_))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "menu:invite")
async def invite_menu(callback: CallbackQuery, bot, sessionmaker: async_sessionmaker, settings: Settings, _) -> None:
    assert callback.from_user
    me = await bot.get_me()
    invite_link = f"https://t.me/{me.username}?start=ref_{callback.from_user.id}"
    async with sessionmaker() as session:
        bonus_gb = await PaymentService(settings).referral_bonus_gb(session)
        user = await get_or_create_user(
            session,
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name,
            settings.default_language,
        )
        reference_code = await ensure_card_reference_code(session, user)
        stats = await referral_stats(session, user.id)
        await session.commit()
    await callback.message.edit_text(  # type: ignore[union-attr]
        _("invite_text", bonus_gb=bonus_gb, invite_link=invite_link, reference_code=reference_code, **stats),
        reply_markup=invite_keyboard(_, invite_link, reference_code),
    )
    await callback.answer()
