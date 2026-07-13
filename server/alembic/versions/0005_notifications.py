"""persisted dorm notifications

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("voice_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("voice_command_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.ForeignKeyConstraint(["voice_command_id"], ["commands.command_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("voice_command_id"),
    )
    op.create_index(op.f("ix_notifications_device_id"), "notifications", ["device_id"], unique=False)
    op.create_index(op.f("ix_notifications_created_at"), "notifications", ["created_at"], unique=False)
    op.create_index(op.f("ix_notifications_voice_command_id"), "notifications", ["voice_command_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_notifications_voice_command_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_created_at"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_device_id"), table_name="notifications")
    op.drop_table("notifications")
