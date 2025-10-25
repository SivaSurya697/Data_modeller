"""Model publication workflow and quality gate enforcement."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from slugify import slugify
from sqlalchemy.orm import Session

from src.models.tables import (
    DataModel,
    Domain,
    Entity,
    EntityRole,
    PublishedModel,
    RelationshipCardinality,
)
from src.services.model_analysis import classify_entity


@dataclass(slots=True)
class QualityGateResult:
    """Represents a single quality gate evaluation."""

    name: str
    passed: bool
    blockers: list[str]

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "passed": self.passed, "blockers": list(self.blockers)}


@dataclass(slots=True)
class PublishPreview:
    """Preview information used by the UI."""

    gates: list[QualityGateResult]
    suggested_tag: str

    @property
    def is_ready(self) -> bool:
        return all(gate.passed for gate in self.gates)

    def to_dict(self) -> dict[str, object]:
        return {
            "gates": [gate.to_dict() for gate in self.gates],
            "suggested_tag": self.suggested_tag,
            "is_ready": self.is_ready,
        }


@dataclass(slots=True)
class PublishResult:
    """Outcome of a successful publication."""

    version_tag: str
    gates: list[QualityGateResult]
    artifacts: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "version_tag": self.version_tag,
            "gates": [gate.to_dict() for gate in self.gates],
            "artifacts": dict(self.artifacts),
        }


class PublishBlocked(RuntimeError):
    """Raised when quality gates prevent publication."""

    def __init__(self, preview: PublishPreview) -> None:
        super().__init__("Model publication blocked by quality gates")
        self.preview = preview


class PublishService:
    """Evaluate quality gates and materialise model artifacts."""

    def __init__(self, artifacts_dir: Path) -> None:
        self._artifacts_dir = artifacts_dir

    def preview(self, domain: Domain) -> PublishPreview:
        model = self._latest_model(domain)
        gates = self._evaluate_gates(domain)
        suggested_tag = self._suggest_tag(domain, model)
        return PublishPreview(gates=gates, suggested_tag=suggested_tag)

    def publish(
        self,
        session: Session,
        domain: Domain,
        *,
        version_tag: str | None = None,
    ) -> PublishResult:
        preview = self.preview(domain)
        if not preview.is_ready:
            raise PublishBlocked(preview)

        model = self._latest_model(domain)
        if model is None:
            raise ValueError("Domain does not have a persisted model to publish.")

        tag = self._ensure_unique_tag(domain, version_tag or preview.suggested_tag)
        version_dir = self._prepare_directory(domain, tag)

        artifacts = {
            "model.json": self._write_model_json(domain, model, tag, version_dir),
            "dictionary.md": self._write_dictionary(domain, version_dir),
            "diagram.puml": self._write_diagram(domain, version_dir),
            "impact_report.md": self._write_impact_report(domain, version_dir),
        }

        self._lock_dimensions(domain)

        report_payload = json.dumps(
            [gate.to_dict() for gate in preview.gates], ensure_ascii=False, indent=2
        )
        publication = PublishedModel(
            domain=domain,
            model=model,
            version_tag=tag,
            artifact_path=str(version_dir),
            quality_report=report_payload,
        )
        session.add(publication)
        session.flush()

        return PublishResult(version_tag=tag, gates=preview.gates, artifacts=artifacts)

    # Helpers -----------------------------------------------------------------

    def _latest_model(self, domain: Domain) -> DataModel | None:
        models: Iterable[DataModel] = getattr(domain, "models", [])
        try:
            return max(models, key=lambda item: item.version)
        except ValueError:
            return None

    def _evaluate_gates(self, domain: Domain) -> list[QualityGateResult]:
        facts = [entity for entity in domain.entities if classify_entity(entity) == "fact"]
        dimensions = [
            entity for entity in domain.entities if classify_entity(entity) == "dimension"
        ]

        gates: list[QualityGateResult] = []
        gates.append(self._gate_fact_completeness(facts))
        gates.append(self._gate_dimension_completeness(dimensions))
        gates.append(self._gate_attribute_coverage(domain.entities))
        gates.append(self._gate_relationship_mappings(domain, facts, dimensions))
        return gates

    def _gate_fact_completeness(self, facts: list[Entity]) -> QualityGateResult:
        blockers: list[str] = []
        if not facts:
            blockers.append("No fact entities identified in the model.")
        for entity in facts:
            if not entity.attributes:
                blockers.append(f"Fact '{entity.name}' has no attributes defined.")
        return QualityGateResult("Fact completeness", not blockers, blockers)

    def _gate_dimension_completeness(self, dimensions: list[Entity]) -> QualityGateResult:
        blockers: list[str] = []
        if not dimensions:
            blockers.append("No dimension entities identified in the model.")
        for entity in dimensions:
            if not entity.attributes:
                blockers.append(f"Dimension '{entity.name}' has no attributes defined.")
            elif not any(not attr.is_nullable for attr in entity.attributes):
                blockers.append(
                    f"Dimension '{entity.name}' must include at least one non-nullable attribute."
                )
        return QualityGateResult("Dimension completeness", not blockers, blockers)

    def _gate_attribute_coverage(self, entities: Iterable[Entity]) -> QualityGateResult:
        blockers: list[str] = []
        for entity in entities:
            if not entity.attributes:
                blockers.append(f"Entity '{entity.name}' lacks attribute coverage.")
            missing_types = [
                attribute.name
                for attribute in entity.attributes
                if not (attribute.data_type or "").strip()
            ]
            if missing_types:
                formatted = ", ".join(sorted(missing_types))
                blockers.append(
                    f"Entity '{entity.name}' is missing data types for: {formatted}."
                )
        return QualityGateResult("Attribute coverage", not blockers, blockers)

    def _gate_relationship_mappings(
        self,
        domain: Domain,
        facts: list[Entity],
        dimensions: list[Entity],
    ) -> QualityGateResult:
        blockers: list[str] = []
        if not domain.relationships:
            blockers.append("No relationships defined in the model.")
        dimension_ids = {entity.id for entity in dimensions}
        for fact in facts:
            related_dimensions = [
                rel
                for rel in domain.relationships
                if (rel.from_entity_id == fact.id and rel.to_entity_id in dimension_ids)
                or (rel.to_entity_id == fact.id and rel.from_entity_id in dimension_ids)
            ]
            if not related_dimensions:
                blockers.append(
                    f"Fact '{fact.name}' must be mapped to at least one dimension relationship."
                )
        return QualityGateResult("Fact-to-dimension mappings", not blockers, blockers)

    def _suggest_tag(self, domain: Domain, model: DataModel | None) -> str:
        base_version = model.version if model else 1
        return f"v{base_version}"

    def _ensure_unique_tag(self, domain: Domain, candidate: str) -> str:
        existing_tags = {pub.version_tag for pub in getattr(domain, "published_models", [])}
        if candidate not in existing_tags:
            return candidate

        index = 2
        while True:
            amended = f"{candidate}-{index}"
            if amended not in existing_tags:
                return amended
            index += 1

    def _prepare_directory(self, domain: Domain, tag: str) -> Path:
        slug = slugify(domain.name) or f"domain-{domain.id}"
        version_dir = self._artifacts_dir / slug / tag
        version_dir.mkdir(parents=True, exist_ok=True)
        return version_dir

    def _write_model_json(
        self, domain: Domain, model: DataModel, tag: str, version_dir: Path
    ) -> str:
        payload = {
            "domain": {"id": domain.id, "name": domain.name, "description": domain.description},
            "model": {
                "id": model.id,
                "name": model.name,
                "summary": model.summary,
                "definition": model.definition,
                "version": model.version,
                "tag": tag,
            },
            "entities": [
                {
                    "id": entity.id,
                    "name": entity.name,
                    "description": entity.description,
                    "documentation": entity.documentation,
                    "classification": classify_entity(entity),
                    "is_locked": entity.is_locked,
                    "attributes": [
                        {
                            "id": attribute.id,
                            "name": attribute.name,
                            "data_type": attribute.data_type,
                            "is_nullable": attribute.is_nullable,
                            "description": attribute.description,
                        }
                        for attribute in sorted(
                            entity.attributes, key=lambda item: item.name.lower()
                        )
                    ],
                }
                for entity in sorted(domain.entities, key=lambda item: item.name.lower())
            ],
            "relationships": [
                {
                    "id": relationship.id,
                    "from": relationship.from_entity.name,
                    "to": relationship.to_entity.name,
                    "type": relationship.relationship_type,
                    "description": relationship.description,
                    "cardinality_from": relationship.cardinality_from.value,
                    "cardinality_to": relationship.cardinality_to.value,
                }
                for relationship in sorted(
                    domain.relationships,
                    key=lambda rel: (
                        rel.from_entity.name.lower(),
                        rel.to_entity.name.lower(),
                        rel.relationship_type or "",
                    ),
                )
            ],
        }
        output_path = version_dir / "model.json"
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(output_path)

    def _write_dictionary(self, domain: Domain, version_dir: Path) -> str:
        lines = [f"# {domain.name} Data Dictionary\n\n", f"Domain description: {domain.description}\n\n"]
        entities = sorted(domain.entities, key=lambda item: item.name.lower())
        if entities:
            for entity in entities:
                lines.append(f"## {entity.name}\n\n")
                if entity.description:
                    lines.append(f"{entity.description}\n\n")
                if entity.documentation:
                    lines.append(f"{entity.documentation}\n\n")
                if entity.attributes:
                    lines.append("| Attribute | Type | Nullable | Description |\n")
                    lines.append("| --- | --- | --- | --- |\n")
                    for attribute in sorted(entity.attributes, key=lambda item: item.name.lower()):
                        data_type = attribute.data_type or "unspecified"
                        nullable = "Yes" if attribute.is_nullable else "No"
                        description = attribute.description or ""
                        lines.append(
                            f"| {attribute.name} | {data_type} | {nullable} | {description} |\n"
                        )
                    lines.append("\n")
        else:
            lines.append("No entities defined for this domain yet.\n")

        output_path = version_dir / "dictionary.md"
        output_path.write_text("".join(lines), encoding="utf-8")
        return str(output_path)

    def _write_diagram(self, domain: Domain, version_dir: Path) -> str:
        title = f"{domain.name} ({self._suggest_title_version(domain)})"
        lines = ["@startuml", "skinparam classAttributeIconSize 0", f"title {title}"]

        entities = sorted(domain.entities, key=lambda item: item.name.lower())
        for entity in entities:
            stereotype = self._stereotype(entity)
            lines.append(self._render_entity_block(entity, stereotype))

        for relationship in sorted(
            domain.relationships,
            key=lambda rel: (
                rel.from_entity.name.lower(),
                rel.to_entity.name.lower(),
                rel.relationship_type or "",
            ),
        ):
            left = slugify(relationship.from_entity.name, separator="_") or f"entity_{relationship.from_entity.id}"
            right = slugify(relationship.to_entity.name, separator="_") or f"entity_{relationship.to_entity.id}"
            label = (relationship.relationship_type or "relates to").strip()
            left_cardinality = self._render_cardinality(relationship.cardinality_from)
            right_cardinality = self._render_cardinality(relationship.cardinality_to)

            relationship_line = left
            if left_cardinality:
                relationship_line += f' "{left_cardinality}"'
            relationship_line += " -->"
            if right_cardinality:
                relationship_line += f' "{right_cardinality}" {right}'
            else:
                relationship_line += f" {right}"
            if label:
                relationship_line += f" : {label}"
            lines.append(relationship_line)
        lines.append("@enduml")

        output_path = version_dir / "diagram.puml"
        output_path.write_text("\n".join(lines), encoding="utf-8")
        return str(output_path)

    def _write_impact_report(self, domain: Domain, version_dir: Path) -> str:
        lines = [f"# Impact assessment for {domain.name}\n\n"]
        tasks = sorted(domain.created_review_tasks, key=lambda item: item.created_at)
        if tasks:
            lines.append("## Generated review tasks\n\n")
            for task in tasks:
                lines.append(f"- **{task.title}** → {task.target_domain.name}: {task.details}\n")
        else:
            lines.append("No outstanding review tasks recorded for this domain.\n")

        output_path = version_dir / "impact_report.md"
        output_path.write_text("".join(lines), encoding="utf-8")
        return str(output_path)

    def _lock_dimensions(self, domain: Domain) -> None:
        for entity in domain.entities:
            classification = classify_entity(entity)
            if classification == "dimension":
                entity.is_locked = True
                if entity.entity_role == EntityRole.UNKNOWN:
                    entity.entity_role = EntityRole.DIMENSION

    def _stereotype(self, entity: Entity) -> str | None:
        classification = classify_entity(entity)
        if classification == "fact":
            return "Fact"
        if classification == "dimension":
            return "Dimension"
        return None

    def _render_entity_block(self, entity: Entity, stereotype: str | None) -> str:
        class_name = slugify(entity.name, separator="_") or f"entity_{entity.id}"
        header = f"class {class_name}"
        if stereotype:
            header += f" <<{stereotype}>>"
        block_lines = [header + " {"]
        if entity.description:
            for line in entity.description.splitlines():
                block_lines.append(f"  ' {line}")
        for attribute in sorted(entity.attributes, key=lambda item: item.name.lower()):
            data_type = attribute.data_type or "unspecified"
            nullable = "?" if attribute.is_nullable else "!"
            block_lines.append(f"  {attribute.name}: {data_type} {nullable}")
        block_lines.append("}")
        return "\n".join(block_lines)

    def _suggest_title_version(self, domain: Domain) -> str:
        publication_versions = [pub.version_tag for pub in getattr(domain, "published_models", [])]
        if publication_versions:
            return publication_versions[-1]
        latest = self._latest_model(domain)
        return f"v{latest.version}" if latest else "unversioned"

    @staticmethod
    def _render_cardinality(cardinality: RelationshipCardinality) -> str | None:
        if not isinstance(cardinality, RelationshipCardinality):
            return None
        if cardinality in {RelationshipCardinality.UNKNOWN}:  # pragma: no cover - defensive
            return None
        value = getattr(cardinality, "value", None)
        if not value or value == RelationshipCardinality.UNKNOWN.value:
            return None
        return value


__all__ = [
    "PublishBlocked",
    "PublishPreview",
    "PublishResult",
    "PublishService",
    "QualityGateResult",
]
