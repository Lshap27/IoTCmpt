"""Reliable worker leases, realtime/trace outboxes, and v1 cutover.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("commands") as batch:
        batch.drop_index("ix_commands_idempotency_key")
        batch.create_index("ix_commands_idempotency_key", ["idempotency_key"], unique=False)
        batch.create_unique_constraint("uq_command_idempotency", ["device_id", "source", "idempotency_key"])

    with op.batch_alter_table("outbox_messages") as batch:
        batch.add_column(sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="8"))
        batch.add_column(sa.Column("lease_owner", sa.String(length=96), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_outbox_messages_lease_owner", ["lease_owner"], unique=False)
        batch.create_index("ix_outbox_messages_lease_expires_at", ["lease_expires_at"], unique=False)

    with op.batch_alter_table("ai_runs") as batch:
        batch.add_column(sa.Column("available_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
        batch.add_column(sa.Column("lease_owner", sa.String(length=96), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("heartbeat_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("cancel_requested_at", sa.DateTime(), nullable=True))
        for column in ("available_at", "lease_owner", "lease_expires_at"):
            batch.create_index(f"ix_ai_runs_{column}", [column], unique=False)

    with op.batch_alter_table("automation_policies") as batch:
        batch.add_column(sa.Column("vision_schedule_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("vision_interval_seconds", sa.Integer(), nullable=False, server_default="300"))
        batch.add_column(sa.Column("sedentary_trigger_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("sedentary_threshold_seconds", sa.Integer(), nullable=False, server_default="7200"))

    op.create_table(
        "realtime_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(length=96), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.UniqueConstraint("event_id"),
    )
    for column in (
        "event_id",
        "device_id",
        "trace_id",
        "type",
        "status",
        "lease_owner",
        "lease_expires_at",
        "created_at",
    ):
        op.create_index(f"ix_realtime_events_{column}", "realtime_events", [column], unique=column == "event_id")

    op.create_table(
        "trace_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=True),
        sa.Column("component", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.UniqueConstraint("event_id"),
    )
    for column in ("event_id", "trace_id", "device_id", "component", "event_type", "status", "occurred_at"):
        op.create_index(f"ix_trace_events_{column}", "trace_events", [column], unique=column == "event_id")

    op.create_table(
        "runtime_instances",
        sa.Column("instance_id", sa.String(length=96), primary_key=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("meta", sa.JSON(), nullable=False),
    )
    op.create_index("ix_runtime_instances_role", "runtime_instances", ["role"], unique=False)
    op.create_index("ix_runtime_instances_heartbeat_at", "runtime_instances", ["heartbeat_at"], unique=False)

    op.create_table(
        "runtime_leases",
        sa.Column("name", sa.String(length=64), primary_key=True),
        sa.Column("owner", sa.String(length=96), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_runtime_leases_owner", "runtime_leases", ["owner"], unique=False)
    op.create_index("ix_runtime_leases_lease_expires_at", "runtime_leases", ["lease_expires_at"], unique=False)

    bind = op.get_bind()
    metadata = sa.MetaData()
    legacy = sa.Table("ai_results", metadata, autoload_with=bind)
    ai_runs = sa.Table("ai_runs", metadata, autoload_with=bind)
    commands = sa.Table("commands", metadata, autoload_with=bind)
    for row in bind.execute(sa.select(legacy)).mappings():
        trace_id = f"legacy-ai-{row['id']}"
        command = bind.execute(sa.select(commands.c.trace_id).where(commands.c.command_id == row["command_id"])).first()
        if command and command[0]:
            trace_id = command[0]
        output = {
            "kind": "decision",
            "summary": row["summary"],
            "risk_level": row["risk_level"],
            "confidence": row["confidence"],
            "reason": row["reason"],
            "speech": row.get("speech") or "",
            "scene_summary": row.get("scene_summary") or "",
            "legacy_command_id": row["command_id"],
        }
        bind.execute(
            ai_runs.insert().values(
                run_id=f"legacy-ai-{row['id']}",
                trace_id=trace_id,
                device_id=row["device_id"],
                kind="decision",
                trigger="legacy",
                status="succeeded",
                input_payload={"migrated_from": "ai_results"},
                output_payload=output,
                model=row["model"],
                created_at=row["created_at"],
                started_at=row["created_at"],
                completed_at=row["created_at"],
                attempt_count=1,
                max_attempts=3,
            )
        )

    bind.execute(
        commands.update()
        .where(commands.c.status == "pending")
        .values(status="expired", error_code="legacy_suggestion", executed_at=datetime.utcnow())
    )
    bind.execute(commands.delete().where(commands.c.type == "none"))
    op.drop_table("ai_results")


def downgrade() -> None:
    op.create_table(
        "ai_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.String(length=64), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("command_id", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("risk_level", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("speech", sa.Text(), nullable=False, server_default=""),
        sa.Column("scene_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    for table in ("runtime_leases", "runtime_instances", "trace_events", "realtime_events"):
        op.drop_table(table)
    with op.batch_alter_table("automation_policies") as batch:
        for column in (
            "sedentary_threshold_seconds",
            "sedentary_trigger_enabled",
            "vision_interval_seconds",
            "vision_schedule_enabled",
        ):
            batch.drop_column(column)
    with op.batch_alter_table("ai_runs") as batch:
        for column in (
            "cancel_requested_at",
            "heartbeat_at",
            "lease_expires_at",
            "lease_owner",
            "max_attempts",
            "attempt_count",
            "available_at",
        ):
            batch.drop_column(column)
    with op.batch_alter_table("outbox_messages") as batch:
        for column in ("lease_expires_at", "lease_owner", "max_attempts"):
            batch.drop_column(column)
    with op.batch_alter_table("commands") as batch:
        batch.drop_constraint("uq_command_idempotency", type_="unique")
        batch.drop_index("ix_commands_idempotency_key")
        batch.create_index("ix_commands_idempotency_key", ["idempotency_key"], unique=True)
