from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import CopyTextButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class LangCb(CallbackData, prefix="lang"):
    code: str


class PackageCb(CallbackData, prefix="pkg"):
    gb: int


class OrderCb(CallbackData, prefix="ord"):
    action: str
    order_id: int


def language_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="فارسی", callback_data=LangCb(code="fa"))
    builder.button(text="English", callback_data=LangCb(code="en"))
    return builder.as_markup()


def main_menu(_) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=_("buy_vpn"), callback_data="menu:buy")
    builder.button(text=_("my_service"), callback_data="menu:service")
    builder.button(text=_("wallet"), callback_data="menu:wallet")
    builder.button(text=_("my_orders"), callback_data="menu:orders")
    builder.button(text=_("renew"), callback_data="menu:renew")
    builder.button(text=_("support"), callback_data="menu:support")
    builder.button(text=_("help"), callback_data="menu:help")
    builder.button(text=_("change_language"), callback_data="menu:lang")
    builder.adjust(2, 2, 2, 2)
    return builder.as_markup()


def packages_keyboard(_, packages: list[tuple[int, int]]) -> InlineKeyboardMarkup:
    from app.utils.formatters import toman

    builder = InlineKeyboardBuilder()
    for gb, price in packages:
        builder.button(text=f"{gb}GB - {toman(price)}", callback_data=PackageCb(gb=gb))
    builder.button(text=_("custom_gb"), callback_data="pkg:custom")
    builder.button(text=_("back"), callback_data="menu:main")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def back_to_menu_keyboard(_) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=_("back_to_menu"), callback_data="menu:main")
    return builder.as_markup()


def payment_keyboard(_, card_number: str, allow_discount: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if card_number:
        builder.button(text=_("copy_card_number"), copy_text=CopyTextButton(text=card_number))
    if allow_discount:
        builder.button(text=_("apply_discount"), callback_data="pay:discount")
    builder.button(text=_("back_to_menu"), callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def payment_method_keyboard(_, allow_discount: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=_("pay_card"), callback_data="pay:card")
    builder.button(text=_("pay_crypto"), callback_data="pay:crypto")
    if allow_discount:
        builder.button(text=_("apply_discount"), callback_data="pay:discount")
    builder.button(text=_("back_to_menu"), callback_data="menu:main")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def wallet_purchase_keyboard(_, allow_discount: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=_("pay_from_wallet"), callback_data="pay:wallet")
    builder.button(text=_("topup_wallet"), callback_data="menu:wallet")
    if allow_discount:
        builder.button(text=_("apply_discount"), callback_data="pay:discount")
    builder.button(text=_("back_to_menu"), callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


def wallet_keyboard(_) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=_("topup_card"), callback_data="wallet:topup:card")
    builder.button(text=_("topup_ltc"), callback_data="wallet:topup:ltc")
    builder.button(text=_("back_to_menu"), callback_data="menu:main")
    builder.adjust(2, 1)
    return builder.as_markup()


def wallet_card_keyboard(_, card_number: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if card_number:
        builder.button(text=_("copy_card_number"), copy_text=CopyTextButton(text=card_number))
    builder.button(text=_("back"), callback_data="menu:wallet")
    builder.adjust(1)
    return builder.as_markup()


def wallet_crypto_keyboard(_, wallet: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if wallet:
        builder.button(text=_("copy_crypto_wallet"), copy_text=CopyTextButton(text=wallet))
    builder.button(text=_("back"), callback_data="menu:wallet")
    builder.adjust(1)
    return builder.as_markup()


def crypto_payment_keyboard(_, wallet: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if wallet:
        builder.button(text=_("copy_crypto_wallet"), copy_text=CopyTextButton(text=wallet))
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


def orders_keyboard(order_ids: list[int], _) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order_id in order_ids:
        builder.button(text=_("view_order_button", order_id=order_id), callback_data=OrderCb(action="view", order_id=order_id))
    builder.button(text=_("back_to_menu"), callback_data="menu:main")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def order_detail_keyboard(order_id: int, status: str, _) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if status in {"rejected", "failed"}:
        builder.button(text=_("contact_support"), callback_data="menu:support")
    builder.button(text=_("back"), callback_data="menu:orders")
    builder.button(text=_("back_to_menu"), callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()
