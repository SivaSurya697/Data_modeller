"""Database table models."""
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


class Domain(Base):
    """Logical business domain grouping multiple models."""

    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    models: Mapped[list["DataModel"]] = relationship(
        "DataModel", back_populates="domain", cascade="all, delete-orphan"
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


class ChangeSet(Base):
    """Captured change to a generated model."""

    __tablename__ = "changesets"

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
