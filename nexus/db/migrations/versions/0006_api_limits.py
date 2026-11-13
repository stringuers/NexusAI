"""Distributed workspace API rate windows."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade():
    op.create_table(
        "api_rate_windows",
        sa.Column("workspace_id", sa.String(36), primary_key=True),
        sa.Column("window", sa.BigInteger(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("api_rate_windows")
