from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BufferedInputFile
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

from app.bot.middlewares.i18n import I18n
from app.config import get_settings
from app.db.models import (
    Order,
    OrderStatus,
    ResellerBulkOrderStatus,
    SupportTicket,
    User,
    VPNService,
    VPNServiceStatus,
    WalletTransactionStatus,
    WalletTransactionType,
)
from app.db.repositories import (
    active_service_for_user,
    add_support_message,
    advanced_stats,
    order_with_user_for_update,
    pending_order_count,
    pending_orders,
    pending_wallet_topup_count,
    pending_wallet_topups,
    referral_stats,
    search_user,
    set_setting,
    support_ticket_by_id,
    support_ticket_count,
    support_ticket_messages,
    support_tickets,
    user_count,
    user_order_history,
    users_with_referral_overview,
    wallet_balance,
    wallet_history,
    wallet_transaction_for_update,
    wallet_user_count,
)
from app.db.session import SessionLocal, engine
from app.marzban.client import MarzbanClient
from app.services.admin_service import log_admin_action
from app.services.admin_settings_service import AdminSettingValidationError, normalize_admin_setting_value
from app.services.bulk_order_service import (
    generate_reseller_accounts,
    generated_reseller_txt,
    recent_reseller_bulk_orders,
    reseller_bulk_order_with_accounts,
)
from app.services.broadcast_service import load_broadcast_recipients, send_broadcast
from app.services.payment_service import PaymentService, format_package_prices
from app.services.referral_service import notify_referrer_about_reward
from app.services.reseller_service import add_reseller, list_resellers, set_reseller_active
from app.services.wallet_service import WalletService
from app.services.vpn_service import DuplicateApprovalError, VPNProvisioningService
from app.utils.formatters import html_code, html_code_lines, optional_gb, toman
from app.utils.validators import parse_positive_int, parse_toman_amount, sanitize_username


settings = get_settings()
templates = Jinja2Templates(directory="app/web/templates")
i18n = I18n(Path("app/bot/i18n"), settings.default_language)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    yield
    await app.state.bot.session.close()
    await engine.dispose()


app = FastAPI(title="VPN Bot Admin", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.web_admin_session_secret,
    same_site="lax",
    https_only=False,
    max_age=60 * 60 * 12,
)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")


templates.env.filters["toman"] = toman
templates.env.filters["gb"] = optional_gb


def request_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    real_ip = request.headers.get("x-real-ip", "")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else ""


@app.middleware("http")
async def restrict_web_admin_ip(request: Request, call_next):
    allowed_ips = settings.web_admin_allowed_ips
    if allowed_ips and request_ip(request) not in allowed_ips:
        return PlainTextResponse("Access denied", status_code=403)
    return await call_next(request)


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def with_message(path: str, message: str, level: str = "ok") -> RedirectResponse:
    separator = "&" if "?" in path else "?"
    return redirect(f"{path}{separator}msg={quote(message)}&level={quote(level)}")


async def session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as db:
        yield db


def admin_id() -> int:
    return settings.web_admin_log_telegram_id


async def require_admin(request: Request) -> str:
    if not settings.web_admin_enabled:
        raise HTTPException(status_code=404)
    user = request.session.get("web_admin_user")
    if not user:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return str(user)


def context(request: Request, title: str, **kwargs: object) -> dict[str, object]:
    return {
        "request": request,
        "title": title,
        "msg": request.query_params.get("msg"),
        "level": request.query_params.get("level", "ok"),
        **kwargs,
    }


def render(request: Request, template: str, title: str, **kwargs: object) -> HTMLResponse:
    return templates.TemplateResponse(request, template, context(request, title, **kwargs))


def row_url(path: str, offset: int, limit: int = 20) -> str:
    return f"{path}?offset={max(0, offset)}&limit={limit}"


