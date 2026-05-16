from __future__ import annotations

import time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.keyboards.admin import (
    AdminOrderCb,
    AdminUserCb,
    DiscountAdminCb,
    PackageAdminCb,
    admin_dashboard,
    confirm_broadcast,
    confirm_delete_keyboard,
    discount_codes_keyboard,
    order_recovery_keyboard,
    package_editor_keyboard,
    pending_order_keyboard,
    settings_keyboard,
    user_actions,
)
from app.bot.keyboards.user import main_menu, service_copy_keyboard
from app.bot.middlewares.admin_auth import AdminFilter
from app.config import Settings
from app.db.models import DiscountCode, Order, OrderStatus, User, VPNService, VPNServiceStatus
from app.db.repositories import (
    active_service_for_user,
    get_discount_code,
    list_discount_codes,
    order_context,
    order_with_user_for_update,
    pending_orders,
    search_user,
    set_setting,
    stats,
    user_order_history,
)
from app.marzban.client import MarzbanClient
from app.services.admin_service import log_admin_action
from app.services.discount_service import parse_discount_definition
from app.services.payment_service import PaymentService, format_package_prices, parse_package_prices
from app.services.vpn_service import DuplicateApprovalError, VPNProvisioningService
from app.utils.formatters import html_code, html_code_lines, optional_gb, toman
from app.utils.validators import parse_positive_int, sanitize_username

router = Router()


class AdminStates(StatesGroup):
    search = State()
    broadcast = State()
    add_traffic_user = State()
    add_traffic_gb = State()
    service_username = State()
    create_new_gb = State()
    setting_value = State()
    package_value = State()
    discount_value = State()
    qr_value = State()


def register_admin_filter(settings: Settings) -> None:
    router.message.filter(AdminFilter(settings))
    router.callback_query.filter(lambda callback: callback.from_user.id in set(settings.admin_telegram_ids))


@router.message(Command("admin"))
async def admin_entry(message: Message, _) -> None:
    await message.answer(_("admin_dashboard"), reply_markup=admin_dashboard(_))


@router.callback_query(F.data == "admin:dashboard")
async def admin_home(callback: CallbackQuery, _) -> None:
    await callback.message.edit_text(_("admin_dashboard"), reply_markup=admin_dashboard(_))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "admin:user_area")
async def admin_user_area(callback: CallbackQuery, state: FSMContext, _) -> None:
    await state.clear()
    await callback.message.edit_text(_("main_menu"), reply_markup=main_menu(_))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "admin:pending")
async def show_pending(callback: CallbackQuery, sessionmaker: async_sessionmaker, _) -> None:
    async with sessionmaker() as session:
        orders = await pending_orders(session, limit=1)
        if not orders:
            await callback.message.edit_text(_("no_pending_orders"), reply_markup=admin_dashboard(_))  # type: ignore[union-attr]
        else:
            order = orders[0]
            context = await order_context(session, order)
            text = _("admin_order",
                     id=order.id,
                     type=_("order_type_" + order.order_type),
                     status=_("status_" + order.status),
                     username=order.user.telegram_username or "-",
                     telegram_id=order.user.telegram_id,
                     gb=order.gb_amount,
                     price=toman(order.price_toman),
                     original_price=toman(order.original_price_toman or order.price_toman),
                     discount=toman(order.discount_amount_toman or 0),
                     discount_code=order.discount_code or "-",
                     payment_method=_("payment_method_" + order.payment_method),
                     crypto_tx_hash=order.crypto_tx_hash or "-",
                     crypto_expected_usdt=order.crypto_expected_usdt or "-",
                     service=context["service"],
                     total_orders=context["total_orders"],
                     completed_orders=context["completed_orders"],
                     duplicate_pending=context["duplicate_pending"],
                     duplicate_receipts=context["duplicate_receipts"],
                     duplicate_crypto=context["duplicate_crypto"],
                     date=order.created_at.strftime("%Y-%m-%d %H:%M"))
            if order.receipt_file_id:
                try:
                    await callback.message.answer_photo(  # type: ignore[union-attr]
                        order.receipt_file_id,
                        caption=text,
                        reply_markup=pending_order_keyboard(order.id, _),
                    )
                except TelegramBadRequest:
                    await callback.message.answer_document(  # type: ignore[union-attr]
                        order.receipt_file_id,
                        caption=text,
                        reply_markup=pending_order_keyboard(order.id, _),
                    )
            else:
                await callback.message.edit_text(  # type: ignore[union-attr]
                    text, reply_markup=pending_order_keyboard(order.id, _)
                )
    await callback.answer()


