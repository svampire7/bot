from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.keyboards.user import back_to_menu_keyboard

router = Router()


@router.callback_query(F.data == "menu:help")
async def help_menu(callback: CallbackQuery, _) -> None:
    await callback.message.edit_text(_("help_text"), reply_markup=back_to_menu_keyboard(_))  # type: ignore[union-attr]
    await callback.answer()
