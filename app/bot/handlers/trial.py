from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.keyboards.user import trial_join_keyboard, trial_ready_keyboard
from app.config import Settings
from app.db.repositories import get_or_create_user
from app.services.trial_service import (
    ActiveServiceExistsError,
    TrialAlreadyUsedError,
    TrialService,
)
from app.utils.formatters import html_code, html_code_lines, optional_gb

router = Router()


def _channel_chat_id(settings: Settings) -> str:
    username = settings.trial_required_channel_username.strip()
    if username:
        return username if username.startswith("@") else f"@{username}"
    return settings.trial_required_channel_url.rstrip("/").rsplit("/", 1)[-1]


async def _is_required_channel_member(bot, telegram_id: int, settings: Settings) -> bool:
    member = await bot.get_chat_member(_channel_chat_id(settings), telegram_id)
    return member.status in {
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.MEMBER,
    }


@router.callback_query(F.data == "menu:trial")
async def trial_menu(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    bot,
    sessionmaker: async_sessionmaker,
    _,
) -> None:
    assert callback.from_user
    await state.clear()
    try:
        is_member = await _is_required_channel_member(bot, callback.from_user.id, settings)
    except (TelegramBadRequest, TelegramForbiddenError):
        await callback.message.edit_text(  # type: ignore[union-attr]
            _("trial_channel_check_failed"),
            reply_markup=trial_join_keyboard(_, settings.trial_required_channel_url),
        )
        await callback.answer()
        return
    if not is_member:
        await callback.message.edit_text(  # type: ignore[union-attr]
            _("trial_join_required", channel=settings.trial_required_channel_url),
            reply_markup=trial_join_keyboard(_, settings.trial_required_channel_url),
        )
        await callback.answer()
        return
    await activate_trial(callback, settings, bot, sessionmaker, _)


@router.callback_query(F.data == "trial:activate")
async def activate_trial(
    callback: CallbackQuery,
    settings: Settings,
    bot,
    sessionmaker: async_sessionmaker,
    _,
) -> None:
    assert callback.from_user
    try:
        is_member = await _is_required_channel_member(bot, callback.from_user.id, settings)
    except (TelegramBadRequest, TelegramForbiddenError):
        await callback.answer(_("trial_channel_check_failed"), show_alert=True)
        return
    if not is_member:
        await callback.answer(_("trial_not_joined"), show_alert=True)
        return
    async with sessionmaker.begin() as session:
        user = await get_or_create_user(
            session,
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name,
            settings.default_language,
        )
        try:
            result = await TrialService(settings).activate_trial(session, user.id)
        except TrialAlreadyUsedError:
            await callback.answer(_("trial_already_used"), show_alert=True)
            return
        except ActiveServiceExistsError:
            await callback.answer(_("trial_active_service_exists"), show_alert=True)
            return
    text = _(
        "trial_ready",
        traffic_mb=settings.trial_traffic_mb,
        hours=settings.trial_duration_hours,
        username=result.service.marzban_username,
        total=optional_gb(result.service.data_limit_gb),
        remaining=optional_gb(result.service.remaining_traffic_gb),
        expire_at=result.service.trial_expire_at.strftime("%Y-%m-%d %H:%M") if result.service.trial_expire_at else "-",
        subscription_url=html_code(result.service.subscription_url or "-"),
        config_links=html_code_lines(result.config_links) if result.config_links else _("configs_not_available"),
    )
    await callback.message.edit_text(  # type: ignore[union-attr]
        text,
        reply_markup=trial_ready_keyboard(_, result.service.subscription_url),
    )
    await callback.answer()
