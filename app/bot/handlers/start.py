from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.handlers.buy import load_purchase_draft, send_config_messages, service_summary_text
from app.bot.keyboards.user import invite_keyboard, language_keyboard, main_menu, service_copy_keyboard
from app.config import Settings
from app.db.repositories import (
    ensure_card_reference_code,
    get_or_create_user,
    referral_stats,
    set_referrer_if_allowed,
)
from app.services.gift_service import GiftRedeemInvalid, GiftRedeemNotReady, GiftRedeemUsed, redeem_gift_order
from app.services.payment_service import PaymentService
from app.services.referral_service import notify_referrer_about_reward
from app.utils.formatters import html_escape

router = Router()


@router.message(CommandStart())
async def start(
    message: Message, command: CommandObject, sessionmaker: async_sessionmaker, settings: Settings, bot, i18n, _
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
            try:
                result = await redeem_gift_order(session, settings, user, payload[5:])
                text = service_summary_text(i18n.t, user.language, result.order, result.service)
                await session.commit()
                await message.answer(
                    _("gift_claim_ready") + "\n\n" + text,
                    reply_markup=service_copy_keyboard(_, result.service.subscription_url),
                )
                await send_config_messages(message, _, result.config_links, user.language, i18n.t)
                await notify_referrer_about_reward(bot, i18n, result.referral_reward)
            except GiftRedeemInvalid:
                await session.commit()
                await message.answer(_("redeem_code_invalid"), reply_markup=main_menu(_))
            except GiftRedeemUsed:
                await session.commit()
                await message.answer(_("redeem_code_used"), reply_markup=main_menu(_))
            except GiftRedeemNotReady as exc:
                await session.commit()
                await message.answer(_("gift_claim_not_ready", status=_("status_" + exc.status)), reply_markup=main_menu(_))
            except Exception as exc:
                await session.rollback()
                await message.answer(_("redeem_code_failed", error=html_escape(str(exc))), reply_markup=main_menu(_))
            return
        await session.commit()
    await message.answer(_("start"), reply_markup=language_keyboard())


@router.message(Command("menu"))
async def menu(message: Message, state: FSMContext, sessionmaker: async_sessionmaker, settings: Settings, redis, _) -> None:
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
    has_saved = bool(await load_purchase_draft(redis, message.from_user.id))
    await message.answer(_("main_menu"), reply_markup=main_menu(_, has_saved_purchase=has_saved))


@router.message(Command("id"))
async def show_telegram_id(message: Message, _) -> None:
    assert message.from_user
    await message.answer(_("your_telegram_id", telegram_id=message.from_user.id))


@router.callback_query(F.data == "menu:main")
async def show_main_menu(callback: CallbackQuery, state: FSMContext, redis, _) -> None:
    await state.clear()
    assert callback.from_user
    has_saved = bool(await load_purchase_draft(redis, callback.from_user.id))
    try:
        await callback.message.edit_text(_("main_menu"), reply_markup=main_menu(_, has_saved_purchase=has_saved))  # type: ignore[union-attr]
    except TelegramBadRequest:
        await callback.message.edit_caption(caption=_("main_menu"), reply_markup=main_menu(_, has_saved_purchase=has_saved))  # type: ignore[union-attr]
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
