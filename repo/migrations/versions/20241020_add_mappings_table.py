"""Add mappings table for attribute to source column planning."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20241020_add_mappings_table"
down_revision = "20241012_add_relationship_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    mapping_status_enum = sa.Enum(
        "draft",
        "approved",
        "rejected",
        name="mapping_status_enum",
    )
    bind = op.get_bind()
    mapping_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "entity_id",
            sa.Integer(),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attribute_id",
            sa.Integer(),
            sa.ForeignKey("attributes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_table_id",
            sa.Integer(),
            sa.ForeignKey("source_tables.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("column_path", sa.String(length=500), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "status",
            mapping_status_enum,
            nullable=False,
            server_default="draft",
        ),
        sa.Column("transforms_json", sa.JSON(), nullable=True),
        sa.Column("join_recipe", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_mappings_entity_attribute",
        "mappings",
        ["entity_id", "attribute_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_mappings_entity_attribute", table_name="mappings")
    op.drop_table("mappings")
    mapping_status_enum = sa.Enum(name="mapping_status_enum")
    mapping_status_enum.drop(op.get_bind(), checkfirst=True)

