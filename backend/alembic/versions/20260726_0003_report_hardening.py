"""crowd report hardening: ip_hash for rate limiting

Revision ID: d72a10reports
Revises: c51f20geocal
Create Date: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d72a10reports"
down_revision: str | None = "c51f20geocal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("gate_reports") as batch:
        batch.add_column(sa.Column("ip_hash", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_gate_reports_ip_hash"), "gate_reports", ["ip_hash"])
    op.create_index(op.f("ix_gate_reports_client_hash"), "gate_reports", ["client_hash"])


def downgrade() -> None:
    op.drop_index(op.f("ix_gate_reports_client_hash"), table_name="gate_reports")
    op.drop_index(op.f("ix_gate_reports_ip_hash"), table_name="gate_reports")
    with op.batch_alter_table("gate_reports") as batch:
        batch.drop_column("ip_hash")
