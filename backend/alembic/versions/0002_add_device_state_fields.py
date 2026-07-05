"""Add device state fields to sensor readings.

Revision ID: 0002_add_device_state_fields
Revises: 0001_initial_schema
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_add_device_state_fields"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sensor_readings", sa.Column("led_status", sa.String(length=16), nullable=True))
    op.add_column("sensor_readings", sa.Column("window_status", sa.String(length=16), nullable=True))
    op.add_column("sensor_readings", sa.Column("dehumidifier_state", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("sensor_readings", "dehumidifier_state")
    op.drop_column("sensor_readings", "window_status")
    op.drop_column("sensor_readings", "led_status")
