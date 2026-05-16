"""referrals

Revision ID: 0005_referrals
Revises: 0004_wallet_transactions
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_referrals"
down_revision = "0004_wallet_transactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("referred_by_user_id", sa.Integer(), nullable=True))
    op.add_column(
        "users",
        sa.Column("referral_bonus_awarded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("pending_referral_bonus_gb", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_users_referred_by_user_id", "users", ["referred_by_user_id"])
    op.create_foreign_key(
        "fk_users_referred_by_user_id_users",
        "users",
        "users",
        ["referred_by_user_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_referred_by_user_id_users", "users", type_="foreignkey")
    op.drop_index("ix_users_referred_by_user_id", table_name="users")
    op.drop_column("users", "pending_referral_bonus_gb")
    op.drop_column("users", "referral_bonus_awarded")
    op.drop_column("users", "referred_by_user_id")
