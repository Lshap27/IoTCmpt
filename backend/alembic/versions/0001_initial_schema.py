"""Initial backend schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sensor_readings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("temperature_in", sa.Float()),
        sa.Column("humidity_in", sa.Float()),
        sa.Column("temperature_out", sa.Float()),
        sa.Column("humidity_out", sa.Float()),
        sa.Column("co2", sa.Float()),
        sa.Column("tvoc", sa.Float()),
        sa.Column("hcho", sa.Float()),
        sa.Column("light", sa.Integer()),
        sa.Column("air_quality", sa.String(length=32)),
        sa.Column("recommend_open_window", sa.Integer()),
        sa.Column("alarm_enabled", sa.Integer()),
        sa.Column("reason", sa.Text()),
        sa.Column("raw_payload", sa.JSON()),
        sa.Column("sampled_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sensor_readings_sampled_at", "sensor_readings", ["sampled_at"])

    op.create_table(
        "pose_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pose", sa.String(length=128), nullable=False),
        sa.Column("human_presence", sa.String(length=16), nullable=False),
        sa.Column("image_url", sa.String(length=512)),
        sa.Column("pose_image_url", sa.String(length=512)),
        sa.Column("photo_time", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pose_events_photo_time", "pose_events", ["photo_time"])

    op.create_table(
        "device_commands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("command", sa.String(length=64), nullable=False),
        sa.Column("parameter", sa.String(length=128)),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("reason", sa.Text()),
        sa.Column("raw_payload", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("executed_at", sa.DateTime()),
    )
    op.create_index("ix_device_commands_status", "device_commands", ["status"])
    op.create_index("ix_device_commands_command", "device_commands", ["command"])
    op.create_index("ix_device_commands_created_at", "device_commands", ["created_at"])


def downgrade() -> None:
    op.drop_table("device_commands")
    op.drop_table("pose_events")
    op.drop_table("sensor_readings")
