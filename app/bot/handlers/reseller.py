from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.keyboards.user import back_to_menu_keyboard, reseller_invoice_keyboard, reseller_menu_keyboard
from app.config import Settings
from app.db.models import ResellerBulkOrder, ResellerBulkOrderStatus
from app.services.bulk_order_service import (
    create_reseller_bulk_order,
    parse_reseller_bulk_request,
    reseller_orders,
)
from app.services.bulk_service import BulkPlanError
from app.services.invoice_service import bulk_invoice_text, bulk_summary_lines
from app.services.payment_service import PaymentService
from app.services.reseller_service import is_active_reseller
from app.utils.formatters import html_code, toman

router = Router()


class ResellerStates(StatesGroup):
    bulk_request = State()
    payment_proof = State()


async def _authorized(callback: CallbackQuery, sessionmaker: async_sessionmaker, _) -> bool:
    assert callback.from_user
    async with sessionmaker() as session:
        allowed = await is_active_reseller(session, callback.from_user.id)
    if not allowed:
        await callback.answer(_("reseller_unauthorized"), show_alert=True)
    return allowed


@router.callback_query(F.data == "menu:reseller")
async def reseller_panel(callback: CallbackQuery, state: FSMContext, sessionmaker: async_sessionmaker, _) -> None:
    if not await _authorized(callback, sessionmaker, _):
        return
    await state.clear()
    await callback.message.edit_text(_("reseller_panel_title"), reply_markup=reseller_menu_keyboard(_))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "reseller:help")
async def reseller_help(callback: CallbackQuery, sessionmaker: async_sessionmaker, _) -> None:
    if not await _authorized(callback, sessionmaker, _):
        return
    await callback.message.edit_text(_("reseller_help_text"), reply_markup=reseller_menu_keyboard(_))  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "reseller:create")
async def ask_bulk_order(callback: CallbackQuery, state: FSMContext, sessionmaker: async_sessionmaker, _) -> None:
    if not await _authorized(callback, sessionmaker, _):
        return
    await state.set_state(ResellerStates.bulk_request)
    await callback.message.edit_text(_("reseller_bulk_format_prompt"), reply_markup=back_to_menu_keyboard(_))  # type: ignore[union-attr]
    await callback.answer()


@router.message(ResellerStates.bulk_request)
async def reseller_bulk_request(
    message: Message,
    state: FSMContext,
    sessionmaker: async_sessionmaker,
    settings: Settings,
    _,
) -> None:
    assert message.from_user
    async with sessionmaker() as session:
        if not await is_active_reseller(session, message.from_user.id):
            await message.answer(_("reseller_unauthorized"))
            await state.clear()
            return
        try:
            plan = await parse_reseller_bulk_request(session, settings, message.text or "")
        except (BulkPlanError, ValueError) as exc:
            await message.answer(_("reseller_bulk_invalid", error=str(exc)), reply_markup=back_to_menu_keyboard(_))
            return
        order = await create_reseller_bulk_order(session, message.from_user.id, message.text or "", plan)
        payment = PaymentService(settings)
        card_number = await payment.card_number(session)
        card_holder = await payment.card_holder_name(session)
        bank = await payment.bank_name(session)
        await session.commit()
    await state.update_data(reseller_bulk_order_id=order.id)
    await state.set_state(ResellerStates.payment_proof)
    summary = "\n".join(bulk_summary_lines(plan.items))
    await message.answer(
        _(
            "reseller_invoice",
            invoice=bulk_invoice_text(order.order_code, message.from_user.id, plan.items, plan.total_price),
            summary=summary,
            order_code=order.order_code,
            total_accounts=plan.total_accounts,
            total_gb=plan.total_gb,
            price=toman(plan.total_price),
            card_number=html_code(card_number),
            card_holder=card_holder or "-",
            bank=bank or "-",
        ),
        reply_markup=reseller_invoice_keyboard(_),
    )


@router.callback_query(F.data == "reseller:paid", ResellerStates.payment_proof)
async def reseller_paid(callback: CallbackQuery, _) -> None:
    await callback.answer(_("reseller_send_payment_proof"), show_alert=True)


@router.message(ResellerStates.payment_proof)
async def reseller_payment_proof(
    message: Message,
    state: FSMContext,
    sessionmaker: async_sessionmaker,
    settings: Settings,
    bot,
    _,
) -> None:
    assert message.from_user
    receipt_file_id = None
    if message.photo:
        receipt_file_id = message.photo[-1].file_id
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        receipt_file_id = message.document.file_id
    if not receipt_file_id:
        await message.answer(_("receipt_required"))
        return
    data = await state.get_data()
    order_id = int(data["reseller_bulk_order_id"])
    async with sessionmaker.begin() as session:
        order = await session.get(ResellerBulkOrder, order_id)
        if not order:
            await message.answer(_("order_not_found"))
            await state.clear()
            return
        order.payment_proof_file_id = receipt_file_id
        order.status = ResellerBulkOrderStatus.pending_admin.value
    admin_text = _(
        "reseller_admin_order",
        order_code=order.order_code,
        telegram_id=order.reseller_telegram_id,
        raw=order.raw_request_text,
        total_accounts=order.total_accounts,
        total_gb=order.total_gb,
        price=toman(order.total_price),
        status=order.status,
    )
    from app.bot.keyboards.admin import reseller_bulk_order_keyboard

    for admin_id in settings.admin_telegram_ids:
        try:
            await bot.send_photo(admin_id, receipt_file_id, caption=admin_text, reply_markup=reseller_bulk_order_keyboard(order.id, _))
        except Exception:
            await bot.send_message(admin_id, admin_text, reply_markup=reseller_bulk_order_keyboard(order.id, _))
    await state.clear()
    await message.answer(_("reseller_order_submitted", order_code=order.order_code), reply_markup=reseller_menu_keyboard(_))


@router.callback_query(F.data == "reseller:orders")
async def my_bulk_orders(callback: CallbackQuery, sessionmaker: async_sessionmaker, _) -> None:
    if not await _authorized(callback, sessionmaker, _):
        return
    async with sessionmaker() as session:
        orders = await reseller_orders(session, callback.from_user.id)  # type: ignore[union-attr]
    if not orders:
        await callback.message.edit_text(_("reseller_no_orders"), reply_markup=reseller_menu_keyboard(_))  # type: ignore[union-attr]
    else:
        lines = [
            _("reseller_order_line", code=o.order_code, status=o.status, accounts=o.total_accounts, gb=o.total_gb, price=toman(o.total_price))
            for o in orders
        ]
        await callback.message.edit_text(_("reseller_my_orders_title") + "\n\n" + "\n".join(lines), reply_markup=reseller_menu_keyboard(_))  # type: ignore[union-attr]
    await callback.answer()
