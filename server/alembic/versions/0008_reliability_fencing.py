"""Worker fencing tokens and MQTT inbox deduplication.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("ai_runs", "outbox_messages", "realtime_events"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("lease_token", sa.String(length=36), nullable=True))
            batch.create_index(f"ix_{table}_lease_token", ["lease_token"], unique=False)

    op.create_table(
        "mqtt_inbox_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.String(length=64), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("message_id", sa.String(length=96), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("received_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("device_id", "topic", "message_id", name="uq_mqtt_inbox_message"),
    )
    op.create_index("ix_mqtt_inbox_messages_device_id", "mqtt_inbox_messages", ["device_id"])
    op.create_index("ix_mqtt_inbox_messages_trace_id", "mqtt_inbox_messages", ["trace_id"])
    op.create_index("ix_mqtt_inbox_messages_received_at", "mqtt_inbox_messages", ["received_at"])


def downgrade() -> None:
    op.drop_index("ix_mqtt_inbox_messages_received_at", table_name="mqtt_inbox_messages")
    op.drop_index("ix_mqtt_inbox_messages_trace_id", table_name="mqtt_inbox_messages")
    op.drop_index("ix_mqtt_inbox_messages_device_id", table_name="mqtt_inbox_messages")
    op.drop_table("mqtt_inbox_messages")
    for table in ("realtime_events", "outbox_messages", "ai_runs"):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_lease_token")
            batch.drop_column("lease_token")