@router.callback_query(AdminOrderCb.filter())
async def admin_order_action(
    callback: CallbackQuery,
    callback_data: AdminOrderCb,
    sessionmaker: async_sessionmaker,
    settings: Settings,
    bot,
    i18n,
    _,
) -> None:
    assert callback.from_user
    order_id = callback_data.order_id
    async with sessionmaker() as session:
        order = await order_with_user_for_update(session, order_id)
        if not order:
            await callback.answer(_("order_not_found"), show_alert=True)
            return
        user_lang = order.user.language
        if callback_data.action == "reject":
            if order.status not in {OrderStatus.pending_admin.value, OrderStatus.failed.value}:
                await callback.answer(_("order_not_pending"), show_alert=True)
                return
            order.status = OrderStatus.rejected.value
            await log_admin_action(session, callback.from_user.id, "reject_order", order_id)
            await session.commit()
            await bot.send_message(order.user.telegram_id, i18n.t("order_rejected", user_lang))
            try:
                await callback.message.edit_caption(caption=_("order_rejected_admin", order_id=order_id))  # type: ignore[union-attr]
            except TelegramBadRequest:
                await callback.message.edit_text(_("order_rejected_admin", order_id=order_id), reply_markup=admin_dashboard(_))  # type: ignore[union-attr]
            await callback.answer()
            return
        if callback_data.action == "new_receipt":
            await log_admin_action(session, callback.from_user.id, "ask_new_receipt", order_id)
            await session.commit()
            await bot.send_message(order.user.telegram_id, i18n.t("new_receipt_requested", user_lang))
            await callback.answer()
            return
        if callback_data.action == "view_user":
            await show_user_profile(callback, session, order.user_id, _)
            return
        if callback_data.action == "complete":
            if order.status == OrderStatus.completed.value:
                await callback.answer(_("order_not_pending"), show_alert=True)
                return
            service = await active_service_for_user(session, order.user_id)
            if not service:
                await callback.answer(_("no_active_service_for_completion"), show_alert=True)
                return
            order.status = OrderStatus.completed.value
            order.marzban_username = service.marzban_username
            if order.discount_code:
                discount = await get_discount_code(session, order.discount_code)
                if discount:
                    discount.used_count += 1
            await log_admin_action(session, callback.from_user.id, "mark_order_completed", order_id)
            await session.commit()
            await bot.send_message(order.user.telegram_id, i18n.t("order_marked_completed", user_lang))
            await callback.message.edit_text(_("order_completed_admin", order_id=order_id), reply_markup=admin_dashboard(_))  # type: ignore[union-attr]
            await callback.answer()
            return
        if callback_data.action == "retry":
            if order.status != OrderStatus.failed.value:
                await callback.answer(_("retry_only_failed"), show_alert=True)
                return
            order.status = OrderStatus.pending_admin.value
            order.admin_note = None
            await log_admin_action(session, callback.from_user.id, "retry_failed_order", order_id)
            await session.commit()
    if callback_data.action in {"approve", "retry"}:
        async with sessionmaker.begin() as session:
            try:
                service, _created, config_links = await VPNProvisioningService(
                    settings
                ).approve_order(session, order_id)
                order = await session.get(Order, order_id)
                assert order is not None
                await log_admin_action(session, callback.from_user.id, "approve_order", order_id)
                user = await session.get(User, order.user_id)
                assert user is not None
                text = i18n.t(
                    "service_ready",
                    user.language,
                    purchased_gb=order.gb_amount,
                    total_gb=service.data_limit_gb,
                    used=optional_gb(service.used_traffic_gb),
                    remaining=optional_gb(service.remaining_traffic_gb),
                    subscription_url=html_code(service.subscription_url or "-"),
                    config_links=html_code_lines(config_links) if config_links else i18n.t(
                        "configs_not_available", user.language
                    ),
                )
                telegram_id = user.telegram_id
                subscription_url = service.subscription_url
            except DuplicateApprovalError:
                await callback.answer(_("order_not_pending"), show_alert=True)
                return
            except Exception as exc:
                failed_order = await session.get(Order, order_id)
                if failed_order:
                    user = await session.get(User, failed_order.user_id)
                    await log_admin_action(
                        session, callback.from_user.id, "approve_order_failed", order_id, str(exc)
                    )
                    if user:
                        await bot.send_message(user.telegram_id, i18n.t("approval_failed", user.language))
                await callback.answer(_("action_failed", error=str(exc)), show_alert=True)
                return
        await bot.send_message(telegram_id, text, reply_markup=service_copy_keyboard(_, subscription_url))
        try:
            await callback.message.edit_caption(caption=_("order_completed_admin", order_id=order_id))  # type: ignore[union-attr]
        except TelegramBadRequest:
            await callback.message.edit_text(_("order_completed_admin", order_id=order_id), reply_markup=admin_dashboard(_))  # type: ignore[union-attr]
        await callback.answer()


