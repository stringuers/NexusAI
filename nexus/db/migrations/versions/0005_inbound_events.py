"""Durable authenticated webhook deduplication."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade():
    op.create_table(
        "inbound_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(100), nullable=False),
        sa.Column("body_hash", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("workflow_runs.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source", "event_id"),
    )


def downgrade():
    op.drop_table("inbound_events")
