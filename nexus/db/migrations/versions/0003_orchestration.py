"""Execution journal, approval binding, artifact and event metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def core():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("workflow_runs.id"), nullable=False),
    ]


def created():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)


def upgrade():
    op.add_column(
        "workflow_runs",
        sa.Column("budget_microusd", sa.BigInteger(), nullable=False, server_default="5000000"),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("reserved_microusd", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_table(
        "agent_executions",
        *core(),
        sa.Column("stage_key", sa.String(100), nullable=False),
        sa.Column("agent", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("reserved_microusd", sa.BigInteger(), nullable=False),
        created(),
        sa.UniqueConstraint("run_id", "stage_key"),
    )
    op.create_table(
        "run_events",
        *core(),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        created(),
        sa.UniqueConstraint("run_id", "sequence"),
    )
    op.create_table(
        "approvals",
        *core(),
        sa.Column("action_hash", sa.String(64), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("decision", sa.String(20)),
        sa.Column("decided_by", sa.String(64)),
        created(),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("run_id", "action_hash"),
    )
    op.create_table(
        "artifacts",
        *core(),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("object_key", sa.String(500), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        created(),
        sa.UniqueConstraint("run_id", "name"),
    )
    for table in ("agent_executions", "run_events", "approvals", "artifacts"):
        for column in ("workspace_id", "run_id"):
            op.create_index(f"ix_{table}_{column}", table, [column])
    op.create_index("ix_artifacts_project_id", "artifacts", ["project_id"])


def downgrade():
    for table in ("artifacts", "approvals", "run_events", "agent_executions"):
        op.drop_table(table)
    op.drop_column("workflow_runs", "reserved_microusd")
    op.drop_column("workflow_runs", "budget_microusd")
