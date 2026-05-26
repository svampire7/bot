"""unlimited time packages

Revision ID: 0012_unlimited_time_packages
Revises: 0011_traffic_depleted_alerts
Create Date: 2026-05-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_unlimited_time_packages"
down_revision = "0011_traffic_depleted_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("package_type", sa.String(length=32), nullable=False, server_default="traffic"),
    )
    op.add_column("orders", sa.Column("duration_days", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("expire_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_orders_package_type"), "orders", ["package_type"], unique=False)
    op.create_index(op.f("ix_orders_expire_at"), "orders", ["expire_at"], unique=False)

    op.add_column(
        "vpn_services",
        sa.Column("package_type", sa.String(length=32), nullable=False, server_default="traffic"),
    )
    op.add_column("vpn_services", sa.Column("expire_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_vpn_services_package_type"), "vpn_services", ["package_type"], unique=False)
    op.create_index(op.f("ix_vpn_services_expire_at"), "vpn_services", ["expire_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_vpn_services_expire_at"), table_name="vpn_services")
    op.drop_index(op.f("ix_vpn_services_package_type"), table_name="vpn_services")
    op.drop_column("vpn_services", "expire_at")
    op.drop_column("vpn_services", "package_type")

    op.drop_index(op.f("ix_orders_expire_at"), table_name="orders")
    op.drop_index(op.f("ix_orders_package_type"), table_name="orders")
    op.drop_column("orders", "expire_at")
    op.drop_column("orders", "duration_days")
    op.drop_column("orders", "package_type")