async def notify_order_completed(
    bot: Bot,
    db: AsyncSession,
    order: Order,
    service: VPNService,
    config_links: list[str],
    referral_reward,
) -> None:
    user = await db.get(User, order.user_id)
    if not user:
        return
    text = i18n.t(
        "service_ready",
        user.language,
        purchased_gb=order.gb_amount,
        total_gb=optional_gb(service.data_limit_gb),
        used=optional_gb(service.used_traffic_gb),
        remaining=optional_gb(service.remaining_traffic_gb),
        subscription_url=html_code(service.subscription_url or "-"),
        config_links=html_code_lines(config_links)
        if config_links
        else i18n.t("configs_not_available", user.language),
    )
    if referral_reward.referred_bonus_gb:
        text += "\n\n" + i18n.t(
            "referral_friend_bonus_applied",
            user.language,
            bonus_gb=referral_reward.referred_bonus_gb,
        )
    if referral_reward.pending_bonus_gb:
        text += "\n" + i18n.t(
            "referral_pending_bonus_applied",
            user.language,
            bonus_gb=referral_reward.pending_bonus_gb,
        )
    await bot.send_message(user.telegram_id, text)
    await notify_referrer_about_reward(bot, i18n, referral_reward)


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    return render(request, "login.html", "Login")


@app.post("/login")
async def login(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> RedirectResponse:
    valid_user = secrets.compare_digest(username, settings.web_admin_username)
    valid_password = bool(settings.web_admin_password) and secrets.compare_digest(
        password,
        settings.web_admin_password,
    )
    if not (valid_user and valid_password):
        return with_message("/login", "Invalid username or password", "bad")
    request.session["web_admin_user"] = username
    return redirect("/")


@app.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return redirect("/login")


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    _: Annotated[str, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(session)],
) -> HTMLResponse:
    data = await advanced_stats(db)
    data["pending_wallet_topups"] = await pending_wallet_topup_count(db)
    data["wallet_users"] = await wallet_user_count(db)
    data["support_tickets"] = await support_ticket_count(db)
    return render(request, "dashboard.html", "Dashboard", stats=data)


@app.get("/orders", response_class=HTMLResponse)
async def orders_page(
    request: Request,
    _: Annotated[str, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(session)],
    offset: int = 0,
    limit: int = 20,
) -> HTMLResponse:
    total = await pending_order_count(db)
    rows = await pending_orders(db, limit=limit, offset=offset)
    return render(
        request,
        "orders.html",
        "Pending Orders",
        rows=rows,
        total=total,
        offset=offset,
        limit=limit,
        prev_url=row_url("/orders", offset - limit, limit) if offset > 0 else None,
        next_url=row_url("/orders", offset + limit, limit) if offset + limit < total else None,
    )


@app.post("/orders/{order_id}/approve")
async def approve_order(
    request: Request,
    order_id: int,
    _: Annotated[str, Depends(require_admin)],
) -> RedirectResponse:
    bot: Bot = request.app.state.bot
    async with SessionLocal.begin() as db:
        try:
            service, _created, config_links, referral_reward = await VPNProvisioningService(
                settings
            ).approve_order(db, order_id)
            order = await db.get(Order, order_id)
            if not order:
                return with_message("/orders", "Order not found", "bad")
            await log_admin_action(db, admin_id(), "web_approve_order", order_id)
            await notify_order_completed(bot, db, order, service, config_links, referral_reward)
        except DuplicateApprovalError:
            return with_message("/orders", "Order is not pending", "bad")
        except Exception as exc:
            failed_order = await db.get(Order, order_id)
            if failed_order:
                user = await db.get(User, failed_order.user_id)
                await log_admin_action(db, admin_id(), "web_approve_order_failed", order_id, str(exc))
                if user:
                    await bot.send_message(user.telegram_id, i18n.t("approval_failed", user.language))
            return with_message("/orders", f"Activation failed: {str(exc)[:140]}", "bad")
    return with_message("/orders", f"Order #{order_id} completed")


