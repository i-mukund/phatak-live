"""persist whether a closure window came from fallback data

Revision ID: e83b41degraded
Revises: d72a10reports
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e83b41degraded"
down_revision: str | None = "d72a10reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("closure_windows") as batch:
        batch.add_column(
            sa.Column(
                "degraded", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("closure_windows") as batch:
        batch.drop_column("degraded")
