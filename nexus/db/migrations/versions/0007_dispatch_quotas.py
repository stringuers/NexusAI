"""Atomic project and daily dispatch reservation caps."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade():
    op.add_column(
        "projects",
        sa.Column("budget_microusd", sa.BigInteger(), nullable=False, server_default="100000000"),
    )
    op.create_table(
        "dispatch_budgets",
        sa.Column("workspace_id", sa.String(36), primary_key=True),
        sa.Column("scope", sa.String(80), primary_key=True),
        sa.Column("period", sa.BigInteger(), primary_key=True),
        sa.Column("reserved_microusd", sa.BigInteger(), nullable=False),
    )


def downgrade():
    op.drop_table("dispatch_budgets")
    op.drop_column("projects", "budget_microusd")
