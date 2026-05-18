"""card reference gate

Revision ID: 0010_card_reference_gate
Revises: 0009_reseller_panel
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_card_reference_gate"
down_revision = "0009_reseller_panel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("card_reference_code", sa.String(length=32), nullable=True))
    op.add_column(
        "users",
        sa.Column("card_access_unlocked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_users_card_reference_code", "users", ["card_reference_code"], unique=True)
    op.create_index("ix_users_card_access_unlocked", "users", ["card_access_unlocked"])


def downgrade() -> None:
    op.drop_index("ix_users_card_access_unlocked", table_name="users")
    op.drop_index("ix_users_card_reference_code", table_name="users")
    op.drop_column("users", "card_access_unlocked")
    op.drop_column("users", "card_reference_code")