@app.post("/orders/{order_id}/reject")
async def reject_order(
    request: Request,
    order_id: int,
    _: Annotated[str, Depends(require_admin)],
    reason: Annotated[str, Form()] = "Rejected by admin",
) -> RedirectResponse:
    bot: Bot = request.app.state.bot
    async with SessionLocal.begin() as db:
        order = await order_with_user_for_update(db, order_id)
        if not order:
            return with_message("/orders", "Order not found", "bad")
        if order.status not in {OrderStatus.pending_admin.value, OrderStatus.failed.value}:
            return with_message("/orders", "Order is already processed", "bad")
        order.status = OrderStatus.rejected.value
        order.admin_note = reason[:1000]
        await log_admin_action(db, admin_id(), "web_reject_order", order_id, reason[:900])
        await bot.send_message(
            order.user.telegram_id,
            i18n.t("order_rejected_reason", order.user.language, reason=reason[:500]),
        )
    return with_message("/orders", f"Order #{order_id} rejected")


@app.get("/wallet/topups", response_class=HTMLResponse)
async def wallet_topups_page(
    request: Request,
    _: Annotated[str, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(session)],
    offset: int = 0,
    limit: int = 20,
) -> HTMLResponse:
    total = await pending_wallet_topup_count(db)
    rows = await pending_wallet_topups(db, limit=limit, offset=offset)
    return render(
        request,
        "wallet_topups.html",
        "Wallet Top-ups",
        rows=rows,
        total=total,
        offset=offset,
        limit=limit,
        prev_url=row_url("/wallet/topups", offset - limit, limit) if offset > 0 else None,
        next_url=row_url("/wallet/topups", offset + limit, limit) if offset + limit < total else None,
    )


@app.post("/wallet/topups/{tx_id}/approve")
async def approve_wallet_topup(
    request: Request,
    tx_id: int,
    _: Annotated[str, Depends(require_admin)],
) -> RedirectResponse:
    bot: Bot = request.app.state.bot
    async with SessionLocal.begin() as db:
        tx = await wallet_transaction_for_update(db, tx_id)
        if not tx:
            return with_message("/wallet/topups", "Transaction not found", "bad")
        if tx.status != WalletTransactionStatus.pending_admin.value:
            return with_message("/wallet/topups", "Transaction is already processed", "bad")
        tx.status = WalletTransactionStatus.completed.value
        await log_admin_action(db, admin_id(), "web_approve_wallet_topup", details=f"{tx.id}:{tx.amount_toman}")
        await bot.send_message(
            tx.user.telegram_id,
            i18n.t("wallet_topup_approved", tx.user.language, amount=toman(tx.amount_toman)),
        )
    return with_message("/wallet/topups", f"Wallet top-up #{tx_id} approved")


@app.post("/wallet/topups/{tx_id}/reject")
async def reject_wallet_topup(
    request: Request,
    tx_id: int,
    _: Annotated[str, Depends(require_admin)],
) -> RedirectResponse:
    bot: Bot = request.app.state.bot
    async with SessionLocal.begin() as db:
        tx = await wallet_transaction_for_update(db, tx_id)
        if not tx:
            return with_message("/wallet/topups", "Transaction not found", "bad")
        if tx.status != WalletTransactionStatus.pending_admin.value:
            return with_message("/wallet/topups", "Transaction is already processed", "bad")
        tx.status = WalletTransactionStatus.rejected.value
        await log_admin_action(db, admin_id(), "web_reject_wallet_topup", details=f"{tx.id}:{tx.amount_toman}")
        await bot.send_message(tx.user.telegram_id, i18n.t("wallet_topup_rejected", tx.user.language))
    return with_message("/wallet/topups", f"Wallet top-up #{tx_id} rejected")


