from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.keyboards.admin import SupportReplyCb, admin_dashboard, support_reply_keyboard
from app.bot.keyboards.user import back_to_menu_keyboard, main_menu
from app.config import Settings
from app.db.models import User
from app.db.repositories import get_user_by_telegram_id
from app.services.admin_service import log_admin_action

router = Router()


class SupportStates(StatesGroup):
    message = State()


class AdminSupportStates(StatesGroup):
    reply = State()


@router.callback_query(F.data == "menu:support")
async def ask_support_message(callback: CallbackQuery, state: FSMContext, _) -> None:
    await state.set_state(SupportStates.message)
    await callback.message.edit_text(_("support_prompt"), reply_markup=back_to_menu_keyboard(_))  # type: ignore[union-attr]
    await callback.answer()


@router.message(SupportStates.message)
async def receive_support_message(
    message: Message,
    state: FSMContext,
    settings: Settings,
    sessionmaker: async_sessionmaker,
    bot,
    _,
) -> None:
    assert message.from_user
    async with sessionmaker() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
    username = f"@{message.from_user.username}" if message.from_user.username else "-"
    first_name = message.from_user.first_name or "-"
    header = _(
        "support_admin_header",
        telegram_id=message.from_user.id,
        username=username,
        first_name=first_name,
    )
    for admin_id in settings.admin_telegram_ids:
        try:
            await bot.send_message(
                admin_id,
                header,
                reply_markup=support_reply_keyboard(user.id if user else message.from_user.id, _),
            )
            await bot.copy_message(admin_id, message.chat.id, message.message_id)
        except Exception:
            continue
    await state.clear()
    await message.answer(_("support_sent"), reply_markup=main_menu(_))


@router.callback_query(SupportReplyCb.filter())
async def ask_support_reply(
    callback: CallbackQuery,
    callback_data: SupportReplyCb,
    state: FSMContext,
    settings: Settings,
    sessionmaker: async_sessionmaker,
    _,
) -> None:
    if callback.from_user.id not in set(settings.admin_telegram_ids):
        await callback.answer(_("access_denied"), show_alert=True)
        return
    async with sessionmaker() as session:
        user = await session.get(User, callback_data.user_id)
    if not user:
        await callback.answer(_("user_not_found"), show_alert=True)
        return
    await state.update_data(support_user_id=user.id, support_telegram_id=user.telegram_id)
    await state.set_state(AdminSupportStates.reply)
    await callback.message.answer(_("support_reply_prompt"))  # type: ignore[union-attr]
    await callback.answer()


@router.message(AdminSupportStates.reply)
async def send_support_reply(
    message: Message,
    state: FSMContext,
    settings: Settings,
    sessionmaker: async_sessionmaker,
    bot,
    i18n,
    _,
) -> None:
    assert message.from_user
    if message.from_user.id not in set(settings.admin_telegram_ids):
        await state.clear()
        return
    data = await state.get_data()
    user_id = int(data["support_user_id"])
    telegram_id = int(data["support_telegram_id"])
    async with sessionmaker.begin() as session:
        user = await session.get(User, user_id)
        if not user:
            await message.answer(_("user_not_found"))
            await state.clear()
            return
        try:
            await bot.send_message(telegram_id, i18n.t("support_reply_intro", user.language))
            await bot.copy_message(telegram_id, message.chat.id, message.message_id)
        except Exception:
            await message.answer(_("support_reply_failed"))
            return
        await log_admin_action(
            session,
            message.from_user.id,
            "support_reply",
            details=f"user_id={user_id}; telegram_id={telegram_id}",
        )
    await state.clear()
    await message.answer(_("support_reply_sent"), reply_markup=admin_dashboard(_))
