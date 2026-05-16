"""growth and ops

Revision ID: 0006_growth_and_ops
Revises: 0005_referrals
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_growth_and_ops"
down_revision = "0005_referrals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vpn_services",
        sa.Column("low_traffic_alert_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "crypto_payment_quotes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount_toman", sa.Integer(), nullable=False),
        sa.Column("expected_ltc", sa.String(length=32), nullable=False),
        sa.Column("ltc_toman_rate", sa.Integer(), nullable=False),
        sa.Column("wallet_address", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("tx_hash", sa.String(length=128), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_crypto_payment_quotes_user_id", "crypto_payment_quotes", ["user_id"])
    op.create_index("ix_crypto_payment_quotes_status", "crypto_payment_quotes", ["status"])
    op.create_index("ix_crypto_payment_quotes_tx_hash", "crypto_payment_quotes", ["tx_hash"], unique=True)
    op.create_index("ix_crypto_payment_quotes_expires_at", "crypto_payment_quotes", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_crypto_payment_quotes_expires_at", table_name="crypto_payment_quotes")
    op.drop_index("ix_crypto_payment_quotes_tx_hash", table_name="crypto_payment_quotes")
    op.drop_index("ix_crypto_payment_quotes_status", table_name="crypto_payment_quotes")
    op.drop_index("ix_crypto_payment_quotes_user_id", table_name="crypto_payment_quotes")
    op.drop_table("crypto_payment_quotes")
    op.drop_column("vpn_services", "low_traffic_alert_sent")
