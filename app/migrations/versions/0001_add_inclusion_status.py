"""Add synthesis inclusion status.

Revision ID: 0001_inclusion_status
Revises: 0000_legacy_baseline
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_inclusion_status"
down_revision = "0000_legacy_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("synthesis_item")}
    if "inclusion_status" not in columns:
        op.add_column(
            "synthesis_item",
            sa.Column(
                "inclusion_status",
                sa.String(length=40),
                nullable=False,
                server_default="included",
            ),
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("synthesis_item")}
    if "inclusion_status" in columns:
        with op.batch_alter_table("synthesis_item") as batch_op:
            batch_op.drop_column("inclusion_status")