@app.post("/wallet/topups/{tx_id}/edit")
async def edit_wallet_topup(
    tx_id: int,
    _: Annotated[str, Depends(require_admin)],
    amount: Annotated[str, Form()],
) -> RedirectResponse:
    new_amount = parse_toman_amount(amount)
    if not new_amount:
        return with_message("/wallet/topups", "Invalid amount", "bad")
    async with SessionLocal.begin() as db:
        tx = await wallet_transaction_for_update(db, tx_id)
        if not tx:
            return with_message("/wallet/topups", "Transaction not found", "bad")
        if tx.transaction_type not in {
            WalletTransactionType.topup_card.value,
            WalletTransactionType.topup_ltc.value,
        }:
            return with_message("/wallet/topups", "Transaction is not editable", "bad")
        old_amount = tx.amount_toman
        if tx.status == WalletTransactionStatus.pending_admin.value:
            tx.amount_toman = new_amount
            tx.admin_note = f"amount corrected from {old_amount} to {new_amount}"
        elif tx.status == WalletTransactionStatus.completed.value:
            delta = new_amount - old_amount
            if delta:
                await WalletService().adjustment(
                    db,
                    tx.user_id,
                    delta,
                    f"correction for wallet top-up #{tx.id}: {old_amount} -> {new_amount}",
                )
        else:
            return with_message("/wallet/topups", "Transaction is not editable", "bad")
        await log_admin_action(db, admin_id(), "web_edit_wallet_topup_amount", details=f"{tx.id}:{old_amount}->{new_amount}")
    return with_message("/wallet/topups", f"Wallet top-up #{tx_id} corrected")


@app.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    _: Annotated[str, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(session)],
    q: str = "",
    offset: int = 0,
    limit: int = 20,
) -> HTMLResponse:
    if q.strip():
        user = await search_user(db, q.strip())
        rows = [(user, 0, 0)] if user else []
        total = len(rows)
    else:
        rows = await users_with_referral_overview(db, limit=limit, offset=offset)
        total = await user_count(db)
    balances = {user.id: await wallet_balance(db, user.id) for user, _, _ in rows if user}
    services = {user.id: await active_service_for_user(db, user.id) for user, _, _ in rows if user}
    return render(
        request,
        "users.html",
        "Users",
        rows=rows,
        balances=balances,
        services=services,
        q=q,
        total=total,
        offset=offset,
        limit=limit,
        prev_url=row_url("/users", offset - limit, limit) if not q and offset > 0 else None,
        next_url=row_url("/users", offset + limit, limit) if not q and offset + limit < total else None,
    )


@app.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail_page(
    request: Request,
    user_id: int,
    _: Annotated[str, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(session)],
) -> HTMLResponse:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404)
    service = await active_service_for_user(db, user.id)
    balance = await wallet_balance(db, user.id)
    txs = await wallet_history(db, user.id, limit=20)
    orders = await user_order_history(db, user.id, limit=20)
    referrer = await db.get(User, user.referred_by_user_id) if user.referred_by_user_id else None
    refs = await referral_stats(db, user.id)
    return render(
        request,
        "user_detail.html",
        "User Detail",
        user=user,
        service=service,
        balance=balance,
        txs=txs,
        orders=orders,
        referrer=referrer,
        refs=refs,
    )