async def show_user_profile(callback: CallbackQuery, session, user_id: int, _) -> None:
    user = await session.get(User, user_id)
    if not user:
        await callback.answer(_("user_not_found"), show_alert=True)
        return
    service = await active_service_for_user(session, user.id)
    total_gb = await session.scalar(
        select(func.coalesce(func.sum(Order.gb_amount), 0)).where(
            Order.user_id == user.id, Order.status == OrderStatus.completed.value
        )
    )
    service_label = service.marzban_username if service else "-"
    text = _("admin_user_info",
             user_id=user.id,
             telegram_id=user.telegram_id,
             username=user.telegram_username or "-",
             language=user.language,
             service=service_label,
             total_gb=int(total_gb or 0))
    await callback.message.answer(text, reply_markup=user_actions(user.id, _))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data.in_({"admin:search", "admin:orders"}))
async def ask_search(callback: CallbackQuery, state: FSMContext, _) -> None:
    await state.set_state(AdminStates.search)
    await callback.message.edit_text(_("enter_search_query"))  # type: ignore[union-attr]
    await callback.answer()


@router.message(AdminStates.search)
async def search_user_message(message: Message, state: FSMContext, sessionmaker: async_sessionmaker, _) -> None:
    query = (message.text or "").strip()
    async with sessionmaker() as session:
        if query.lower().startswith("order "):
            order_id = parse_positive_int(query.split(maxsplit=1)[1])
            order = await session.scalar(select(Order).where(Order.id == order_id)) if order_id else None
            if not order:
                await message.answer(_("order_not_found"))
                return
            context = await order_context(session, order)
            user = await session.get(User, order.user_id)
            text = _("admin_order",
                     id=order.id,
                     type=_("order_type_" + order.order_type),
                     status=_("status_" + order.status),
                     username=user.telegram_username if user else "-",
                     telegram_id=user.telegram_id if user else "-",
                     gb=order.gb_amount,
                     price=toman(order.price_toman),
                     original_price=toman(order.original_price_toman or order.price_toman),
                     discount=toman(order.discount_amount_toman or 0),
                     discount_code=order.discount_code or "-",
                     payment_method=_("payment_method_" + order.payment_method),
                     crypto_tx_hash=order.crypto_tx_hash or "-",
                     crypto_expected_usdt=order.crypto_expected_usdt or "-",
                     service=context["service"],
                     total_orders=context["total_orders"],
                     completed_orders=context["completed_orders"],
                     duplicate_pending=context["duplicate_pending"],
                     duplicate_receipts=context["duplicate_receipts"],
                     duplicate_crypto=context["duplicate_crypto"],
                     date=order.created_at.strftime("%Y-%m-%d %H:%M"))
            keyboard = (
                pending_order_keyboard(order.id, _)
                if order.status == OrderStatus.pending_admin.value
                else order_recovery_keyboard(order.id, _)
            )
            await message.answer(text, reply_markup=keyboard)
            await state.clear()
            return
        user = await search_user(session, query)
        if not user:
            await message.answer(_("user_not_found"))
            return
        service = await active_service_for_user(session, user.id)
        orders = await user_order_history(session, user.id)
        history = "\n".join(
            f"#{o.id} {o.status} {o.gb_amount}GB {toman(o.price_toman)}" for o in orders
        ) or "-"
        service_text = _("service_line",
                         username=service.marzban_username,
                         limit=service.data_limit_gb,
                         used=optional_gb(service.used_traffic_gb),
                         remaining=optional_gb(service.remaining_traffic_gb),
                         subscription_url=html_code(service.subscription_url or "-")) if service else "-"
        await message.answer(
            _("admin_search_result",
              telegram_id=user.telegram_id,
              username=user.telegram_username or "-",
              service=service_text,
              history=history),
            reply_markup=user_actions(user.id, _),
        )
    await state.clear()


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery, sessionmaker: async_sessionmaker, _) -> None:
    async with sessionmaker() as session:
        data = await stats(session)
    await callback.message.edit_text(_("stats_text", **data), reply_markup=admin_dashboard(_))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "admin:settings")
