"""hardware loop features

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-11
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("telemetry", sa.Column("smoke_detected", sa.Boolean(), nullable=True))
    op.add_column("telemetry", sa.Column("led_on", sa.Boolean(), nullable=True))
    op.add_column("device_events", sa.Column("acknowledged_at", sa.DateTime(), nullable=True))
    op.add_column("image_assets", sa.Column("kind", sa.String(length=32), server_default="capture", nullable=False))
    op.create_index(op.f("ix_image_assets_kind"), "image_assets", ["kind"], unique=False)
    op.create_table(
        "pose_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("source_image_id", sa.Integer(), nullable=False),
        sa.Column("annotated_image_id", sa.Integer(), nullable=True),
        sa.Column("human_present", sa.Boolean(), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["annotated_image_id"], ["image_assets.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.ForeignKeyConstraint(["source_image_id"], ["image_assets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pose_results_device_id"), "pose_results", ["device_id"], unique=False)
    op.create_index(op.f("ix_pose_results_source_image_id"), "pose_results", ["source_image_id"], unique=False)
    op.create_index(op.f("ix_pose_results_created_at"), "pose_results", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("pose_results")
    op.drop_index(op.f("ix_image_assets_kind"), table_name="image_assets")
    op.drop_column("image_assets", "kind")
    op.drop_column("device_events", "acknowledged_at")
    op.drop_column("telemetry", "led_on")
    op.drop_column("telemetry", "smoke_detected")
