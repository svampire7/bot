"""reseller panel

Revision ID: 0009_reseller_panel
Revises: 0008_bulk_batches
Create Date: 2026-05-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_reseller_panel"
down_revision = "0008_bulk_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resellers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_resellers_telegram_id", "resellers", ["telegram_id"], unique=True)
    op.create_index("ix_resellers_is_active", "resellers", ["is_active"])

    op.create_table(
        "reseller_bulk_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_code", sa.String(length=32), nullable=False),
        sa.Column("reseller_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_request_text", sa.Text(), nullable=False),
        sa.Column("parsed_items_json", sa.Text(), nullable=False),
        sa.Column("total_accounts", sa.Integer(), nullable=False),
        sa.Column("total_gb", sa.Integer(), nullable=False),
        sa.Column("total_price", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payment_proof_file_id", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_reseller_bulk_orders_order_code", "reseller_bulk_orders", ["order_code"], unique=True)
    op.create_index("ix_reseller_bulk_orders_reseller_telegram_id", "reseller_bulk_orders", ["reseller_telegram_id"])
    op.create_index("ix_reseller_bulk_orders_status", "reseller_bulk_orders", ["status"])

    op.create_table(
        "reseller_bulk_order_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bulk_order_id", sa.Integer(), sa.ForeignKey("reseller_bulk_orders.id"), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("quota_gb", sa.Integer(), nullable=False),
        sa.Column("config_link", sa.Text(), nullable=True),
        sa.Column("subscription_link", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_reseller_bulk_order_accounts_bulk_order_id", "reseller_bulk_order_accounts", ["bulk_order_id"])
    op.create_index("ix_reseller_bulk_order_accounts_username", "reseller_bulk_order_accounts", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_reseller_bulk_order_accounts_username", table_name="reseller_bulk_order_accounts")
    op.drop_index("ix_reseller_bulk_order_accounts_bulk_order_id", table_name="reseller_bulk_order_accounts")
    op.drop_table("reseller_bulk_order_accounts")
    op.drop_index("ix_reseller_bulk_orders_status", table_name="reseller_bulk_orders")
    op.drop_index("ix_reseller_bulk_orders_reseller_telegram_id", table_name="reseller_bulk_orders")
    op.drop_index("ix_reseller_bulk_orders_order_code", table_name="reseller_bulk_orders")
    op.drop_table("reseller_bulk_orders")
    op.drop_index("ix_resellers_is_active", table_name="resellers")
    op.drop_index("ix_resellers_telegram_id", table_name="resellers")
    op.drop_table("resellers")