async def admin_settings(callback: CallbackQuery, settings: Settings, sessionmaker: async_sessionmaker, _) -> None:
    from app.services.payment_service import PaymentService

    payment = PaymentService(settings)
    async with sessionmaker() as session:
        text = _("settings_text",
                 price=await payment.price_per_gb(session),
                 packages=format_package_prices(await payment.package_prices(session)),
                 min_gb=await payment.min_custom_gb(session),
                 max_gb=await payment.max_custom_gb(session),
                 card=html_code(await payment.card_number(session)),
                 card_holder=html_code(await payment.card_holder_name(session)),
                 bank=html_code(await payment.bank_name(session)),
                 crypto_wallet=html_code(await payment.crypto_ltc_wallet(session)),
                 crypto_qr=_("configured") if await payment.crypto_ltc_qr_file_id(session) else "-",
                 ltc_rate=await payment.ltc_toman_rate(session),
                 support=html_code(await payment.support_username(session)))
    await callback.message.edit_text(text, reply_markup=settings_keyboard(_))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data.startswith("admin:set:"))
async def ask_setting_value(callback: CallbackQuery, state: FSMContext, _) -> None:
    key = (callback.data or "").split(":", 2)[-1]
    await state.update_data(setting_key=key)
    await state.set_state(AdminStates.setting_value)
    await callback.message.edit_text(_("enter_setting_value"))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data.startswith("admin:setqr:"))
async def ask_qr_value(callback: CallbackQuery, state: FSMContext, _) -> None:
    key = (callback.data or "").split(":", 2)[-1]
    await state.update_data(setting_key=key)
    await state.set_state(AdminStates.qr_value)
    await callback.message.edit_text(_("send_qr_image"))  # type: ignore[union-attr]
    await callback.answer()


