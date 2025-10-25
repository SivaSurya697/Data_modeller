"""Database table models."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for ORM models."""


class Setting(Base):
    """Key/value configuration stored in the database."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Domain(Base):
    """Logical business domain grouping multiple models."""

    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    models: Mapped[list["DataModel"]] = relationship(
        "DataModel", back_populates="domain", cascade="all, delete-orphan"
    )
    entities: Mapped[list["DomainEntity"]] = relationship(
        "DomainEntity", back_populates="domain", cascade="all, delete-orphan"
    )
    source_tables: Mapped[list["SourceTable"]] = relationship(
        "SourceTable", back_populates="domain", cascade="all, delete-orphan"
    )


class DataModel(Base):
    """Model draft generated for a domain."""

    __tablename__ = "data_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    domain: Mapped["Domain"] = relationship("Domain", back_populates="models")
    changesets: Mapped[list["ChangeSet"]] = relationship(
        "ChangeSet", back_populates="model", cascade="all, delete-orphan"
    )
    exports: Mapped[list["ExportRecord"]] = relationship(
        "ExportRecord", back_populates="model", cascade="all, delete-orphan"
    )


class DomainEntity(Base):
    """Entity captured inside a domain."""

    __tablename__ = "domain_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    classification: Mapped[str] = mapped_column(String(50), default="core", nullable=False)
    is_link: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    business_rules: Mapped[str | None] = mapped_column(Text, nullable=True)

    domain: Mapped["Domain"] = relationship("Domain", back_populates="entities")
    attributes: Mapped[list["EntityAttribute"]] = relationship(
        "EntityAttribute", back_populates="entity", cascade="all, delete-orphan"
    )
    outbound_relationships: Mapped[list["EntityRelationship"]] = relationship(
        "EntityRelationship",
        back_populates="parent_entity",
        cascade="all, delete-orphan",
        foreign_keys="EntityRelationship.parent_entity_id",
    )
    inbound_relationships: Mapped[list["EntityRelationship"]] = relationship(
        "EntityRelationship",
        back_populates="child_entity",
        cascade="all, delete-orphan",
        foreign_keys="EntityRelationship.child_entity_id",
    )
    source_links: Mapped[list["EntitySourceLink"]] = relationship(
        "EntitySourceLink", back_populates="entity", cascade="all, delete-orphan"
    )


class EntityAttribute(Base):
    """Attribute describing an entity."""

    __tablename__ = "entity_attributes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("domain_entities.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    data_type: Mapped[str] = mapped_column(String(100), nullable=False)
    is_nullable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_unique: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_primary_key: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    business_rules: Mapped[str | None] = mapped_column(Text, nullable=True)

    entity: Mapped["DomainEntity"] = relationship("DomainEntity", back_populates="attributes")


class EntityRelationship(Base):
    """Relationship between two domain entities."""

    __tablename__ = "entity_relationships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_entity_id: Mapped[int] = mapped_column(
        ForeignKey("domain_entities.id"), nullable=False
    )
    child_entity_id: Mapped[int] = mapped_column(
        ForeignKey("domain_entities.id"), nullable=False
    )
    cardinality: Mapped[str] = mapped_column(String(30), default="many-to-one", nullable=False)
    is_identifying: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_optional: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    business_rules: Mapped[str | None] = mapped_column(Text, nullable=True)

    domain: Mapped["Domain"] = relationship("Domain")
    parent_entity: Mapped["DomainEntity"] = relationship(
        "DomainEntity", foreign_keys=[parent_entity_id], back_populates="outbound_relationships"
    )
    child_entity: Mapped["DomainEntity"] = relationship(
        "DomainEntity", foreign_keys=[child_entity_id], back_populates="inbound_relationships"
    )


class SourceTable(Base):
    """Source system table supporting the model."""

    __tablename__ = "source_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_authoritative: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    refresh_cadence: Mapped[str | None] = mapped_column(String(100), nullable=True)
    business_rules: Mapped[str | None] = mapped_column(Text, nullable=True)

    domain: Mapped["Domain"] = relationship("Domain", back_populates="source_tables")
    entity_links: Mapped[list["EntitySourceLink"]] = relationship(
        "EntitySourceLink", back_populates="source_table", cascade="all, delete-orphan"
    )


class EntitySourceLink(Base):
    """Associates an entity with one of its source tables."""

    __tablename__ = "entity_source_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("domain_entities.id"), nullable=False)
    source_table_id: Mapped[int] = mapped_column(ForeignKey("source_tables.id"), nullable=False)
    is_primary_source: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    business_rules: Mapped[str | None] = mapped_column(Text, nullable=True)

    entity: Mapped["DomainEntity"] = relationship("DomainEntity", back_populates="source_links")
    source_table: Mapped["SourceTable"] = relationship(
        "SourceTable", back_populates="entity_links"
    )
class ChangeSet(Base):
    """Captured change to a generated model."""

    __tablename__ = "changesets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_model_id: Mapped[int] = mapped_column(
        ForeignKey("data_models.id"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    model: Mapped["DataModel"] = relationship("DataModel", back_populates="changesets")


class ExportRecord(Base):
    """Exported assets tied to a model."""

    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_model_id: Mapped[int] = mapped_column(
        ForeignKey("data_models.id"), nullable=False
    )
    exporter: Mapped[str] = mapped_column(String(50), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    model: Mapped["DataModel"] = relationship("DataModel", back_populates="exports")
