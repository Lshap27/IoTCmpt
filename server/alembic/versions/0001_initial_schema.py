"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-08

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_devices_device_id"), "devices", ["device_id"], unique=True)
    op.create_index(op.f("ix_devices_status"), "devices", ["status"], unique=False)

    op.create_table(
        "telemetry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("sampled_at", sa.DateTime(), nullable=False),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("humidity_percent", sa.Float(), nullable=True),
        sa.Column("tvoc_ppb", sa.Float(), nullable=True),
        sa.Column("hcho_ug_m3", sa.Float(), nullable=True),
        sa.Column("eco2_ppm", sa.Float(), nullable=True),
        sa.Column("light_is_dark", sa.Boolean(), nullable=True),
        sa.Column("window_open", sa.Boolean(), nullable=True),
        sa.Column("alarm_on", sa.Boolean(), nullable=True),
        sa.Column("manual_override", sa.Boolean(), nullable=True),
        sa.Column("air_quality", sa.String(length=32), nullable=True),
        sa.Column("recommend_open_window", sa.Boolean(), nullable=True),
        sa.Column("alarm_enabled", sa.Boolean(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_telemetry_device_id"), "telemetry", ["device_id"], unique=False)
    op.create_index(op.f("ix_telemetry_sampled_at"), "telemetry", ["sampled_at"], unique=False)
    op.create_index(op.f("ix_telemetry_created_at"), "telemetry", ["created_at"], unique=False)

    op.create_table(
        "device_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_device_events_device_id"), "device_events", ["device_id"], unique=False)
    op.create_index(op.f("ix_device_events_type"), "device_events", ["type"], unique=False)
    op.create_index(op.f("ix_device_events_created_at"), "device_events", ["created_at"], unique=False)

    op.create_table(
        "commands",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("command_id", sa.String(length=64), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("parameter", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_commands_command_id"), "commands", ["command_id"], unique=True)
    op.create_index(op.f("ix_commands_device_id"), "commands", ["device_id"], unique=False)
    op.create_index(op.f("ix_commands_type"), "commands", ["type"], unique=False)
    op.create_index(op.f("ix_commands_status"), "commands", ["status"], unique=False)
    op.create_index(op.f("ix_commands_created_at"), "commands", ["created_at"], unique=False)

    op.create_table(
        "ai_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("command_id", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_results_device_id"), "ai_results", ["device_id"], unique=False)
    op.create_index(op.f("ix_ai_results_command_id"), "ai_results", ["command_id"], unique=False)
    op.create_index(op.f("ix_ai_results_created_at"), "ai_results", ["created_at"], unique=False)

    op.create_table(
        "image_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_image_assets_device_id"), "image_assets", ["device_id"], unique=False)
    op.create_index(op.f("ix_image_assets_created_at"), "image_assets", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("image_assets")
    op.drop_table("ai_results")
    op.drop_table("commands")
    op.drop_table("device_events")
    op.drop_table("telemetry")
    op.drop_table("devices")