@app.post("/users/{user_id}/wallet-adjust")
async def user_wallet_adjust(
    user_id: int,
    _: Annotated[str, Depends(require_admin)],
    amount: Annotated[str, Form()],
    note: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        parsed = int(amount.strip().replace(",", ""))
    except ValueError:
        return with_message(f"/users/{user_id}", "Invalid amount", "bad")
    if parsed == 0:
        return with_message(f"/users/{user_id}", "Amount cannot be zero", "bad")
    async with SessionLocal.begin() as db:
        if not await db.get(User, user_id):
            return with_message("/users", "User not found", "bad")
        await WalletService().adjustment(db, user_id, parsed, note[:500])
        await log_admin_action(db, admin_id(), "web_wallet_adjustment", details=f"{user_id}:{parsed}:{note[:400]}")
    return with_message(f"/users/{user_id}", "Wallet adjustment saved")


@app.post("/users/{user_id}/service/add-traffic")
async def user_service_add_traffic(
    user_id: int,
    _: Annotated[str, Depends(require_admin)],
    gb: Annotated[str, Form()],
) -> RedirectResponse:
    amount = parse_positive_int(gb)
    if not amount:
        return with_message(f"/users/{user_id}", "Invalid GB amount", "bad")
    async with SessionLocal.begin() as db:
        service = await active_service_for_user(db, user_id)
        if not service:
            return with_message(f"/users/{user_id}", "User has no active service", "bad")
        async with MarzbanClient(settings) as marzban:
            await marzban.add_traffic_to_user(service.marzban_username, amount)
        service.data_limit_gb += amount
        service.low_traffic_alert_sent = False
        service.traffic_depleted_alert_sent = False
        service.status = VPNServiceStatus.active.value
        await log_admin_action(db, admin_id(), "web_manual_add_traffic", details=f"{service.marzban_username}:{amount}")
    return with_message(f"/users/{user_id}", "Traffic added")


@app.post("/users/{user_id}/service/{action}")
async def user_service_action(
    user_id: int,
    action: str,
    _: Annotated[str, Depends(require_admin)],
) -> RedirectResponse:
    if action not in {"disable", "enable", "delete"}:
        raise HTTPException(status_code=404)
    async with SessionLocal.begin() as db:
        service = await active_service_for_user(db, user_id)
        if not service:
            return with_message(f"/users/{user_id}", "User has no active service", "bad")
        async with MarzbanClient(settings) as marzban:
            if action == "disable":
                await marzban.disable_user(service.marzban_username)
                service.status = VPNServiceStatus.disabled.value
            elif action == "enable":
                await marzban.enable_user(service.marzban_username)
                service.status = VPNServiceStatus.active.value
            else:
                await marzban.delete_user(service.marzban_username)
                service.status = VPNServiceStatus.deleted.value
        await log_admin_action(db, admin_id(), f"web_{action}_vpn_user", details=service.marzban_username)
    return with_message(f"/users/{user_id}", f"Service {action} done")


@app.post("/users/{user_id}/service/new")
async def user_create_new_service(
    user_id: int,
    _: Annotated[str, Depends(require_admin)],
    gb: Annotated[str, Form()],
) -> RedirectResponse:
    amount = parse_positive_int(gb)
    if not amount:
        return with_message(f"/users/{user_id}", "Invalid GB amount", "bad")
    async with SessionLocal.begin() as db:
        user = await db.get(User, user_id)
        if not user:
            return with_message("/users", "User not found", "bad")
        old_service = await active_service_for_user(db, user.id)
        username = sanitize_username(f"tg_{user.telegram_id}_manual_web")
        async with MarzbanClient(settings) as marzban:
            if old_service:
                await marzban.disable_user(old_service.marzban_username)
                old_service.status = VPNServiceStatus.disabled.value
            existing = await marzban.get_user(username)
            if existing:
                username = sanitize_username(f"{username}_{user.id}")
            created = await marzban.create_user(username, amount)
            service = VPNService(
                user_id=user.id,
                marzban_username=username,
                subscription_url=marzban.get_subscription_url(username, created),
                data_limit_gb=amount,
                status=VPNServiceStatus.active.value,
            )
            db.add(service)
        await log_admin_action(db, admin_id(), "web_manual_create_new_service", details=f"{username}:{amount}")
    return with_message(f"/users/{user_id}", "New service created")


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    _: Annotated[str, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(session)],
) -> HTMLResponse:
    payment = PaymentService(settings)
    values = {
        "price_per_gb_toman": await payment.price_per_gb(db),
        "package_prices_toman": format_package_prices(await payment.package_prices(db)),
        "min_custom_gb": await payment.min_custom_gb(db),
        "max_custom_gb": await payment.max_custom_gb(db),
        "trial_enabled": "1" if await payment.trial_enabled(db) else "0",
        "card_reference_required": "1" if await payment.card_reference_required(db) else "0",
        "card_number": await payment.card_number(db),
        "card_holder_name": await payment.card_holder_name(db),
        "bank_name": await payment.bank_name(db),
        "support_username": await payment.support_username(db),
        "crypto_ltc_wallet": await payment.crypto_ltc_wallet(db),
        "ltc_toman_rate": await payment.ltc_toman_rate(db),
        "crypto_ltc_bonus_percent": await payment.crypto_ltc_bonus_percent(db),
        "referral_bonus_gb": await payment.referral_bonus_gb(db),
        "price_per_gb_reseller": await payment.reseller_price_per_gb(db),
        "min_reseller_bulk_gb": await payment.min_reseller_bulk_gb(db),
    }
    return render(request, "settings.html", "Settings", values=values)


