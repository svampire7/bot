"""bulk batches

Revision ID: 0008_bulk_batches
Revises: 0007_free_trials
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_bulk_batches"
down_revision = "0007_free_trials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bulk_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("admin_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("total_accounts", sa.Integer(), nullable=False),
        sa.Column("total_gb", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_bulk_batches_name", "bulk_batches", ["name"])
    op.create_index("ix_bulk_batches_admin_telegram_id", "bulk_batches", ["admin_telegram_id"])
    op.create_index("ix_bulk_batches_status", "bulk_batches", ["status"])

    op.create_table(
        "bulk_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("bulk_batches.id"), nullable=False),
        sa.Column("marzban_username", sa.String(length=128), nullable=False),
        sa.Column("gb_amount", sa.Integer(), nullable=False),
        sa.Column("subscription_url", sa.Text(), nullable=True),
        sa.Column("config_links_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_bulk_accounts_batch_id", "bulk_accounts", ["batch_id"])
    op.create_index("ix_bulk_accounts_marzban_username", "bulk_accounts", ["marzban_username"], unique=True)
    op.create_index("ix_bulk_accounts_status", "bulk_accounts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_bulk_accounts_status", table_name="bulk_accounts")
    op.drop_index("ix_bulk_accounts_marzban_username", table_name="bulk_accounts")
    op.drop_index("ix_bulk_accounts_batch_id", table_name="bulk_accounts")
    op.drop_table("bulk_accounts")
    op.drop_index("ix_bulk_batches_status", table_name="bulk_batches")
    op.drop_index("ix_bulk_batches_admin_telegram_id", table_name="bulk_batches")
    op.drop_index("ix_bulk_batches_name", table_name="bulk_batches")
    op.drop_table("bulk_batches")
