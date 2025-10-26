"""ORM models used by the application.

The previous repository state contained partially merged model definitions
which resulted in duplicate classes, missing imports, and invalid SQLAlchemy
relationships.  The re-implementation below captures the schema documented in
``ARCHITECTURE.md`` while keeping the model surface area intentionally small so
that the blueprints and services can rely on a predictable API.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.db import Base


class TimestampMixin:
    """Provide timestamp columns shared by most tables."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Settings(Base, TimestampMixin):
    """Per-user application configuration persisted in the database."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    encrypted_openai_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    openai_base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False)


class Domain(Base, TimestampMixin):
    """Business domain grouping data models and the latest entity snapshot."""

    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="draft", server_default="draft"
    )

    models: Mapped[list["DataModel"]] = relationship(
        "DataModel",
        back_populates="domain",
        cascade="all, delete-orphan",
        order_by="DataModel.version",
    )
    entities: Mapped[list["Entity"]] = relationship(
        "Entity", back_populates="domain", cascade="all, delete-orphan"
    )
    relationships: Mapped[list["Relationship"]] = relationship(
        "Relationship", back_populates="domain", cascade="all, delete-orphan"
    )
    change_sets: Mapped[list["ChangeSet"]] = relationship(
        "ChangeSet", back_populates="domain", cascade="all, delete-orphan"
    )
    exports: Mapped[list["ExportRecord"]] = relationship(
        "ExportRecord", back_populates="domain", cascade="all, delete-orphan"
    )
    created_review_tasks: Mapped[list["ReviewTask"]] = relationship(
        "ReviewTask",
        back_populates="source_domain",
        cascade="all, delete-orphan",
        foreign_keys="ReviewTask.source_domain_id",
    )
    assigned_review_tasks: Mapped[list["ReviewTask"]] = relationship(
        "ReviewTask",
        back_populates="target_domain",
        foreign_keys="ReviewTask.target_domain_id",
    )


class DataModel(Base, TimestampMixin):
    """Model draft persisted for a domain."""

    __tablename__ = "data_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("domain_id", "version", name="uq_data_model_domain_version"),
    )

    domain: Mapped[Domain] = relationship("Domain", back_populates="models")


class EntityRole(str, Enum):
    """Supported roles for entities within a dimensional model."""

    FACT = "fact"
    DIMENSION = "dimension"
    BRIDGE = "bridge"
    UNKNOWN = "unknown"


class SCDType(str, Enum):
    """Slowly changing dimension strategies supported by the modeller."""

    NONE = "none"
    TYPE_0 = "type_0"
    TYPE_1 = "type_1"
    TYPE_2 = "type_2"


class Entity(Base, TimestampMixin):
    """Entity representing a conceptual object within a domain."""

    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    documentation: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[EntityRole] = mapped_column(
        SAEnum(EntityRole, name="entity_role_enum", validate_strings=True),
        nullable=False,
        default=EntityRole.UNKNOWN,
        server_default=EntityRole.UNKNOWN.value,
    )
    grain_json: Mapped[list[str] | dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    scd_type: Mapped[SCDType] = mapped_column(
        SAEnum(SCDType, name="scd_type_enum", validate_strings=True),
        nullable=False,
        default=SCDType.NONE,
        server_default=SCDType.NONE.value,
    )

    __table_args__ = (UniqueConstraint("domain_id", "name", name="uq_entity_domain_name"),)

    domain: Mapped[Domain] = relationship("Domain", back_populates="entities")
    attributes: Mapped[list["Attribute"]] = relationship(
        "Attribute", back_populates="entity", cascade="all, delete-orphan"
    )
    outbound_relationships: Mapped[list["Relationship"]] = relationship(
        "Relationship",
        back_populates="from_entity",
        foreign_keys="Relationship.from_entity_id",
        cascade="all, delete-orphan",
    )
    inbound_relationships: Mapped[list["Relationship"]] = relationship(
        "Relationship",
        back_populates="to_entity",
        foreign_keys="Relationship.to_entity_id",
    )


class Attribute(Base, TimestampMixin):
    """Attribute belonging to an entity."""

    __tablename__ = "attributes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    data_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_nullable: Mapped[bool] = mapped_column(default=True, nullable=False)
    default_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_measure: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_surrogate_key: Mapped[bool] = mapped_column(default=False, nullable=False)

    __table_args__ = (UniqueConstraint("entity_id", "name", name="uq_attribute_entity_name"),)

    entity: Mapped[Entity] = relationship("Entity", back_populates="attributes")


class RelationshipCardinality(str, Enum):
    """Supported relationship cardinalities."""

    ONE = "one"
    MANY = "many"
    ZERO_OR_ONE = "zero_or_one"
    ZERO_OR_MANY = "zero_or_many"
    UNKNOWN = "unknown"


class Relationship(Base, TimestampMixin):
    """Relationship between two entities in the same domain."""

    __tablename__ = "relationships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    from_entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    to_entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cardinality_from: Mapped[RelationshipCardinality] = mapped_column(
        SAEnum(
            RelationshipCardinality,
            name="relationship_cardinality_enum",
            validate_strings=True,
        ),
        nullable=False,
        default=RelationshipCardinality.UNKNOWN,
        server_default=RelationshipCardinality.UNKNOWN.value,
    )
    cardinality_to: Mapped[RelationshipCardinality] = mapped_column(
        SAEnum(
            RelationshipCardinality,
            name="relationship_cardinality_enum",
            validate_strings=True,
        ),
        nullable=False,
        default=RelationshipCardinality.UNKNOWN,
        server_default=RelationshipCardinality.UNKNOWN.value,
    )
    inference_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="manual", server_default="manual"
    )
    evidence_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "domain_id",
            "from_entity_id",
            "to_entity_id",
            "relationship_type",
            name="uq_relationship_unique",
        ),
    )

    domain: Mapped[Domain] = relationship("Domain", back_populates="relationships")
    from_entity: Mapped[Entity] = relationship(
        "Entity", foreign_keys=[from_entity_id], back_populates="outbound_relationships"
    )
    to_entity: Mapped[Entity] = relationship(
        "Entity", foreign_keys=[to_entity_id], back_populates="inbound_relationships"
    )


class ChangeSet(Base, TimestampMixin):
    """Human-authored notes describing recent domain changes."""

    __tablename__ = "change_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    data_model_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_models.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(String(255), nullable=False, default="system")

    domain: Mapped[Domain] = relationship("Domain", back_populates="change_sets")
    model: Mapped[DataModel | None] = relationship("DataModel")


class ReviewTask(Base, TimestampMixin):
    """Cross-domain review task generated by impact analysis."""

    __tablename__ = "review_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_domain_id: Mapped[int] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    target_domain_id: Mapped[int] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")

    source_domain: Mapped[Domain] = relationship(
        "Domain",
        foreign_keys=[source_domain_id],
        back_populates="created_review_tasks",
    )
    target_domain: Mapped[Domain] = relationship(
        "Domain",
        foreign_keys=[target_domain_id],
        back_populates="assigned_review_tasks",
    )


class ExportRecord(Base, TimestampMixin):
    """Metadata about generated export files."""

    __tablename__ = "export_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    exporter: Mapped[str] = mapped_column(String(50), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)

    domain: Mapped[Domain] = relationship("Domain", back_populates="exports")


class SourceSystem(Base, TimestampMixin):
    """Physical system that exposes one or more source tables."""

    __tablename__ = "source_systems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    connection_type: Mapped[str] = mapped_column(String(100), nullable=False)
    connection_config: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    last_imported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tables: Mapped[list["SourceTable"]] = relationship(
        "SourceTable",
        back_populates="system",
        cascade="all, delete-orphan",
        order_by="SourceTable.table_name",
    )


class SourceTable(Base, TimestampMixin):
    """Table or view discovered from a source system."""

    __tablename__ = "source_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    system_id: Mapped[int] = mapped_column(
        ForeignKey("source_systems.id", ondelete="CASCADE"), nullable=False
    )
    schema_name: Mapped[str] = mapped_column(String(255), nullable=False)
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_definition: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    table_statistics: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sampled_row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profiled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "system_id",
            "schema_name",
            "table_name",
            name="uq_source_table_identity",
        ),
    )

    system: Mapped[SourceSystem] = relationship("SourceSystem", back_populates="tables")
    columns: Mapped[list["SourceColumn"]] = relationship(
        "SourceColumn",
        back_populates="table",
        cascade="all, delete-orphan",
        order_by="SourceColumn.ordinal_position",
    )


class SourceColumn(Base, TimestampMixin):
    """Column captured during source import or profiling."""

    __tablename__ = "source_columns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_id: Mapped[int] = mapped_column(
        ForeignKey("source_tables.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    data_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_nullable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ordinal_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    statistics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    sample_values: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("table_id", "name", name="uq_source_column_identity"),
    )

    table: Mapped[SourceTable] = relationship("SourceTable", back_populates="columns")


class MappingStatus(str, Enum):
    """Lifecycle states for attribute-to-source column mappings."""

    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"


class Mapping(Base, TimestampMixin):
    """Candidate or approved attribute mapping to a physical source column."""

    __tablename__ = "mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    attribute_id: Mapped[int] = mapped_column(
        ForeignKey("attributes.id", ondelete="CASCADE"), nullable=False
    )
    source_table_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_tables.id", ondelete="SET NULL"), nullable=True
    )
    column_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[MappingStatus] = mapped_column(
        SAEnum(MappingStatus, name="mapping_status_enum", validate_strings=True),
        nullable=False,
        default=MappingStatus.DRAFT,
        server_default=MappingStatus.DRAFT.value,
    )
    transforms_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    join_recipe: Mapped[str | None] = mapped_column(Text, nullable=True)

    entity: Mapped[Entity] = relationship("Entity")
    attribute: Mapped[Attribute] = relationship("Attribute")
    source_table: Mapped[SourceTable | None] = relationship("SourceTable")


__all__ = [
    "Attribute",
    "ChangeSet",
    "DataModel",
    "Domain",
    "Entity",
    "EntityRole",
    "ExportRecord",
    "Mapping",
    "MappingStatus",
    "SourceColumn",
    "SourceSystem",
    "SourceTable",
    "Relationship",
    "ReviewTask",
    "SCDType",
    "Settings",
]

