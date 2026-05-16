from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class OrderType(StrEnum):
    new = "new"
    renewal = "renewal"


class OrderStatus(StrEnum):
    pending_admin = "pending_admin"
    approved = "approved"
    rejected = "rejected"
    completed = "completed"
    failed = "failed"


class VPNServiceStatus(StrEnum):
    active = "active"
    disabled = "disabled"
    deleted = "deleted"
    failed = "failed"


class SupportTicketStatus(StrEnum):
    open = "open"
    answered = "answered"
    closed = "closed"


class WalletTransactionStatus(StrEnum):
    pending_admin = "pending_admin"
    completed = "completed"
    rejected = "rejected"
    failed = "failed"


class WalletTransactionType(StrEnum):
    topup_card = "topup_card"
    topup_ltc = "topup_ltc"
    purchase = "purchase"
    refund = "refund"
    adjustment = "adjustment"


class CryptoPaymentQuoteStatus(StrEnum):
    pending = "pending"
    completed = "completed"
    expired = "expired"
    failed = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(128), index=True)
    first_name: Mapped[str | None] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(8), default="fa")
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    referred_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    referral_bonus_awarded: Mapped[bool] = mapped_column(Boolean, default=False)
    pending_referral_bonus_gb: Mapped[int] = mapped_column(Integer, default=0)
    has_used_trial: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    trial_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trial_expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    orders: Mapped[list[Order]] = relationship(back_populates="user")
    vpn_services: Mapped[list[VPNService]] = relationship(back_populates="user")
    support_tickets: Mapped[list[SupportTicket]] = relationship(back_populates="user")
    wallet_transactions: Mapped[list[WalletTransaction]] = relationship(back_populates="user")
    referred_by: Mapped[User | None] = relationship(remote_side=[id])


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_type: Mapped[str] = mapped_column(String(32))
    gb_amount: Mapped[int] = mapped_column(Integer)
    price_toman: Mapped[int] = mapped_column(Integer)
    original_price_toman: Mapped[int | None] = mapped_column(Integer)
    discount_code: Mapped[str | None] = mapped_column(String(64), index=True)
    discount_amount_toman: Mapped[int] = mapped_column(Integer, default=0)
    payment_method: Mapped[str] = mapped_column(String(32), default="card", index=True)
    crypto_tx_hash: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    crypto_expected_usdt: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default=OrderStatus.pending_admin.value, index=True)
    receipt_file_id: Mapped[str | None] = mapped_column(String(512))
    admin_note: Mapped[str | None] = mapped_column(Text)
    marzban_username: Mapped[str | None] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="orders")


class VPNService(Base):
    __tablename__ = "vpn_services"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    marzban_username: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    subscription_url: Mapped[str | None] = mapped_column(Text)
    data_limit_gb: Mapped[float] = mapped_column(Float, default=0)
    used_traffic_gb: Mapped[float | None]
    remaining_traffic_gb: Mapped[float | None]
    status: Mapped[str] = mapped_column(String(32), default=VPNServiceStatus.active.value, index=True)
    low_traffic_alert_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    trial_expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="vpn_services")


class AdminActionLog(Base):
    __tablename__ = "admin_action_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BotSetting(Base):
    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default=SupportTicketStatus.open.value, index=True)
    last_message_preview: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="support_tickets")
    messages: Mapped[list[SupportMessage]] = relationship(back_populates="ticket")


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("support_tickets.id"), index=True)
    sender_type: Mapped[str] = mapped_column(String(16), index=True)
    sender_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    message_type: Mapped[str] = mapped_column(String(32), default="message")
    telegram_message_id: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped[SupportTicket] = relationship(back_populates="messages")


class DiscountCode(Base):
    __tablename__ = "discount_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    percent: Mapped[int] = mapped_column(Integer, default=0)
    amount_toman: Mapped[int] = mapped_column(Integer, default=0)
    max_uses: Mapped[int | None] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True, index=True)
    transaction_type: Mapped[str] = mapped_column(String(32), index=True)
    amount_toman: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default=WalletTransactionStatus.pending_admin.value, index=True)
    payment_method: Mapped[str | None] = mapped_column(String(32), index=True)
    receipt_file_id: Mapped[str | None] = mapped_column(String(512))
    crypto_tx_hash: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    crypto_amount: Mapped[str | None] = mapped_column(String(32))
    admin_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="wallet_transactions")


class CryptoPaymentQuote(Base):
    __tablename__ = "crypto_payment_quotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount_toman: Mapped[int] = mapped_column(Integer)
    expected_ltc: Mapped[str] = mapped_column(String(32))
    ltc_toman_rate: Mapped[int] = mapped_column(Integer)
    wallet_address: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), default=CryptoPaymentQuoteStatus.pending.value, index=True)
    tx_hash: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
