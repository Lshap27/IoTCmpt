"""Add persistent automation actuator claims.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automation_actuator_claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.String(length=64), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("actuator", sa.String(length=16), nullable=False),
        sa.Column("owner_type", sa.String(length=16), nullable=False),
        sa.Column(
            "plan_id",
            sa.String(length=64),
            sa.ForeignKey("automation_plans.plan_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rule_ids", sa.JSON(), nullable=False),
        sa.Column("target_command", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="claimed"),
        sa.Column("reason", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("observation_key", sa.String(length=200), nullable=False, server_default=""),
        sa.Column(
            "command_id",
            sa.String(length=64),
            sa.ForeignKey("commands.command_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("device_id", "actuator", name="uq_automation_actuator_claim"),
    )
    op.create_index("ix_automation_actuator_claims_device_id", "automation_actuator_claims", ["device_id"])
    op.create_index("ix_automation_actuator_claims_actuator", "automation_actuator_claims", ["actuator"])
    op.create_index("ix_automation_actuator_claims_owner_type", "automation_actuator_claims", ["owner_type"])
    op.create_index("ix_automation_actuator_claims_plan_id", "automation_actuator_claims", ["plan_id"])
    op.create_index("ix_automation_actuator_claims_status", "automation_actuator_claims", ["status"])
    op.create_index("ix_automation_actuator_claims_command_id", "automation_actuator_claims", ["command_id"])


def downgrade() -> None:
    op.drop_table("automation_actuator_claims")
