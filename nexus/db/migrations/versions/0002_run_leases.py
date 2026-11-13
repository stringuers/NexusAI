"""Durable worker leases and safe status reasons."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    op.add_column("workflow_runs", sa.Column("lease_token", sa.String(36)))
    op.add_column("workflow_runs", sa.Column("lease_expires_at", sa.BigInteger()))
    op.add_column(
        "workflow_runs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("workflow_runs", sa.Column("status_reason", sa.String(200)))
    op.create_index("ix_runs_recovery", "workflow_runs", ["status", "lease_expires_at"])


def downgrade():
    op.drop_index("ix_runs_recovery", table_name="workflow_runs")
    for column in ("status_reason", "attempt_count", "lease_expires_at", "lease_token"):
        op.drop_column("workflow_runs", column)
