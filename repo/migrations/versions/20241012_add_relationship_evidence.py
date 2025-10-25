from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20241012_add_relationship_evidence"
down_revision = "20240915_add_version_to_data_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "relationships",
        sa.Column("inference_status", sa.String(length=50), nullable=False, server_default="manual"),
    )
    op.add_column("relationships", sa.Column("evidence_json", sa.JSON(), nullable=True))
    op.execute(
        """
        UPDATE relationships
        SET inference_status = 'manual'
        WHERE inference_status IS NULL OR inference_status = ''
        """
    )


def downgrade() -> None:
    op.drop_column("relationships", "evidence_json")
    op.drop_column("relationships", "inference_status")
