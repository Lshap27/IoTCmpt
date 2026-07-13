"""runtime control priority and AI voice

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("telemetry", sa.Column("manual_window_override", sa.Boolean(), nullable=True))
    op.add_column("telemetry", sa.Column("manual_led_override", sa.Boolean(), nullable=True))
    op.add_column("telemetry", sa.Column("control_priority", sa.String(length=32), nullable=True))
    op.add_column("telemetry", sa.Column("smoke_silenced", sa.Boolean(), nullable=True))
    op.add_column("ai_results", sa.Column("speech", sa.Text(), server_default="", nullable=False))
    op.add_column("ai_results", sa.Column("scene_summary", sa.Text(), server_default="", nullable=False))


def downgrade() -> None:
    op.drop_column("ai_results", "scene_summary")
    op.drop_column("ai_results", "speech")
    op.drop_column("telemetry", "smoke_silenced")
    op.drop_column("telemetry", "control_priority")
    op.drop_column("telemetry", "manual_led_override")
    op.drop_column("telemetry", "manual_window_override")
