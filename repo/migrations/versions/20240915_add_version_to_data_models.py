"""Add version column to data_models."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20240915_add_version_to_data_models"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("data_models", sa.Column("version", sa.Integer(), nullable=True))

    data_models = sa.table(
        "data_models",
        sa.column("id", sa.Integer()),
        sa.column("domain_id", sa.Integer()),
        sa.column("created_at", sa.DateTime()),
        sa.column("version", sa.Integer()),
    )

    bind = op.get_bind()
    result = bind.execute(
        sa.select(data_models.c.id, data_models.c.domain_id)
        .order_by(data_models.c.domain_id, data_models.c.created_at, data_models.c.id)
    )

    counters: dict[int, int] = {}
    for row in result:
        domain_id = int(row.domain_id)
        counters[domain_id] = counters.get(domain_id, 0) + 1
        bind.execute(
            sa.update(data_models)
            .where(data_models.c.id == int(row.id))
            .values(version=counters[domain_id])
        )

    bind.execute(sa.text("UPDATE data_models SET version = 1 WHERE version IS NULL"))

    op.alter_column("data_models", "version", existing_type=sa.Integer(), nullable=False)
    op.create_unique_constraint(
        "uq_data_model_domain_version", "data_models", ["domain_id", "version"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_data_model_domain_version", "data_models", type_="unique")
    op.drop_column("data_models", "version")