@router.message(AdminStates.qr_value)
async def save_qr_value(
    message: Message, state: FSMContext, sessionmaker: async_sessionmaker, _
) -> None:
    assert message.from_user
    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        file_id = message.document.file_id
    elif (message.text or "").strip() == "-":
        file_id = ""
    if file_id is None:
        await message.answer(_("qr_image_required"))
        return
    data = await state.get_data()
    key = data["setting_key"]
    async with sessionmaker.begin() as session:
        await set_setting(session, key, file_id)
        await log_admin_action(session, message.from_user.id, "update_bot_setting", details=f"{key}=***")
    await state.clear()
    await message.answer(_("setting_saved"), reply_markup=admin_dashboard(_))


@router.message(AdminStates.setting_value)
async def save_setting_value(
    message: Message, state: FSMContext, sessionmaker: async_sessionmaker, _
) -> None:
    assert message.from_user
    data = await state.get_data()
    key = data["setting_key"]
    value = (message.text or "").strip()
    numeric_keys = {"price_per_gb_toman", "min_custom_gb", "max_custom_gb", "ltc_toman_rate"}
    if key in numeric_keys and (parse_positive_int(value) is None):
        await message.answer(_("invalid_value"))
        return
    if key == "package_prices_toman":
        try:
            value = format_package_prices(parse_package_prices(value))
        except ValueError:
            await message.answer(_("invalid_package_prices"))
            return
    async with sessionmaker.begin() as session:
        await set_setting(session, key, value)
        await log_admin_action(session, message.from_user.id, "update_bot_setting", details=f"{key}=***")
    await state.clear()
    await message.answer(_("setting_saved"), reply_markup=admin_dashboard(_))


@router.callback_query(F.data == "admin:packages")
async def admin_package_editor(callback: CallbackQuery, settings: Settings, sessionmaker: async_sessionmaker, _) -> None:
    async with sessionmaker() as session:
        packages = await PaymentService(settings).package_prices(session)
    lines = [f"{gb}GB = {toman(price)}" for gb, price in packages]
    await callback.message.edit_text(  # type: ignore[union-attr]
        _("package_editor_text", packages="\n".join(lines)),
        reply_markup=package_editor_keyboard(packages, _),
    )
    await callback.answer()


@router.callback_query(PackageAdminCb.filter())
async def package_editor_action(
    callback: CallbackQuery,
    callback_data: PackageAdminCb,
    state: FSMContext,
    settings: Settings,
    sessionmaker: async_sessionmaker,
    _,
) -> None:
    if callback_data.action == "remove":
        async with sessionmaker.begin() as session:
            payment = PaymentService(settings)
            packages = await payment.package_prices(session)
            packages = [(gb, price) for gb, price in packages if gb != callback_data.gb]
            if not packages:
                await callback.answer(_("cannot_remove_last_package"), show_alert=True)
                return
            await set_setting(session, "package_prices_toman", format_package_prices(packages))
            await log_admin_action(session, callback.from_user.id, "remove_package", details=str(callback_data.gb))  # type: ignore[union-attr]
        await callback.message.edit_text(_("setting_saved"), reply_markup=admin_dashboard(_))  # type: ignore[union-attr]
        await callback.answer()
        return
    await state.update_data(package_action=callback_data.action, package_gb=callback_data.gb)
    await state.set_state(AdminStates.package_value)
    prompt = _("enter_package_price", gb=callback_data.gb) if callback_data.action == "edit" else _("enter_package_definition")
    await callback.message.edit_text(prompt)  # type: ignore[union-attr]
    await callback.answer()


@router.message(AdminStates.package_value)
async def save_package_value(
    message: Message, state: FSMContext, settings: Settings, sessionmaker: async_sessionmaker, _
) -> None:
    assert message.from_user
    data = await state.get_data()
    action = data["package_action"]
    async with sessionmaker.begin() as session:
        packages = dict(await PaymentService(settings).package_prices(session))
        try:
            if action == "edit":
                gb = int(data["package_gb"])
                price = parse_positive_int(message.text or "")
                if not price:
                    raise ValueError
                packages[gb] = price
            else:
                raw_gb, raw_price = (message.text or "").replace(":", " ").split()[:2]
                gb = parse_positive_int(raw_gb)
                price = parse_positive_int(raw_price)
                if not gb or not price:
                    raise ValueError
                packages[gb] = price
        except Exception:
            await message.answer(_("invalid_package_value"))
            return
        value = format_package_prices(sorted(packages.items()))
        await set_setting(session, "package_prices_toman", value)
        await log_admin_action(session, message.from_user.id, "update_package", details=value)
    await state.clear()
    await message.answer(_("setting_saved"), reply_markup=admin_dashboard(_))


