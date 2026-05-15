from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.keyboards.user import back_to_menu_keyboard
from app.db.repositories import active_service_for_user, get_user_by_telegram_id, user_order_history
from app.utils.formatters import optional_gb, toman

router = Router()


@router.callback_query(F.data == "menu:service")
async def my_service(callback: CallbackQuery, sessionmaker: async_sessionmaker, _) -> None:
    assert callback.from_user
    async with sessionmaker() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        service = await active_service_for_user(session, user.id) if user else None
        if not service:
            await callback.message.edit_text(  # type: ignore[union-attr]
                _("no_service"), reply_markup=back_to_menu_keyboard(_)
            )
        else:
            await callback.message.edit_text(  # type: ignore[union-attr]
                _("service_info",
                  username=service.marzban_username,
                  total_gb=service.data_limit_gb,
                  used=optional_gb(service.used_traffic_gb),
                  remaining=optional_gb(service.remaining_traffic_gb),
                  subscription_url=service.subscription_url or "-"),
                reply_markup=back_to_menu_keyboard(_),
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
            _("order_line",
              id=order.id,
              type=_("order_type_" + order.order_type),
              status=_("status_" + order.status),
              gb=order.gb_amount,
              price=toman(order.price_toman),
              date=order.created_at.strftime("%Y-%m-%d %H:%M"),
              marzban_username=order.marzban_username or "-")
        )
    await callback.message.edit_text(  # type: ignore[union-attr]
        _("orders_title") + "\n\n" + "\n\n".join(lines),
        reply_markup=back_to_menu_keyboard(_),
    )
    await callback.answer()
