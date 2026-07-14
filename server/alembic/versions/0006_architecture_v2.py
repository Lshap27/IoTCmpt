"""architecture v2 command, AI, capability and automation state

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-14
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("commands", sa.Column("trace_id", sa.String(length=64), nullable=True))
    op.add_column("commands", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.add_column("commands", sa.Column("expires_at", sa.DateTime(), nullable=True))
    op.add_column("commands", sa.Column("accepted_at", sa.DateTime(), nullable=True))
    op.add_column("commands", sa.Column("error_code", sa.String(length=64), nullable=True))
    op.add_column("commands", sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False))
    op.create_index(op.f("ix_commands_trace_id"), "commands", ["trace_id"], unique=False)
    op.create_index(op.f("ix_commands_idempotency_key"), "commands", ["idempotency_key"], unique=True)

    op.create_table(
        "device_capabilities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("protocol_version", sa.String(length=16), nullable=False),
        sa.Column("firmware_version", sa.String(length=64), nullable=False),
        sa.Column("hardware_model", sa.String(length=64), nullable=False),
        sa.Column("commands", sa.JSON(), nullable=False),
        sa.Column("capability_hash", sa.String(length=64), nullable=False),
        sa.Column("seen_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id"),
    )
    op.create_index(op.f("ix_device_capabilities_device_id"), "device_capabilities", ["device_id"], unique=True)
    op.create_index(op.f("ix_device_capabilities_seen_at"), "device_capabilities", ["seen_at"], unique=False)

    op.create_table(
        "device_twins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("desired_state", sa.JSON(), nullable=False),
        sa.Column("reported_state", sa.JSON(), nullable=False),
        sa.Column("desired_at", sa.DateTime(), nullable=True),
        sa.Column("reported_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id"),
    )
    op.create_index(op.f("ix_device_twins_device_id"), "device_twins", ["device_id"], unique=True)

    op.create_table(
        "command_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("command_id", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("from_status", sa.String(length=24), nullable=True),
        sa.Column("to_status", sa.String(length=24), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["command_id"], ["commands.command_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("command_id", "trace_id", "to_status", "occurred_at"):
        op.create_index(op.f(f"ix_command_events_{column}"), "command_events", [column], unique=False)

    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("command_id", sa.String(length=64), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("qos", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["command_id"], ["commands.command_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("command_id"),
    )
    for column, unique in (("command_id", True), ("status", False), ("next_attempt_at", False), ("created_at", False)):
        op.create_index(op.f(f"ix_outbox_messages_{column}"), "outbox_messages", [column], unique=unique)

    op.create_table(
        "ai_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("trigger", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("output_payload", sa.JSON(), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column, unique in (
        ("run_id", True),
        ("trace_id", False),
        ("device_id", False),
        ("kind", False),
        ("status", False),
        ("created_at", False),
    ):
        op.create_index(op.f(f"ix_ai_runs_{column}"), "ai_runs", [column], unique=unique)

    op.create_table(
        "ai_tool_calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("call_id", sa.String(length=96), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["ai_runs.run_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column, unique in (
        ("call_id", True),
        ("run_id", False),
        ("trace_id", False),
        ("tool_name", False),
        ("status", False),
        ("created_at", False),
    ):
        op.create_index(op.f(f"ix_ai_tool_calls_{column}"), "ai_tool_calls", [column], unique=unique)

    op.create_table(
        "automation_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("event_trigger_enabled", sa.Boolean(), nullable=False),
        sa.Column("patrol_enabled", sa.Boolean(), nullable=False),
        sa.Column("patrol_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("patrol_force_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("execution_mode", sa.String(length=24), nullable=False),
        sa.Column("thresholds", sa.JSON(), nullable=False),
        sa.Column("last_fingerprint", sa.JSON(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("last_model_run_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id"),
    )
    op.create_index(op.f("ix_automation_policies_device_id"), "automation_policies", ["device_id"], unique=True)

    op.create_table(
        "ai_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.ForeignKeyConstraint(["run_id"], ["ai_runs.run_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_ai_reports_run_id"),
    )
    op.create_index(op.f("ix_ai_reports_run_id"), "ai_reports", ["run_id"], unique=False)
    op.create_index(op.f("ix_ai_reports_device_id"), "ai_reports", ["device_id"], unique=False)
    op.create_index(op.f("ix_ai_reports_created_at"), "ai_reports", ["created_at"], unique=False)


def downgrade() -> None:
    for table in (
        "ai_reports",
        "automation_policies",
        "ai_tool_calls",
        "ai_runs",
        "outbox_messages",
        "command_events",
        "device_twins",
        "device_capabilities",
    ):
        op.drop_table(table)
    op.drop_index(op.f("ix_commands_idempotency_key"), table_name="commands")
    op.drop_index(op.f("ix_commands_trace_id"), table_name="commands")
    for column in ("attempt_count", "error_code", "accepted_at", "expires_at", "idempotency_key", "trace_id"):
        op.drop_column("commands", column)
