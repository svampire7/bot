"""traffic depleted alerts

Revision ID: 0011_traffic_depleted_alerts
Revises: 0010_card_reference_gate
Create Date: 2026-05-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_traffic_depleted_alerts"
down_revision = "0010_card_reference_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vpn_services",
        sa.Column(
            "traffic_depleted_alert_sent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("vpn_services", "traffic_depleted_alert_sent")
