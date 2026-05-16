"""free trials

Revision ID: 0007_free_trials
Revises: 0006_growth_and_ops
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_free_trials"
down_revision = "0006_growth_and_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("has_used_trial", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("trial_created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("trial_expire_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_has_used_trial", "users", ["has_used_trial"])
    op.create_index("ix_users_trial_expire_at", "users", ["trial_expire_at"])

    op.alter_column(
        "vpn_services",
        "data_limit_gb",
        existing_type=sa.Integer(),
        type_=sa.Float(),
        existing_nullable=False,
        postgresql_using="data_limit_gb::double precision",
    )
    op.add_column(
        "vpn_services",
        sa.Column("is_trial", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("vpn_services", sa.Column("trial_expire_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_vpn_services_is_trial", "vpn_services", ["is_trial"])
    op.create_index("ix_vpn_services_trial_expire_at", "vpn_services", ["trial_expire_at"])


def downgrade() -> None:
    op.drop_index("ix_vpn_services_trial_expire_at", table_name="vpn_services")
    op.drop_index("ix_vpn_services_is_trial", table_name="vpn_services")
    op.drop_column("vpn_services", "trial_expire_at")
    op.drop_column("vpn_services", "is_trial")
    op.alter_column(
        "vpn_services",
        "data_limit_gb",
        existing_type=sa.Float(),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="data_limit_gb::integer",
    )

    op.drop_index("ix_users_trial_expire_at", table_name="users")
    op.drop_index("ix_users_has_used_trial", table_name="users")
    op.drop_column("users", "trial_expire_at")
    op.drop_column("users", "trial_created_at")
    op.drop_column("users", "has_used_trial")
