"""Create the usage_log table.

Revision ID: 0001
Revises:
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_log",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("team", sa.String(100), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("policy", sa.String(20), nullable=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("masked_entities", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(300), nullable=True),
    )
    op.create_index("ix_usage_log_created_at", "usage_log", ["created_at"])
    op.create_index("ix_usage_log_team", "usage_log", ["team"])


def downgrade() -> None:
    op.drop_index("ix_usage_log_team", table_name="usage_log")
    op.drop_index("ix_usage_log_created_at", table_name="usage_log")
    op.drop_table("usage_log")
