"""Extend entity metadata with grain and SCD tracking."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20241005_extend_entity_metadata"
down_revision = "20240915_add_version_to_data_models"
branch_labels = None
depends_on = None


SCHEMA_ENUM_VALUES = ("none", "type_0", "type_1", "type_2")


def upgrade() -> None:
    scd_type_enum = sa.Enum(*SCHEMA_ENUM_VALUES, name="scd_type_enum")
    bind = op.get_bind()
    scd_type_enum.create(bind, checkfirst=True)

    with op.batch_alter_table("entities", schema=None) as batch_op:
        batch_op.alter_column("entity_role", new_column_name="role")
        batch_op.add_column(sa.Column("grain_json", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "scd_type",
                scd_type_enum,
                nullable=False,
                server_default="none",
            )
        )

    op.execute(
        sa.text("UPDATE entities SET scd_type = 'none' WHERE scd_type IS NULL")
    )

    with op.batch_alter_table("attributes", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_measure",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "is_surrogate_key",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    op.execute(
        sa.text(
            "UPDATE attributes SET is_measure = 0 WHERE is_measure IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE attributes SET is_surrogate_key = 0 WHERE is_surrogate_key IS NULL"
        )
    )

    with op.batch_alter_table("attributes", schema=None) as batch_op:
        batch_op.alter_column("is_measure", server_default=None)
        batch_op.alter_column("is_surrogate_key", server_default=None)

    with op.batch_alter_table("entities", schema=None) as batch_op:
        batch_op.alter_column("scd_type", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("attributes", schema=None) as batch_op:
        batch_op.drop_column("is_surrogate_key")
        batch_op.drop_column("is_measure")

    with op.batch_alter_table("entities", schema=None) as batch_op:
        batch_op.drop_column("scd_type")
        batch_op.drop_column("grain_json")
        batch_op.alter_column("role", new_column_name="entity_role")

    scd_type_enum = sa.Enum(*SCHEMA_ENUM_VALUES, name="scd_type_enum")
    scd_type_enum.drop(op.get_bind(), checkfirst=True)
