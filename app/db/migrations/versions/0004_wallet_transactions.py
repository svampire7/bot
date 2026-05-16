"""wallet transactions

Revision ID: 0004_wallet_transactions
Revises: 0003_crypto_payments
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_wallet_transactions"
down_revision = "0003_crypto_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wallet_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("transaction_type", sa.String(length=32), nullable=False),
        sa.Column("amount_toman", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payment_method", sa.String(length=32), nullable=True),
        sa.Column("receipt_file_id", sa.String(length=512), nullable=True),
        sa.Column("crypto_tx_hash", sa.String(length=128), nullable=True),
        sa.Column("crypto_amount", sa.String(length=32), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_wallet_transactions_user_id", "wallet_transactions", ["user_id"])
    op.create_index("ix_wallet_transactions_order_id", "wallet_transactions", ["order_id"])
    op.create_index("ix_wallet_transactions_transaction_type", "wallet_transactions", ["transaction_type"])
    op.create_index("ix_wallet_transactions_status", "wallet_transactions", ["status"])
    op.create_index("ix_wallet_transactions_payment_method", "wallet_transactions", ["payment_method"])
    op.create_index("ix_wallet_transactions_crypto_tx_hash", "wallet_transactions", ["crypto_tx_hash"], unique=True)


def downgrade() -> None:
    op.drop_table("wallet_transactions")
