"""Database table models aligned with the modelling specification."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.db import Base


class Settings(Base):
    """Per-user application configuration stored securely."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    encrypted_openai_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    openai_base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(Base, TimestampMixin):
    """Application user capable of owning modelling artefacts."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    domains: Mapped[list["Domain"]] = relationship(
        "Domain", back_populates="owner", cascade="all, delete-orphan"
    )
    settings: Mapped[list["Setting"]] = relationship(
        "Setting", back_populates="user", cascade="all, delete-orphan"
    )
    change_sets: Mapped[list["ChangeSet"]] = relationship(
        "ChangeSet", back_populates="author"
    )


class Setting(Base, TimestampMixin):
    """Connection and LLM configuration persisted per user."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    api_key_enc: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (UniqueConstraint("user_id", name="uq_settings_user"),)

    user: Mapped["User" | None] = relationship("User", back_populates="settings")


class Domain(Base, TimestampMixin):
    """Logical business domain grouping entities and relationships."""

    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_domain_owner_name"),)

    owner: Mapped["User" | None] = relationship("User", back_populates="domains")
    entities: Mapped[list["Entity"]] = relationship(
        "Entity", back_populates="domain", cascade="all, delete-orphan"
    )
    relationships: Mapped[list["Relationship"]] = relationship(
        "Relationship", back_populates="domain", cascade="all, delete-orphan"
    )
    source_tables: Mapped[list["SourceTable"]] = relationship(
        "SourceTable", back_populates="domain", cascade="all, delete-orphan"
    )
    change_sets: Mapped[list["ChangeSet"]] = relationship(
        "ChangeSet", back_populates="domain", cascade="all, delete-orphan"
    )
    exports: Mapped[list["ExportRecord"]] = relationship(
        "ExportRecord", back_populates="domain", cascade="all, delete-orphan"
    )
    entities: Mapped[list["DomainEntity"]] = relationship(
        "DomainEntity", back_populates="domain", cascade="all, delete-orphan"
    )
    source_tables: Mapped[list["SourceTable"]] = relationship(
        "SourceTable", back_populates="domain", cascade="all, delete-orphan"
    )


class Entity(Base, TimestampMixin):
    """Entity representing a conceptual dataset in a domain."""

    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    documentation: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("domain_id", "name", name="uq_entity_domain_name"),)

    domain: Mapped["Domain"] = relationship("Domain", back_populates="entities")
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
    change_items: Mapped[list["ChangeItem"]] = relationship(
        "ChangeItem",
        back_populates="entity",
    )


class Attribute(Base, TimestampMixin):
    """Attribute captured for an entity."""

    __tablename__ = "attributes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    data_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_nullable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    default_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("entity_id", "name", name="uq_attribute_entity_name"),)

    entity: Mapped["Entity"] = relationship("Entity", back_populates="attributes")
    mappings: Mapped[list["Mapping"]] = relationship(
        "Mapping", back_populates="attribute", cascade="all, delete-orphan"
    )
    change_items: Mapped[list["ChangeItem"]] = relationship(
        "ChangeItem", back_populates="attribute"
    )


class Relationship(Base, TimestampMixin):
    """Logical relationship between two entities."""

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
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "domain_id",
            "from_entity_id",
            "to_entity_id",
            "relationship_type",
            name="uq_relationship_unique",
        ),
    )

    domain: Mapped["Domain"] = relationship("Domain", back_populates="relationships")
    from_entity: Mapped["Entity"] = relationship(
        "Entity",
        foreign_keys=[from_entity_id],
        back_populates="outbound_relationships",
    )
    to_entity: Mapped["Entity"] = relationship(
        "Entity",
        foreign_keys=[to_entity_id],
        back_populates="inbound_relationships",
    )


class SourceTable(Base, TimestampMixin):
    """Source system table feeding a domain."""

    __tablename__ = "source_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    database_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    schema_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("domain_id", "name", name="uq_source_table_domain_name"),)

    domain: Mapped["Domain"] = relationship("Domain", back_populates="source_tables")
    mappings: Mapped[list["Mapping"]] = relationship(
        "Mapping", back_populates="source_table", cascade="all, delete-orphan"
    )


class Mapping(Base, TimestampMixin):
    """Mapping between attributes and physical source columns."""

    __tablename__ = "mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attribute_id: Mapped[int] = mapped_column(
        ForeignKey("attributes.id", ondelete="CASCADE"), nullable=False
    )
    source_table_id: Mapped[int] = mapped_column(
        ForeignKey("source_tables.id", ondelete="CASCADE"), nullable=False
    )
    source_column: Mapped[str] = mapped_column(String(255), nullable=False)
    transformation: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "attribute_id",
            "source_table_id",
            "source_column",
            name="uq_mapping_unique",
        ),
    )

    attribute: Mapped["Attribute"] = relationship("Attribute", back_populates="mappings")
    source_table: Mapped["SourceTable"] = relationship(
        "SourceTable", back_populates="mappings"
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
    """A collection of change notes for a domain."""

    __tablename__ = "change_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_model_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_models.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="draft"
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    domain: Mapped["Domain"] = relationship("Domain", back_populates="change_sets")
    author: Mapped["User" | None] = relationship("User", back_populates="change_sets")
    items: Mapped[list["ChangeItem"]] = relationship(
        "ChangeItem", back_populates="change_set", cascade="all, delete-orphan"
    )


class ChangeItem(Base):
    """Individual change captured as part of a change set."""

    __tablename__ = "change_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    change_set_id: Mapped[int] = mapped_column(
        ForeignKey("change_sets.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[int | None] = mapped_column(
        ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    attribute_id: Mapped[int | None] = mapped_column(
        ForeignKey("attributes.id", ondelete="SET NULL"), nullable=True
    )
    change_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    previous_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    change_set: Mapped["ChangeSet"] = relationship("ChangeSet", back_populates="items")
    entity: Mapped["Entity" | None] = relationship("Entity", back_populates="change_items")
    attribute: Mapped["Attribute" | None] = relationship(
        "Attribute", back_populates="change_items"
    )


class ExportRecord(Base):
    """Recorded export artefact for a domain."""

    __tablename__ = "export_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    exporter: Mapped[str] = mapped_column(String(50), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    domain: Mapped["Domain"] = relationship("Domain", back_populates="exports")