@router.callback_query(F.data == "admin:discounts")
async def admin_discounts(callback: CallbackQuery, sessionmaker: async_sessionmaker, _) -> None:
    async with sessionmaker() as session:
        discounts = await list_discount_codes(session, limit=10)
    lines = [
        _("discount_line",
          code=d.code,
          percent=d.percent,
          amount=toman(d.amount_toman),
          used=d.used_count,
          max_uses=d.max_uses or "-",
          status=_("enabled") if d.is_active else _("disabled"))
        for d in discounts
    ]
    await callback.message.edit_text(  # type: ignore[union-attr]
        _("discounts_text", discounts="\n".join(lines) or "-"),
        reply_markup=discount_codes_keyboard([d.code for d in discounts], _),
    )
    await callback.answer()


@router.callback_query(DiscountAdminCb.filter())
async def discount_action(
    callback: CallbackQuery,
    callback_data: DiscountAdminCb,
    state: FSMContext,
    sessionmaker: async_sessionmaker,
    _,
) -> None:
    if callback_data.action == "toggle":
        async with sessionmaker.begin() as session:
            discount = await session.scalar(select(DiscountCode).where(DiscountCode.code == callback_data.code))
            if discount:
                discount.is_active = not discount.is_active
                await log_admin_action(session, callback.from_user.id, "toggle_discount", details=discount.code)  # type: ignore[union-attr]
        await callback.message.edit_text(_("setting_saved"), reply_markup=admin_dashboard(_))  # type: ignore[union-attr]
        await callback.answer()
        return
    await state.set_state(AdminStates.discount_value)
    await callback.message.edit_text(_("enter_discount_definition"))  # type: ignore[union-attr]
    await callback.answer()


@router.message(AdminStates.discount_value)
async def save_discount(message: Message, state: FSMContext, sessionmaker: async_sessionmaker, _) -> None:
    assert message.from_user
    try:
        code, percent, amount, max_uses = parse_discount_definition(message.text or "")
    except Exception:
        await message.answer(_("invalid_discount_definition"))
        return
    async with sessionmaker.begin() as session:
        discount = await session.scalar(select(DiscountCode).where(DiscountCode.code == code))
        if not discount:
            discount = DiscountCode(code=code)
            session.add(discount)
        discount.percent = percent
        discount.amount_toman = amount
        discount.max_uses = max_uses
        discount.is_active = True
        await log_admin_action(session, message.from_user.id, "save_discount", details=code)
    await state.clear()
    await message.answer(_("setting_saved"), reply_markup=admin_dashboard(_))


@router.callback_query(F.data == "admin:services")
async def active_services(callback: CallbackQuery, sessionmaker: async_sessionmaker, _) -> None:
    async with sessionmaker() as session:
        services = list(
            await session.scalars(
                select(VPNService)
                .where(VPNService.status == VPNServiceStatus.active.value)
                .order_by(VPNService.id.desc())
                .limit(10)
            )
        )
    text = "\n".join(f"{s.marzban_username} | {s.data_limit_gb}GB" for s in services) or "-"
    await callback.message.edit_text(f"{_('active_services')}\n\n{text}", reply_markup=admin_dashboard(_))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "admin:broadcast")
async def ask_broadcast(callback: CallbackQuery, state: FSMContext, _) -> None:
    await state.set_state(AdminStates.broadcast)
    await callback.message.edit_text(_("enter_broadcast"))  # type: ignore[union-attr]
    await callback.answer()


