"""add gift delivery tokens

Revision ID: 0014_gift_delivery_tokens
Revises: 0013_order_purchased_by
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_gift_delivery_tokens"
down_revision = "0013_order_purchased_by"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("gift_delivery_token", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_orders_gift_delivery_token"), "orders", ["gift_delivery_token"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_orders_gift_delivery_token"), table_name="orders")
    op.drop_column("orders", "gift_delivery_token")
