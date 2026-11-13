"""Versioned canonical project context and explicit specialist preferences."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade():
    op.add_column("tasks", sa.Column("options", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.String(30000), nullable=False),
        sa.Column("source", sa.String(1000), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "title", "version"),
    )
    op.create_index("ix_knowledge_documents_workspace_id", "knowledge_documents", ["workspace_id"])
    op.create_index("ix_knowledge_documents_project_id", "knowledge_documents", ["project_id"])


def downgrade():
    op.drop_table("knowledge_documents")
    op.drop_column("tasks", "options")
