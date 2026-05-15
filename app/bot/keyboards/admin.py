from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class AdminOrderCb(CallbackData, prefix="admord"):
    action: str
    order_id: int


class AdminUserCb(CallbackData, prefix="admuser"):
    action: str
    user_id: int


def admin_dashboard(_) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for text, data in [
        (_("pending_orders"), "admin:pending"),
        (_("search_user"), "admin:search"),
        (_("order_history"), "admin:orders"),
        (_("active_services"), "admin:services"),
        (_("add_traffic"), "admin:addtraffic"),
        (_("disable_user"), "admin:disable"),
        (_("enable_user"), "admin:enable"),
        (_("delete_user"), "admin:delete"),
        (_("broadcast"), "admin:broadcast"),
        (_("bot_settings"), "admin:settings"),
        (_("stats"), "admin:stats"),
    ]:
        builder.button(text=text, callback_data=data)
    builder.adjust(2, 2, 2, 2, 2, 1)
    return builder.as_markup()


def pending_order_keyboard(order_id: int, _) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=_("approve"), callback_data=AdminOrderCb(action="approve", order_id=order_id))
    builder.button(text=_("reject"), callback_data=AdminOrderCb(action="reject", order_id=order_id))
    builder.button(
        text=_("ask_new_receipt"), callback_data=AdminOrderCb(action="new_receipt", order_id=order_id)
    )
    builder.button(text=_("view_user"), callback_data=AdminOrderCb(action="view_user", order_id=order_id))
    builder.button(text=_("back"), callback_data="admin:dashboard")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def user_actions(user_id: int, _) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for action, label in [
        ("addtraffic", _("add_traffic")),
        ("disable", _("disable_user")),
        ("enable", _("enable_user")),
        ("delete", _("delete_user")),
        ("newservice", _("create_new_service")),
    ]:
        builder.button(text=label, callback_data=AdminUserCb(action=action, user_id=user_id))
    builder.button(text=_("back"), callback_data="admin:dashboard")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def confirm_broadcast(_) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=_("approve"), callback_data="admin:broadcast:confirm")
    builder.button(text=_("reject"), callback_data="admin:dashboard")
    return builder.as_markup()


def confirm_delete_keyboard(_) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=_("approve"), callback_data="admin:delete:confirm")
    builder.button(text=_("reject"), callback_data="admin:delete:cancel")
    return builder.as_markup()


def settings_keyboard(_) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=_("change_price"), callback_data="admin:set:price_per_gb_toman")
    builder.button(text=_("change_min_gb"), callback_data="admin:set:min_custom_gb")
    builder.button(text=_("change_max_gb"), callback_data="admin:set:max_custom_gb")
    builder.button(text=_("change_card"), callback_data="admin:set:card_number")
    builder.button(text=_("change_support"), callback_data="admin:set:support_username")
    builder.button(text=_("back"), callback_data="admin:dashboard")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()
