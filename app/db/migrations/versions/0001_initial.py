"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_username", sa.String(length=128), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("is_blocked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)
    op.create_index("ix_users_telegram_username", "users", ["telegram_username"])
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("order_type", sa.String(length=32), nullable=False),
        sa.Column("gb_amount", sa.Integer(), nullable=False),
        sa.Column("price_toman", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("receipt_file_id", sa.String(length=512), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("marzban_username", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_orders_user_id", "orders", ["user_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_marzban_username", "orders", ["marzban_username"])
    op.create_table(
        "vpn_services",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("marzban_username", sa.String(length=128), nullable=False),
        sa.Column("subscription_url", sa.Text(), nullable=True),
        sa.Column("data_limit_gb", sa.Integer(), nullable=False),
        sa.Column("used_traffic_gb", sa.Float(), nullable=True),
        sa.Column("remaining_traffic_gb", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_vpn_services_user_id", "vpn_services", ["user_id"])
    op.create_index("ix_vpn_services_status", "vpn_services", ["status"])
    op.create_index("ix_vpn_services_marzban_username", "vpn_services", ["marzban_username"], unique=True)
    op.create_table(
        "admin_action_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_admin_action_logs_admin_telegram_id", "admin_action_logs", ["admin_telegram_id"])
    op.create_index("ix_admin_action_logs_order_id", "admin_action_logs", ["order_id"])
    op.create_index("ix_admin_action_logs_action", "admin_action_logs", ["action"])
    op.create_table(
        "bot_settings",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("bot_settings")
    op.drop_table("admin_action_logs")
    op.drop_table("vpn_services")
    op.drop_table("orders")
    op.drop_table("users")
