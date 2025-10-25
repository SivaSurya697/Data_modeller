"""Service helpers for managing source systems and profiling metadata."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import fmean
from typing import Any, Callable, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from src.models.tables import SourceColumn, SourceSystem, SourceTable


def _normalise_identifier(value: str) -> str:
    """Normalise identifiers for comparison purposes."""

    return value.strip().lower()


def _serialise_sample(value: Any) -> Any:
    """Return a JSON serialisable representation of a sample value."""

    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def _coerce_numeric(value: Any) -> float | None:
    """Coerce values to ``float`` when possible for statistics calculations."""

    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _coerce_datetime(value: Any) -> datetime | None:
    """Best-effort conversion of ISO formatted strings to datetimes."""

    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            # ``fromisoformat`` returns naive datetimes when no timezone is present.
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return None
    return None


class SourceRegistryService:
    """Persist and profile source metadata."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        return self._clock()

    def list_systems(self, session: Session) -> list[SourceSystem]:
        """Return all registered source systems with eager relationships."""

        stmt = (
            select(SourceSystem)
            .options(joinedload(SourceSystem.tables).joinedload(SourceTable.columns))
            .order_by(SourceSystem.name)
        )
        return list(session.execute(stmt).unique().scalars())

    def import_source(self, session: Session, payload: dict[str, Any]) -> SourceSystem:
        """Create or update a source system from the provided payload."""

        system_data = payload.get("system", {})
        if not system_data:
            raise ValueError("Import payload is missing system details")

        name = system_data["name"].strip()
        stmt = select(SourceSystem).where(SourceSystem.name == name)
        system = session.execute(stmt).scalar_one_or_none()
        if system is None:
            system = SourceSystem(name=name)
            session.add(system)

        if "description" in system_data:
            system.description = system_data.get("description")
        if "connection_type" in system_data:
            system.connection_type = system_data.get("connection_type", "unknown")
        if "connection_config" in system_data:
            system.connection_config = system_data.get("connection_config")
        system.last_imported_at = self._now()

        existing_tables: dict[tuple[str, str], SourceTable] = {
            (
                _normalise_identifier(table.schema_name),
                _normalise_identifier(table.table_name),
            ): table
            for table in system.tables
        }

        seen_tables: set[tuple[str, str]] = set()

        for table_data in payload.get("tables", []):
            schema_name = table_data.get("schema_name", "public")
            table_name = table_data.get("table_name")
            if not table_name:
                raise ValueError("Table entries must include a table_name")

            key = (
                _normalise_identifier(schema_name),
                _normalise_identifier(table_name),
            )
            seen_tables.add(key)

            table = existing_tables.get(key)
            if table is None:
                table = SourceTable(
                    schema_name=schema_name,
                    table_name=table_name,
                )
                system.tables.append(table)

            if "display_name" in table_data:
                table.display_name = table_data.get("display_name")
            if "description" in table_data:
                table.description = table_data.get("description")
            if "schema" in table_data:
                table.schema_definition = table_data.get("schema")
            if "schema_definition" in table_data:
                table.schema_definition = table_data.get("schema_definition")
            if "statistics" in table_data:
                table.table_statistics = table_data.get("statistics")
            if "table_statistics" in table_data:
                table.table_statistics = table_data.get("table_statistics")
            if "row_count" in table_data:
                table.row_count = table_data.get("row_count")
            if "sampled_row_count" in table_data:
                table.sampled_row_count = table_data.get("sampled_row_count")
            if "profiled_at" in table_data:
                table.profiled_at = _coerce_datetime(table_data.get("profiled_at"))

            existing_columns: dict[str, SourceColumn] = {
                _normalise_identifier(column.name): column for column in table.columns
            }
            seen_columns: set[str] = set()

            for idx, column_data in enumerate(table_data.get("columns", []), start=1):
                column_name = column_data.get("name")
                if not column_name:
                    raise ValueError("Column entries must include a name")

                column_key = _normalise_identifier(column_name)
                seen_columns.add(column_key)

                column = existing_columns.get(column_key)
                if column is None:
                    column = SourceColumn(name=column_name)
                    table.columns.append(column)

                if "data_type" in column_data:
                    column.data_type = column_data.get("data_type")
                if "is_nullable" in column_data:
                    column.is_nullable = bool(column_data.get("is_nullable"))
                elif column.is_nullable is None:
                    column.is_nullable = True
                position = column_data.get("ordinal_position")
                if position is not None:
                    column.ordinal_position = position
                elif column.ordinal_position is None:
                    column.ordinal_position = idx
                if "description" in column_data:
                    column.description = column_data.get("description")
                if "statistics" in column_data:
                    column.statistics = column_data.get("statistics")
                if "sample_values" in column_data:
                    samples = column_data.get("sample_values")
                    column.sample_values = (
                        [_serialise_sample(value) for value in samples]
                        if samples is not None
                        else None
                    )

            for column_key, column in list(existing_columns.items()):
                if column_key not in seen_columns:
                    table.columns.remove(column)

        for key, table in list(existing_tables.items()):
            if key not in seen_tables:
                system.tables.remove(table)

        session.flush()
        return system

    def profile_table(
        self,
        session: Session,
        table_id: int,
        samples: Iterable[dict[str, Any]],
        total_rows: int | None = None,
    ) -> SourceTable:
        """Update profiling statistics for the given table."""

        table = session.get(SourceTable, table_id)
        if table is None:
            raise LookupError(f"Source table {table_id} was not found")

        sample_list = list(samples)
        now = self._now()
        table.profiled_at = now
        table.sampled_row_count = len(sample_list)
        if total_rows is not None:
            table.row_count = total_rows

        table_stats = {
            "profiled_at": now.isoformat(),
            "sampled_row_count": len(sample_list),
            "columns_profiled": len(table.columns),
        }
        if table.row_count is not None:
            table_stats["row_count"] = table.row_count
        table.table_statistics = table_stats

        column_samples: dict[str, list[Any]] = defaultdict(list)
        for row in sample_list:
            for column in table.columns:
                column_samples[column.name].append(row.get(column.name))

        for column in table.columns:
            values = column_samples.get(column.name, [])
            column.statistics = self._build_column_statistics(values)
            column.sample_values = [
                _serialise_sample(value) for value in values[:5]
            ] or None

        session.flush()
        return table

    def _build_column_statistics(self, values: list[Any]) -> dict[str, Any]:
        """Return aggregate statistics for the provided values."""

        total = len(values)
        nulls = sum(1 for value in values if value is None)
        non_null = [value for value in values if value is not None]
        distinct = len({repr(value) for value in non_null})

        stats: dict[str, Any] = {
            "total": total,
            "nulls": nulls,
            "distinct": distinct,
        }

        numeric_values = [
            value
            for value in (_coerce_numeric(item) for item in non_null)
            if value is not None
        ]
        if numeric_values:
            stats.update(
                {
                    "min": min(numeric_values),
                    "max": max(numeric_values),
                    "avg": fmean(numeric_values),
                }
            )

        try:
            if non_null and len(non_null) != len(set(non_null)):
                stats["mode"] = max(
                    set(non_null), key=lambda item: non_null.count(item)
                )
        except TypeError:
            # Non-hashable values (e.g. dicts) cannot be counted using ``set``.
            pass

        return stats


__all__ = ["SourceRegistryService"]
