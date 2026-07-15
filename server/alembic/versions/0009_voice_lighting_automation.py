"""Persist deterministic lighting automation state.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lighting_rule_states",
        sa.Column("device_id", sa.String(length=64), sa.ForeignKey("devices.device_id"), primary_key=True),
        sa.Column("condition", sa.String(length=48), nullable=False, server_default="unknown"),
        sa.Column("last_telemetry_id", sa.Integer(), nullable=True),
        sa.Column("last_pose_result_id", sa.Integer(), nullable=True),
        sa.Column(
            "last_action_command_id",
            sa.String(length=64),
            sa.ForeignKey("commands.command_id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
        sa.Column(
            "speech_command_id",
            sa.String(length=64),
            sa.ForeignKey("commands.command_id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("lighting_rule_states")
