from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.keyboards.user import LangCb, language_keyboard, main_menu
from app.db.repositories import get_user_by_telegram_id

router = Router()


@router.callback_query(LangCb.filter())
async def set_language(
    callback: CallbackQuery, callback_data: LangCb, sessionmaker: async_sessionmaker, i18n
) -> None:
    assert callback.from_user
    async with sessionmaker() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if user:
            user.language = callback_data.code
        await session.commit()
    t = lambda key, **kwargs: i18n.t(key, callback_data.code, **kwargs)
    await callback.message.edit_text(t("language_saved"), reply_markup=main_menu(t))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(lambda c: c.data == "menu:lang")
async def change_language(callback: CallbackQuery, _) -> None:
    await callback.message.edit_text(_("start"), reply_markup=language_keyboard())  # type: ignore[union-attr]
    await callback.answer()

