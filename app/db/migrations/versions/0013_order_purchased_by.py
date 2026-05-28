"""track order buyer separately from service recipient

Revision ID: 0013_order_purchased_by
Revises: 0012_unlimited_time_packages
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_order_purchased_by"
down_revision = "0012_unlimited_time_packages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("purchased_by_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_orders_purchased_by_user_id_users"),
        "orders",
        "users",
        ["purchased_by_user_id"],
        ["id"],
    )
    op.create_index(op.f("ix_orders_purchased_by_user_id"), "orders", ["purchased_by_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_orders_purchased_by_user_id"), table_name="orders")
    op.drop_constraint(op.f("fk_orders_purchased_by_user_id_users"), "orders", type_="foreignkey")
    op.drop_column("orders", "purchased_by_user_id")