@app.post("/settings")
async def save_settings(
    request: Request,
    _: Annotated[str, Depends(require_admin)],
) -> RedirectResponse:
    form = await request.form()
    async with SessionLocal.begin() as db:
        for key, value in form.items():
            if key.startswith("_"):
                continue
            try:
                normalized = normalize_admin_setting_value(key, str(value))
            except AdminSettingValidationError as exc:
                return with_message("/settings", f"{key}: {exc}", "bad")
            await set_setting(db, key, normalized)
            await log_admin_action(db, admin_id(), "web_update_bot_setting", details=f"{key}=***")
    return with_message("/settings", "Settings saved")


@app.get("/resellers", response_class=HTMLResponse)
async def resellers_page(
    request: Request,
    _: Annotated[str, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(session)],
) -> HTMLResponse:
    rows = await list_resellers(db, limit=100)
    return render(request, "resellers.html", "Resellers", rows=rows)


@app.post("/resellers")
async def save_reseller(
    _: Annotated[str, Depends(require_admin)],
    telegram_id: Annotated[str, Form()],
    name: Annotated[str, Form()] = "",
) -> RedirectResponse:
    parsed = parse_positive_int(telegram_id)
    if not parsed:
        return with_message("/resellers", "Invalid Telegram ID", "bad")
    async with SessionLocal.begin() as db:
        await add_reseller(db, parsed, name.strip() or None)
        await log_admin_action(db, admin_id(), "web_add_reseller", details=f"{parsed}:{name[:200]}")
    return with_message("/resellers", "Reseller saved")


@app.post("/resellers/{telegram_id}/{action}")
async def reseller_action(
    telegram_id: int,
    action: str,
    _: Annotated[str, Depends(require_admin)],
) -> RedirectResponse:
    if action not in {"enable", "disable", "remove"}:
        raise HTTPException(status_code=404)
    async with SessionLocal.begin() as db:
        ok = await set_reseller_active(db, telegram_id, action == "enable")
        if ok:
            await log_admin_action(db, admin_id(), f"web_reseller_{action}", details=str(telegram_id))
    return with_message("/resellers", "Reseller updated" if ok else "Reseller not found", "ok" if ok else "bad")


@app.get("/reseller-orders", response_class=HTMLResponse)
async def reseller_orders_page(
    request: Request,
    _: Annotated[str, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(session)],
) -> HTMLResponse:
    rows = await recent_reseller_bulk_orders(db, limit=50)
    return render(request, "reseller_orders.html", "Reseller Bulk Orders", rows=rows)


@app.post("/reseller-orders/{order_id}/{action}")
async def reseller_order_action(
    request: Request,
    order_id: int,
    action: str,
    _: Annotated[str, Depends(require_admin)],
) -> RedirectResponse:
    bot: Bot = request.app.state.bot
    async with SessionLocal.begin() as db:
        order = await reseller_bulk_order_with_accounts(db, order_id)
        if not order:
            return with_message("/reseller-orders", "Order not found", "bad")
        if action == "reject":
            order.status = ResellerBulkOrderStatus.rejected.value
            order.rejected_reason = "Rejected from web admin"
            await log_admin_action(db, admin_id(), "web_reject_reseller_bulk_order", details=order.order_code)
            await bot.send_message(order.reseller_telegram_id, i18n.t("reseller_order_rejected", "fa", order_code=order.order_code))
            return with_message("/reseller-orders", f"{order.order_code} rejected")
        if action in {"approve", "retry"}:
            ok, result = await generate_reseller_accounts(db, settings, order, admin_id())
            await log_admin_action(db, admin_id(), "web_approve_reseller_bulk_order", details=f"{order.order_code}:{ok}")
            if not ok:
                return with_message("/reseller-orders", f"Generation failed: {result[:140]}", "bad")
            txt = result
        elif action == "resend":
            successful = [account for account in order.accounts if not account.error_message]
            if not successful:
                return with_message("/reseller-orders", "No generated accounts found", "bad")
            txt = generated_reseller_txt(order, successful)
        else:
            raise HTTPException(status_code=404)
        await bot.send_document(
            order.reseller_telegram_id,
            BufferedInputFile(txt.encode("utf-8"), filename=f"{order.order_code}.txt"),
        )
    return with_message("/reseller-orders", f"{order.order_code} file sent")


