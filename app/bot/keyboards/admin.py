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


class SupportReplyCb(CallbackData, prefix="suprep"):
    user_id: int


class PackageAdminCb(CallbackData, prefix="admpkg"):
    action: str
    gb: int = 0


class DiscountAdminCb(CallbackData, prefix="admdisc"):
    action: str
    code: str = "-"


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
        (_("user_area"), "admin:user_area"),
    ]:
        builder.button(text=text, callback_data=data)
    builder.adjust(2, 2, 2, 2, 2, 2)
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


def order_recovery_keyboard(order_id: int, _) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=_("retry_order"), callback_data=AdminOrderCb(action="retry", order_id=order_id))
    builder.button(text=_("mark_completed"), callback_data=AdminOrderCb(action="complete", order_id=order_id))
    builder.button(text=_("reject"), callback_data=AdminOrderCb(action="reject", order_id=order_id))
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
    builder.button(text=_("change_packages"), callback_data="admin:set:package_prices_toman")
    builder.button(text=_("package_editor"), callback_data="admin:packages")
    builder.button(text=_("discount_codes"), callback_data="admin:discounts")
    builder.button(text=_("change_card"), callback_data="admin:set:card_number")
    builder.button(text=_("change_card_holder"), callback_data="admin:set:card_holder_name")
    builder.button(text=_("change_bank"), callback_data="admin:set:bank_name")
    builder.button(text=_("change_crypto_wallet"), callback_data="admin:set:crypto_ltc_wallet")
    builder.button(text=_("change_crypto_qr"), callback_data="admin:setqr:crypto_ltc_qr_file_id")
    builder.button(text=_("change_usdt_rate"), callback_data="admin:set:ltc_toman_rate")
    builder.button(text=_("change_support"), callback_data="admin:set:support_username")
    builder.button(text=_("back"), callback_data="admin:dashboard")
    builder.adjust(2, 2, 2, 2, 2, 2, 1, 1)
    return builder.as_markup()


def support_reply_keyboard(user_id: int, _) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=_("reply_to_support"), callback_data=SupportReplyCb(user_id=user_id))
    builder.button(text=_("back"), callback_data="admin:dashboard")
    builder.adjust(1)
    return builder.as_markup()


def package_editor_keyboard(packages: list[tuple[int, int]], _) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for gb, _price in packages:
        builder.button(text=_("edit_package_button", gb=gb), callback_data=PackageAdminCb(action="edit", gb=gb))
        builder.button(text=_("remove_package_button", gb=gb), callback_data=PackageAdminCb(action="remove", gb=gb))
    builder.button(text=_("add_package"), callback_data=PackageAdminCb(action="add", gb=0))
    builder.button(text=_("back"), callback_data="admin:settings")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def discount_codes_keyboard(codes: list[str], _) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code in codes:
        builder.button(text=_("disable_discount_button", code=code), callback_data=DiscountAdminCb(action="toggle", code=code))
    builder.button(text=_("add_discount"), callback_data=DiscountAdminCb(action="add", code="-"))
    builder.button(text=_("back"), callback_data="admin:settings")
    builder.adjust(1)
    return builder.as_markup()
