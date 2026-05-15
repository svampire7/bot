from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import CopyTextButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class LangCb(CallbackData, prefix="lang"):
    code: str


class PackageCb(CallbackData, prefix="pkg"):
    gb: int


def language_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="فارسی", callback_data=LangCb(code="fa"))
    builder.button(text="English", callback_data=LangCb(code="en"))
    return builder.as_markup()


def main_menu(_) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=_("buy_vpn"), callback_data="menu:buy")
    builder.button(text=_("my_service"), callback_data="menu:service")
    builder.button(text=_("my_orders"), callback_data="menu:orders")
    builder.button(text=_("renew"), callback_data="menu:renew")
    builder.button(text=_("help"), callback_data="menu:help")
    builder.button(text=_("change_language"), callback_data="menu:lang")
    builder.adjust(2, 2, 2)
    return builder.as_markup()


def packages_keyboard(_) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for gb in (10, 20, 50, 100):
        builder.button(text=f"{gb}GB", callback_data=PackageCb(gb=gb))
    builder.button(text=_("custom_gb"), callback_data="pkg:custom")
    builder.button(text=_("back"), callback_data="menu:main")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def back_to_menu_keyboard(_) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=_("back_to_menu"), callback_data="menu:main")
    return builder.as_markup()


def payment_keyboard(_, card_number: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if card_number:
        builder.button(text=_("copy_card_number"), copy_text=CopyTextButton(text=card_number))
    builder.button(text=_("back_to_menu"), callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def service_copy_keyboard(_, subscription_url: str | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if subscription_url:
        builder.button(
            text=_("copy_subscription_link"),
            copy_text=CopyTextButton(text=subscription_url),
        )
    builder.button(text=_("back_to_menu"), callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()
