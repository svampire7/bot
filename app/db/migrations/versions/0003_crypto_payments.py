"""crypto payment fields

Revision ID: 0003_crypto_payments
Revises: 0002_support_and_discounts
Create Date: 2026-05-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_crypto_payments"
down_revision = "0002_support_and_discounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("payment_method", sa.String(length=32), nullable=False, server_default="card"),
    )
    op.add_column("orders", sa.Column("crypto_tx_hash", sa.String(length=128), nullable=True))
    op.add_column("orders", sa.Column("crypto_expected_usdt", sa.String(length=32), nullable=True))
    op.create_index("ix_orders_payment_method", "orders", ["payment_method"])
    op.create_index("ix_orders_crypto_tx_hash", "orders", ["crypto_tx_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_orders_crypto_tx_hash", table_name="orders")
    op.drop_index("ix_orders_payment_method", table_name="orders")
    op.drop_column("orders", "crypto_expected_usdt")
    op.drop_column("orders", "crypto_tx_hash")
    op.drop_column("orders", "payment_method")
