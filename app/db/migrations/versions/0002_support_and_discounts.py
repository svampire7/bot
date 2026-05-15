"""support tickets and discount codes

Revision ID: 0002_support_and_discounts
Revises: 0001_initial
Create Date: 2026-05-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_support_and_discounts"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("original_price_toman", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("discount_code", sa.String(length=64), nullable=True))
    op.add_column("orders", sa.Column("discount_amount_toman", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_orders_discount_code", "orders", ["discount_code"])
    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_message_preview", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_support_tickets_user_id", "support_tickets", ["user_id"])
    op.create_index("ix_support_tickets_status", "support_tickets", ["status"])
    op.create_table(
        "support_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("support_tickets.id"), nullable=False),
        sa.Column("sender_type", sa.String(length=16), nullable=False),
        sa.Column("sender_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("message_type", sa.String(length=32), nullable=False),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_support_messages_ticket_id", "support_messages", ["ticket_id"])
    op.create_index("ix_support_messages_sender_type", "support_messages", ["sender_type"])
    op.create_index("ix_support_messages_sender_telegram_id", "support_messages", ["sender_telegram_id"])
    op.create_table(
        "discount_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("percent", sa.Integer(), nullable=False),
        sa.Column("amount_toman", sa.Integer(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("used_count", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_discount_codes_code", "discount_codes", ["code"], unique=True)
    op.create_index("ix_discount_codes_is_active", "discount_codes", ["is_active"])


def downgrade() -> None:
    op.drop_table("discount_codes")
    op.drop_table("support_messages")
    op.drop_table("support_tickets")
    op.drop_index("ix_orders_discount_code", table_name="orders")
    op.drop_column("orders", "discount_amount_toman")
    op.drop_column("orders", "discount_code")
    op.drop_column("orders", "original_price_toman")
