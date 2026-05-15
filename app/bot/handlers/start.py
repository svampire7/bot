from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.keyboards.user import language_keyboard, main_menu
from app.config import Settings
from app.db.repositories import get_or_create_user

router = Router()


@router.message(CommandStart())
async def start(message: Message, sessionmaker: async_sessionmaker, settings: Settings, _) -> None:
    assert message.from_user
    async with sessionmaker() as session:
        await get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            settings.default_language,
        )
        await session.commit()
    await message.answer(_("start"), reply_markup=language_keyboard())


@router.message(Command("menu"))
async def menu(message: Message, sessionmaker: async_sessionmaker, settings: Settings, _) -> None:
    assert message.from_user
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
async def show_main_menu(callback: CallbackQuery, _) -> None:
    await callback.message.edit_text(_("main_menu"), reply_markup=main_menu(_))  # type: ignore[union-attr]
    await callback.answer()
