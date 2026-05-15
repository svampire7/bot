from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.keyboards.user import (
    OrderCb,
    back_to_menu_keyboard,
    order_detail_keyboard,
    orders_keyboard,
    service_copy_keyboard,
)
from app.config import Settings
from app.db.repositories import (
    active_service_for_user,
    get_user_by_telegram_id,
    order_for_user,
    user_order_history,
)
from app.services.vpn_service import VPNProvisioningService
from app.utils.formatters import html_code, optional_gb, toman

router = Router()


@router.callback_query(F.data == "menu:service")
async def my_service(callback: CallbackQuery, sessionmaker: async_sessionmaker, settings: Settings, _) -> None:
    assert callback.from_user
    async with sessionmaker() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        service = await active_service_for_user(session, user.id) if user else None
        if not service:
            await callback.message.edit_text(  # type: ignore[union-attr]
                _("no_service"), reply_markup=back_to_menu_keyboard(_)
            )
        else:
            try:
                service = await VPNProvisioningService(settings).sync_service_usage(service)
                await session.commit()
            except Exception:
                await session.rollback()
            await callback.message.edit_text(  # type: ignore[union-attr]
                _("service_info",
                  username=service.marzban_username,
                  total_gb=service.data_limit_gb,
                  used=optional_gb(service.used_traffic_gb),
                  remaining=optional_gb(service.remaining_traffic_gb),
                  subscription_url=html_code(service.subscription_url or "-")),
                reply_markup=service_copy_keyboard(_, service.subscription_url),
            )
    await callback.answer()


@router.callback_query(F.data == "menu:orders")
async def my_orders(callback: CallbackQuery, sessionmaker: async_sessionmaker, _) -> None:
    assert callback.from_user
    async with sessionmaker() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        orders = await user_order_history(session, user.id, limit=10) if user else []
    if not orders:
        await callback.message.edit_text(_("no_orders"), reply_markup=back_to_menu_keyboard(_))  # type: ignore[union-attr]
        await callback.answer()
        return
    lines = []
    for order in orders:
        lines.append(
            _("order_summary_line",
              id=order.id,
              type=_("order_type_" + order.order_type),
              status=_("status_" + order.status),
              gb=order.gb_amount,
              price=toman(order.price_toman),
              date=order.created_at.strftime("%Y-%m-%d %H:%M"),
              marzban_username=order.marzban_username or "-")
        )
    await callback.message.edit_text(_("orders_title") + "\n\n" + "\n".join(lines), reply_markup=orders_keyboard([o.id for o in orders], _))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(OrderCb.filter())
async def order_detail(
    callback: CallbackQuery,
    callback_data: OrderCb,
    sessionmaker: async_sessionmaker,
    _,
) -> None:
    assert callback.from_user
    async with sessionmaker() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        order = await order_for_user(session, user.id, callback_data.order_id) if user else None
    if not order:
        await callback.answer(_("order_not_found"), show_alert=True)
        return
    text = _("order_detail",
             id=order.id,
             type=_("order_type_" + order.order_type),
             status=_("status_" + order.status),
             gb=order.gb_amount,
             price=toman(order.price_toman),
             original_price=toman(order.original_price_toman or order.price_toman),
             discount=toman(order.discount_amount_toman or 0),
             discount_code=order.discount_code or "-",
             payment_method=_("payment_method_" + order.payment_method),
             crypto_tx_hash=order.crypto_tx_hash or "-",
             crypto_expected_usdt=order.crypto_expected_usdt or "-",
             date=order.created_at.strftime("%Y-%m-%d %H:%M"),
             marzban_username=order.marzban_username or "-",
             note=order.admin_note or "-")
    await callback.message.edit_text(text, reply_markup=order_detail_keyboard(order.id, order.status, _))  # type: ignore[union-attr]
    await callback.answer()
