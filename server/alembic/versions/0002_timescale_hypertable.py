"""telemetry hypertable (TimescaleDB)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-08

PostgreSQL-only: widens the telemetry primary key to (id, sampled_at) as required
by TimescaleDB, then converts the table to a hypertable. The ORM keeps a
single-column id primary key (SQLite tests cannot autoincrement composite PKs);
the composite PK exists only at the database level and is managed here.
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("ALTER TABLE telemetry DROP CONSTRAINT telemetry_pkey")
    op.execute("ALTER TABLE telemetry ADD PRIMARY KEY (id, sampled_at)")
    op.execute(
        "SELECT create_hypertable("
        "'telemetry', 'sampled_at', chunk_time_interval => INTERVAL '1 day', migrate_data => true)"
    )


def downgrade() -> None:
    # Converting a hypertable back to a plain table is not practical; roll back by
    # recreating the volume (docker compose down -v) and re-running migrations.
    pass
