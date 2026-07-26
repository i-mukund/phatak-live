"""prediction direction/speed + geometry adjustment audit trail

Revision ID: c51f20geocal
Revises: b408056eb34b
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c51f20geocal"
down_revision: str | None = "b408056eb34b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("prediction_records") as batch:
        batch.add_column(
            sa.Column("direction", sa.String(length=10), nullable=False,
                      server_default="unknown")
        )
        batch.add_column(sa.Column("speed_kmph", sa.Float(), nullable=True))

    op.create_table(
        "geometry_adjustments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("crossing_id", sa.Integer(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delta_km", sa.Float(), nullable=False),
        sa.Column("old_distance_from_prev_km", sa.Float(), nullable=False),
        sa.Column("new_distance_from_prev_km", sa.Float(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["crossing_id"], ["crossings.id"], ondelete="CASCADE",
                                name=op.f("fk_geometry_adjustments_crossing_id_crossings")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_geometry_adjustments")),
    )
    op.create_index(op.f("ix_geometry_adjustments_applied_at"),
                    "geometry_adjustments", ["applied_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_geometry_adjustments_applied_at"),
                  table_name="geometry_adjustments")
    op.drop_table("geometry_adjustments")
    with op.batch_alter_table("prediction_records") as batch:
        batch.drop_column("speed_kmph")
        batch.drop_column("direction")
