"""Add durable automation plans and AI strategy proposals.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

SYSTEM_LIGHTING_SPEC = {
    "schema_version": "1.0",
    "title": "系统默认照明自动化",
    "duration_seconds": 86400,
    "timezone": "Asia/Shanghai",
    "manual_override_policy": "respect",
    "end_behavior": "keep_state",
    "clarifications": [],
    "rules": [
        {
            "id": "system-light-on",
            "description": "连续暗光且检测到人体时开启照明",
            "trigger": {
                "type": "condition",
                "mode": "all",
                "items": [
                    {"fact": "light_is_dark", "op": "eq", "value": True},
                    {"fact": "human_present", "op": "eq", "value": True},
                ],
                "stability_samples": 2,
            },
            "action": {"command": "led.on", "parameter": {}},
            "cooldown_seconds": 1,
        },
        {
            "id": "system-light-off",
            "description": "连续明亮且确认无人时关闭照明",
            "trigger": {
                "type": "condition",
                "mode": "all",
                "items": [
                    {"fact": "light_is_dark", "op": "eq", "value": False},
                    {"fact": "human_present", "op": "eq", "value": False},
                ],
                "stability_samples": 2,
            },
            "action": {"command": "led.off", "parameter": {}},
            "cooldown_seconds": 1,
        },
    ],
}


def _system_plan_id(device_id: str) -> str:
    return f"plan-system-lighting-{hashlib.sha256(device_id.encode()).hexdigest()[:20]}"


def _copy_lighting_states() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT device_id, condition, last_action_command_id, speech_command_id FROM lighting_rule_states")
    ).mappings()
    plans = sa.table(
        "automation_plans",
        sa.column("plan_id", sa.String()),
        sa.column("device_id", sa.String()),
        sa.column("plan_type", sa.String()),
        sa.column("title", sa.String()),
        sa.column("status", sa.String()),
        sa.column("current_version", sa.Integer()),
        sa.column("source_prompt", sa.Text()),
        sa.column("activation_blockers", sa.JSON()),
        sa.column("started_at", sa.DateTime()),
    )
    versions = sa.table(
        "automation_plan_versions",
        sa.column("plan_id", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("spec", sa.JSON()),
        sa.column("explanation", sa.Text()),
        sa.column("validation", sa.JSON()),
    )
    states = sa.table(
        "automation_rule_states",
        sa.column("plan_id", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("rule_id", sa.String()),
        sa.column("last_condition", sa.String()),
        sa.column("stable_count", sa.Integer()),
        sa.column("last_command_id", sa.String()),
        sa.column("meta", sa.JSON()),
    )
    for row in rows:
        plan_id = _system_plan_id(row["device_id"])
        condition = str(row["condition"] or "unknown")
        active_rule = (
            "system-light-on" if "dark" in condition else "system-light-off" if "bright" in condition else None
        )
        bind.execute(
            plans.insert(),
            {
                "plan_id": plan_id,
                "device_id": row["device_id"],
                "plan_type": "system",
                "title": SYSTEM_LIGHTING_SPEC["title"],
                "status": "active",
                "current_version": 1,
                "source_prompt": "system-default-lighting",
                "activation_blockers": [],
                "started_at": datetime.now(UTC).replace(tzinfo=None),
            },
        )
        bind.execute(
            versions.insert(),
            {
                "plan_id": plan_id,
                "version": 1,
                "spec": SYSTEM_LIGHTING_SPEC,
                "explanation": "由现有确定性灯光规则迁移的系统计划",
                "validation": {"valid": True, "system": True, "migrated_from": "lighting_rule_states"},
            },
        )
        for rule_id in ("system-light-on", "system-light-off"):
            bind.execute(
                states.insert(),
                {
                    "plan_id": plan_id,
                    "version": 1,
                    "rule_id": rule_id,
                    "last_condition": "true" if rule_id == active_rule else "unknown",
                    "stable_count": 2 if rule_id == active_rule else 0,
                    "last_command_id": row["last_action_command_id"] if rule_id == active_rule else None,
                    "meta": {
                        "speech_command_id": row["speech_command_id"] if rule_id == "system-light-on" else None,
                        "system": True,
                        "migrated": True,
                    },
                },
            )


def upgrade() -> None:
    op.add_column(
        "automation_policies",
        sa.Column("strategy_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "automation_policies",
        sa.Column("strategy_min_interval_seconds", sa.Integer(), nullable=False, server_default="300"),
    )
    op.add_column(
        "automation_policies",
        sa.Column("strategy_force_interval_seconds", sa.Integer(), nullable=False, server_default="3600"),
    )
    op.add_column("automation_policies", sa.Column("last_strategy_fingerprint", sa.JSON(), nullable=True))
    op.add_column("automation_policies", sa.Column("last_strategy_run_at", sa.DateTime(), nullable=True))

    op.create_table(
        "automation_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("device_id", sa.String(length=64), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("plan_type", sa.String(length=16), nullable=False, server_default="user"),
        sa.Column("title", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("activation_blockers", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("paused_at", sa.DateTime(), nullable=True),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("plan_id", name="uq_automation_plans_plan_id"),
    )
    op.create_index("ix_automation_plans_device_id", "automation_plans", ["device_id"])
    op.create_index("ix_automation_plans_status", "automation_plans", ["status"])
    op.create_index("ix_automation_plans_ends_at", "automation_plans", ["ends_at"])
    op.create_index(
        "uq_active_user_plan_per_device",
        "automation_plans",
        ["device_id"],
        unique=True,
        postgresql_where=sa.text("plan_type = 'user' AND status IN ('active', 'paused')"),
        sqlite_where=sa.text("plan_type = 'user' AND status IN ('active', 'paused')"),
    )

    op.create_table(
        "automation_plan_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.String(length=64),
            sa.ForeignKey("automation_plans.plan_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_ai_run_id", sa.String(length=64), sa.ForeignKey("ai_runs.run_id"), nullable=True),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("validation", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("plan_id", "version", name="uq_automation_plan_version"),
    )
    op.create_index("ix_automation_plan_versions_plan_id", "automation_plan_versions", ["plan_id"])
    op.create_index("ix_automation_plan_versions_source_ai_run_id", "automation_plan_versions", ["source_ai_run_id"])

    op.create_table(
        "automation_rule_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.String(length=64),
            sa.ForeignKey("automation_plans.plan_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.String(length=48), nullable=False),
        sa.Column("last_condition", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("stable_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_fired_at", sa.DateTime(), nullable=True),
        sa.Column("next_fire_at", sa.DateTime(), nullable=True),
        sa.Column("last_command_id", sa.String(length=64), sa.ForeignKey("commands.command_id", ondelete="SET NULL")),
        sa.Column("last_occurrence_key", sa.String(length=160), nullable=True),
        sa.Column("blocked_reason", sa.String(length=64), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("plan_id", "version", "rule_id", name="uq_automation_rule_state"),
    )
    op.create_index("ix_automation_rule_states_plan_id", "automation_rule_states", ["plan_id"])
    op.create_index("ix_automation_rule_states_next_fire_at", "automation_rule_states", ["next_fire_at"])
    op.create_index("ix_automation_rule_states_last_command_id", "automation_rule_states", ["last_command_id"])

    op.create_table(
        "automation_plan_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "plan_id",
            sa.String(length=64),
            sa.ForeignKey("automation_plans.plan_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("device_id", sa.String(length=64), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.String(length=48), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_automation_plan_events_plan_id", "automation_plan_events", ["plan_id"])
    op.create_index("ix_automation_plan_events_device_id", "automation_plan_events", ["device_id"])
    op.create_index("ix_automation_plan_events_trace_id", "automation_plan_events", ["trace_id"])

    op.create_table(
        "ai_strategies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("device_id", sa.String(length=64), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("run_id", sa.String(length=64), sa.ForeignKey("ai_runs.run_id"), nullable=False, unique=True),
        sa.Column("plan_id", sa.String(length=64), sa.ForeignKey("automation_plans.plan_id"), nullable=True),
        sa.Column("base_version", sa.Integer(), nullable=True),
        sa.Column("proposed_spec", sa.JSON(), nullable=False),
        sa.Column("diff", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="proposed"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_ai_strategies_device_id", "ai_strategies", ["device_id"])
    op.create_index("ix_ai_strategies_plan_id", "ai_strategies", ["plan_id"])
    op.create_index("ix_ai_strategies_status", "ai_strategies", ["status"])
    _copy_lighting_states()


def downgrade() -> None:
    op.drop_table("ai_strategies")
    op.drop_table("automation_plan_events")
    op.drop_table("automation_rule_states")
    op.drop_table("automation_plan_versions")
    op.drop_index("uq_active_user_plan_per_device", table_name="automation_plans")
    op.drop_table("automation_plans")
    op.drop_column("automation_policies", "last_strategy_run_at")
    op.drop_column("automation_policies", "last_strategy_fingerprint")
    op.drop_column("automation_policies", "strategy_force_interval_seconds")
    op.drop_column("automation_policies", "strategy_min_interval_seconds")
    op.drop_column("automation_policies", "strategy_enabled")