@router.message(AdminStates.broadcast)
async def broadcast_text(message: Message, state: FSMContext, _) -> None:
    await state.update_data(text=message.text or "")
    await message.answer(_("confirm_broadcast", text=message.text or ""), reply_markup=confirm_broadcast(_))


@router.callback_query(F.data == "admin:broadcast:confirm")
async def broadcast_confirm(
    callback: CallbackQuery, state: FSMContext, sessionmaker: async_sessionmaker, bot, _
) -> None:
    assert callback.from_user
    data = await state.get_data()
    text = data.get("text", "")
    ok = fail = 0
    async with sessionmaker() as session:
        users = list(await session.scalars(select(User).where(User.is_blocked.is_(False))))
        for user in users:
            try:
                await bot.send_message(user.telegram_id, text)
                ok += 1
            except Exception:
                fail += 1
        await log_admin_action(session, callback.from_user.id, "broadcast", details=text[:1000])
        await session.commit()
    await state.clear()
    await callback.message.edit_text(_("broadcast_done", ok=ok, fail=fail), reply_markup=admin_dashboard(_))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data.in_({"admin:addtraffic", "admin:disable", "admin:enable", "admin:delete"}))
async def ask_service_username(callback: CallbackQuery, state: FSMContext, _) -> None:
    action = (callback.data or "").split(":")[-1]
    await state.update_data(service_action=action)
    await state.set_state(AdminStates.service_username)
    await callback.message.edit_text(_("enter_marzban_username"))  # type: ignore[union-attr]
    await callback.answer()


@router.message(AdminStates.service_username)
async def service_username_step(
    message: Message, state: FSMContext, sessionmaker: async_sessionmaker, settings: Settings, _
) -> None:
    data = await state.get_data()
    username = (message.text or "").strip()
    action = data.get("service_action")
    if action == "addtraffic":
        await state.update_data(marzban_username=username)
        await state.set_state(AdminStates.add_traffic_gb)
        await message.answer(_("enter_gb_amount"))
        return
    if action == "delete":
        await state.update_data(marzban_username=username)
        await message.answer(
            _("confirm_delete_vpn", username=username),
            reply_markup=confirm_delete_keyboard(_),
        )
        return
    async with sessionmaker.begin() as session:
        service = await session.scalar(select(VPNService).where(VPNService.marzban_username == username))
        async with MarzbanClient(settings) as marzban:
            if action == "disable":
                await marzban.disable_user(username)
                if service:
                    service.status = VPNServiceStatus.disabled.value
            elif action == "enable":
                await marzban.enable_user(username)
                if service:
                    service.status = VPNServiceStatus.active.value
        await log_admin_action(session, message.from_user.id, f"{action}_vpn_user", details=username)  # type: ignore[union-attr]
    await state.clear()
    await message.answer(_("done"), reply_markup=admin_dashboard(_))


@router.callback_query(F.data.in_({"admin:delete:confirm", "admin:delete:cancel"}))
async def confirm_delete_service(
    callback: CallbackQuery, state: FSMContext, sessionmaker: async_sessionmaker, settings: Settings, _
) -> None:
    assert callback.from_user
    data = await state.get_data()
    username = (data.get("marzban_username") or "").strip()
    if callback.data == "admin:delete:cancel":
        await state.clear()
        await callback.message.edit_text(_("delete_cancelled"), reply_markup=admin_dashboard(_))  # type: ignore[union-attr]
        await callback.answer()
        return
    async with sessionmaker.begin() as session:
        service = await session.scalar(select(VPNService).where(VPNService.marzban_username == username))
        async with MarzbanClient(settings) as marzban:
            deleted_remote = await marzban.delete_user(username)
        if service:
            service.status = VPNServiceStatus.deleted.value
        await log_admin_action(
            session,
            callback.from_user.id,
            "delete_vpn_user",
            details=f"{username}; remote_deleted={deleted_remote}",
        )
    await state.clear()
    text = _("done") if deleted_remote else _("delete_remote_missing")
    await callback.message.edit_text(text, reply_markup=admin_dashboard(_))  # type: ignore[union-attr]
    await callback.answer()