@app.get("/support", response_class=HTMLResponse)
async def support_page(
    request: Request,
    _: Annotated[str, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(session)],
    ticket_id: int | None = None,
    offset: int = 0,
) -> HTMLResponse:
    total = await support_ticket_count(db)
    tickets = await support_tickets(db, limit=20, offset=offset)
    selected: SupportTicket | None = None
    messages = []
    if ticket_id:
        selected = await support_ticket_by_id(db, ticket_id)
        if selected:
            messages = await support_ticket_messages(db, selected.id, limit=30)
    return render(
        request,
        "support.html",
        "Support",
        tickets=tickets,
        total=total,
        selected=selected,
        messages=messages,
        offset=offset,
    )


@app.post("/support/{ticket_id}/reply")
async def support_reply(
    request: Request,
    ticket_id: int,
    _: Annotated[str, Depends(require_admin)],
    text: Annotated[str, Form()],
) -> RedirectResponse:
    if not text.strip():
        return with_message(f"/support?ticket_id={ticket_id}", "Reply cannot be empty", "bad")
    bot: Bot = request.app.state.bot
    async with SessionLocal.begin() as db:
        ticket = await support_ticket_by_id(db, ticket_id)
        if not ticket:
            return with_message("/support", "Ticket not found", "bad")
        await bot.send_message(ticket.user.telegram_id, i18n.t("support_reply_intro", ticket.user.language))
        await bot.send_message(ticket.user.telegram_id, text.strip())
        await add_support_message(db, ticket, "admin", admin_id(), "message", None, text.strip())
        await log_admin_action(db, admin_id(), "web_support_reply", details=f"ticket_id={ticket_id}")
    return with_message(f"/support?ticket_id={ticket_id}", "Reply sent")


@app.get("/broadcast", response_class=HTMLResponse)
async def broadcast_page(
    request: Request,
    _: Annotated[str, Depends(require_admin)],
) -> HTMLResponse:
    return render(request, "broadcast.html", "Broadcast")


@app.post("/broadcast")
async def broadcast_send(
    request: Request,
    _: Annotated[str, Depends(require_admin)],
    segment: Annotated[str, Form()],
    text: Annotated[str, Form()],
) -> RedirectResponse:
    if not text.strip():
        return with_message("/broadcast", "Message cannot be empty", "bad")
    bot: Bot = request.app.state.bot
    async with SessionLocal() as db:
        recipients = await load_broadcast_recipients(db, segment)
        await log_admin_action(db, admin_id(), "web_broadcast_started", details=f"{segment}: {text[:900]}")
        await db.commit()
    ok, fail = await send_broadcast(
        bot,
        recipients,
        text.strip(),
        batch_size=settings.broadcast_batch_size,
        batch_delay_seconds=settings.broadcast_batch_delay_seconds,
    )
    async with SessionLocal.begin() as db:
        await log_admin_action(db, admin_id(), "web_broadcast_done", details=f"{segment}: ok={ok}; fail={fail}")
    return with_message("/broadcast", f"Broadcast sent. OK={ok}, failed={fail}")


@app.get("/services", response_class=HTMLResponse)
async def services_page(
    request: Request,
    _: Annotated[str, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(session)],
) -> HTMLResponse:
    rows = list(
        await db.scalars(
            select(VPNService)
            .where(VPNService.status == VPNServiceStatus.active.value)
            .order_by(VPNService.id.desc())
            .limit(100)
        )
    )
    return render(request, "services.html", "Active Services", rows=rows)