@router.message(AdminStates.add_traffic_gb)
async def add_traffic_gb(
    message: Message, state: FSMContext, sessionmaker: async_sessionmaker, settings: Settings, _
) -> None:
    gb = parse_positive_int(message.text or "")
    if not gb:
        await message.answer(_("invalid_value"))
        return
    data = await state.get_data()
    username = data["marzban_username"]
    async with sessionmaker.begin() as session:
        service = await session.scalar(select(VPNService).where(VPNService.marzban_username == username))
        async with MarzbanClient(settings) as marzban:
            await marzban.add_traffic_to_user(username, gb)
        if service:
            service.data_limit_gb += gb
            service.status = VPNServiceStatus.active.value
        await log_admin_action(session, message.from_user.id, "manual_add_traffic", details=f"{username}:{gb}")  # type: ignore[union-attr]
    await state.clear()
    await message.answer(_("traffic_added"), reply_markup=admin_dashboard(_))


@router.callback_query(AdminUserCb.filter())
async def user_action_button(
    callback: CallbackQuery, callback_data: AdminUserCb, state: FSMContext, sessionmaker: async_sessionmaker, _
) -> None:
    async with sessionmaker() as session:
        user = await session.get(User, callback_data.user_id)
        service = await active_service_for_user(session, callback_data.user_id) if user else None
    if not user:
        await callback.answer(_("user_not_found"), show_alert=True)
        return
    if callback_data.action == "addtraffic":
        await state.update_data(service_action="addtraffic", marzban_username=service.marzban_username if service else "")
        await state.set_state(AdminStates.add_traffic_gb)
        await callback.message.answer(_("enter_gb_amount"))  # type: ignore[union-attr]
    elif callback_data.action == "newservice":
        await state.update_data(create_new_user_id=callback_data.user_id)
        await state.set_state(AdminStates.create_new_gb)
        await callback.message.answer(_("enter_new_service_gb"))  # type: ignore[union-attr]
    else:
        await state.update_data(service_action=callback_data.action)
        await state.set_state(AdminStates.service_username)
        await callback.message.answer(_("enter_marzban_username"))  # type: ignore[union-attr]
    await callback.answer()


@router.message(AdminStates.create_new_gb)
async def create_new_service_gb(
    message: Message, state: FSMContext, sessionmaker: async_sessionmaker, settings: Settings, _
) -> None:
    assert message.from_user
    gb = parse_positive_int(message.text or "")
    if not gb:
        await message.answer(_("invalid_value"))
        return
    data = await state.get_data()
    user_id = int(data["create_new_user_id"])
    async with sessionmaker.begin() as session:
        user = await session.get(User, user_id)
        if not user:
            await message.answer(_("user_not_found"))
            return
        old_service = await active_service_for_user(session, user_id)
        if old_service:
            old_service.status = VPNServiceStatus.disabled.value
        username = sanitize_username(f"tg_{user.telegram_id}_manual_{int(time.time())}")
        async with MarzbanClient(settings) as marzban:
            if old_service:
                await marzban.disable_user(old_service.marzban_username)
            created = await marzban.create_user(username, gb)
            service = VPNService(
                user_id=user.id,
                marzban_username=username,
                subscription_url=marzban.get_subscription_url(username, created),
                data_limit_gb=gb,
                status=VPNServiceStatus.active.value,
            )
            session.add(service)
        await log_admin_action(
            session, message.from_user.id, "manual_create_new_service", details=f"{username}:{gb}"
        )
    await state.clear()
    await message.answer(_("new_service_created"), reply_markup=admin_dashboard(_))
