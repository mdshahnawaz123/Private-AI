"""
Engineering Knowledge Hub — the long-term core of the platform.

The LLM is NOT the knowledge database. The LLM is a reasoning layer
over the Engineering Knowledge Hub.

This module provides:
- Structured entity storage and retrieval
- Knowledge graph navigation
- Provenance tracking
- Source precedence management
- Requirement management
- Evidence management
"""
import json
import datetime
from typing import List, Optional, Dict, Any, Tuple

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()

from knowledge.entities import (
    EntityType, ConfidenceLevel, Provenance,
    EngineeringEntity, RequirementEntity, EvidenceEntity,
    BIMElementEntity, DrawingEntity, ScheduleEntity, Relationship,
)
from knowledge.graph import KnowledgeGraph, GraphNode, GraphEdge
from knowledge.provenance import get_tracker
from knowledge.precedence import get_precedence


class KnowledgeHub:
    """
    The Engineering Knowledge Hub.

    Central access point for all structured engineering knowledge.
    Provides entity storage, retrieval, graph navigation, and provenance.
    """

    def __init__(self):
        self._graph = KnowledgeGraph()
        self._provenance = get_tracker()
        self._precedence = get_precedence()
        self._entities: Dict[str, EngineeringEntity] = {}

    # ── Entity management ─────────────────────────────────────

    def add_entity(self, entity: EngineeringEntity) -> str:
        """Add an entity to the hub."""
        self._entities[entity.entity_id] = entity

        # Also add to graph
        node = GraphNode(
            node_id=entity.entity_id,
            node_type=entity.entity_type.value,
            name=entity.name,
            properties=entity.properties,
            project_id=entity.project_id,
        )
        self._graph.add_node(node)

        logger.info("Added entity: id={} type={} name={}",
                    entity.entity_id, entity.entity_type.value, entity.name)
        return entity.entity_id

    def get_entity(self, entity_id: str) -> Optional[EngineeringEntity]:
        """Get an entity by ID."""
        return self._entities.get(entity_id)

    def find_entities(self, entity_type: EntityType = None,
                      project_id: str = "",
                      filters: Dict[str, Any] = None) -> List[EngineeringEntity]:
        """Find entities by type, project, and filters."""
        results = []
        for entity in self._entities.values():
            if entity_type and entity.entity_type != entity_type:
                continue
            if project_id and entity.project_id != project_id:
                continue
            if filters:
                match = True
                for key, value in filters.items():
                    if entity.properties.get(key) != value:
                        match = False
                        break
                if not match:
                    continue
            results.append(entity)
        return results

    def update_entity(self, entity_id: str, **kwargs) -> bool:
        """Update an entity's properties."""
        entity = self._entities.get(entity_id)
        if not entity:
            return False
        for key, value in kwargs.items():
            if hasattr(entity, key):
                setattr(entity, key, value)
            else:
                entity.properties[key] = value
        entity.updated_at = datetime.datetime.utcnow().isoformat()
        return True

    # ── Relationship management ───────────────────────────────

    def add_relationship(self, src_id: str, relation: str, dst_id: str,
                         src_type: EntityType = None, dst_type: EntityType = None,
                         confidence: float = 0.0) -> bool:
        """Add a relationship between two entities."""
        src = self._entities.get(src_id)
        dst = self._entities.get(dst_id)
        if not src or not dst:
            logger.warning("Cannot add relationship: entity not found")
            return False

        edge = GraphEdge(
            src_id=src_id,
            src_type=src_type.value if src_type else src.entity_type.value,
            relation=relation,
            dst_id=dst_id,
            dst_type=dst_type.value if dst_type else dst.entity_type.value,
            confidence=confidence,
        )
        self._graph.add_edge(edge)
        return True

    def get_relationships(self, entity_id: str, relation: str = "",
                          direction: str = "out") -> List[Dict[str, Any]]:
        """Get relationships for an entity."""
        if direction == "out":
            edges = self._graph.get_edges_from(entity_id, relation)
            return [{"relation": e.relation, "target_id": e.dst_id,
                     "target_type": e.dst_type, "confidence": e.confidence}
                    for e in edges]
        else:
            edges = self._graph.get_edges_to(entity_id, relation)
            return [{"relation": e.relation, "source_id": e.src_id,
                     "source_type": e.src_type, "confidence": e.confidence}
                    for e in edges]

    # ── Requirement management ────────────────────────────────

    def add_requirement(self, project_id: str, req_id: str, title: str,
                        value: float = None, unit: str = "",
                        operator: str = "", applies_to: str = "",
                        discipline: str = "", code_reference: str = "",
                        source_doc: str = "", source_page: int = None,
                        source_clause: str = "", confidence: str = "medium",
                        notes: str = "") -> str:
        """Add a code requirement to the hub."""
        entity = RequirementEntity(
            entity_id=f"req-{req_id}",
            entity_type=EntityType.REQUIREMENT,
            project_id=project_id,
            name=title,
            description=notes,
            requirement_id=req_id,
            value=value,
            unit=unit,
            operator=operator,
            applies_to=applies_to,
            discipline=discipline,
            code_reference=code_reference,
            provenance=self._provenance.create(
                source_doc=source_doc,
                source_page=source_page,
                source_clause=source_clause,
                source_type="code",
                extraction_method="native_text",
                confidence=confidence,
            ),
        )
        return self.add_entity(entity)

    def get_requirements(self, project_id: str = "",
                         discipline: str = "",
                         applies_to: str = "") -> List[RequirementEntity]:
        """Get requirements filtered by project, discipline, and applies_to."""
        results = []
        for entity in self._entities.values():
            if entity.entity_type != EntityType.REQUIREMENT:
                continue
            if project_id and entity.project_id != project_id:
                continue
            if discipline and entity.properties.get("discipline") != discipline:
                continue
            if applies_to and entity.properties.get("applies_to") != applies_to:
                continue
            results.append(entity)
        return results

    def find_requirement(self, query: str, project_id: str = "") -> Optional[RequirementEntity]:
        """Find a requirement by keyword search."""
        q = query.lower()
        best_match = None
        best_score = 0
        for entity in self._entities.values():
            if entity.entity_type != EntityType.REQUIREMENT:
                continue
            if project_id and entity.project_id != project_id:
                continue
            score = 0
            if q in entity.name.lower():
                score += 10
            if q in entity.description.lower():
                score += 5
            if q in entity.properties.get("code_reference", "").lower():
                score += 3
            if score > best_score:
                best_score = score
                best_match = entity
        return best_match

    # ── Evidence management ───────────────────────────────────

    def add_evidence(self, project_id: str, evidence_type: str,
                     content: str, source_doc: str,
                     source_page: int = None, actual_value: float = None,
                     unit: str = "", location: str = "",
                     confidence: float = 0.0) -> str:
        """Add evidence to the hub."""
        entity = EvidenceEntity(
            entity_id=f"ev-{len(self._entities)}",
            entity_type=EntityType.EVIDENCE,
            project_id=project_id,
            name=f"Evidence from {source_doc}",
            evidence_type=evidence_type,
            content=content,
            actual_value=actual_value,
            unit=unit,
            location=location,
            provenance=self._provenance.create(
                source_doc=source_doc,
                source_page=source_page,
                source_type=evidence_type,
                extraction_method="vision" if evidence_type in ("drawing", "image") else "native_text",
                confidence_score=confidence,
            ),
        )
        return self.add_entity(entity)

    def get_evidence_for_requirement(self, requirement_id: str,
                                     project_id: str = "") -> List[EvidenceEntity]:
        """Get all evidence related to a requirement."""
        # Find relationships
        edges = self._graph.get_edges_to(requirement_id, "supports")
        evidence_ids = [e.src_id for e in edges]
        return [self._entities[eid] for eid in evidence_ids if eid in self._entities]

    # ── BIM element management ────────────────────────────────

    def add_bim_element(self, project_id: str, guid: str, ifc_class: str,
                        name: str, level: str = "",
                        position: Dict[str, float] = None,
                        dimensions: Dict[str, float] = None,
                        material: str = "", system: str = "",
                        classification: str = "") -> str:
        """Add a BIM element to the hub."""
        entity = BIMElementEntity(
            entity_id=f"bim-{guid}",
            entity_type=EntityType.BIM_ELEMENT,
            project_id=project_id,
            name=name,
            guid=guid,
            ifc_class=ifc_class,
            level=level,
            position=position or {},
            dimensions=dimensions or {},
            material=material,
            system=system,
            classification=classification,
        )
        return self.add_entity(entity)

    def get_bim_elements(self, project_id: str = "",
                         ifc_class: str = "",
                         level: str = "") -> List[BIMElementEntity]:
        """Get BIM elements filtered by project, class, and level."""
        results = []
        for entity in self._entities.values():
            if entity.entity_type != EntityType.BIM_ELEMENT:
                continue
            if project_id and entity.project_id != project_id:
                continue
            if ifc_class and entity.properties.get("ifc_class") != ifc_class:
                continue
            if level and entity.properties.get("level") != level:
                continue
            results.append(entity)
        return results

    # ── Drawing management ────────────────────────────────────

    def add_drawing(self, project_id: str, drawing_number: str, title: str,
                    revision: str = "", discipline: str = "",
                    level: str = "", sheet: str = "",
                    file_path: str = "", page: int = None) -> str:
        """Add a drawing to the hub."""
        entity = DrawingEntity(
            entity_id=f"drw-{drawing_number}-{revision}",
            entity_type=EntityType.DRAWING,
            project_id=project_id,
            name=title,
            drawing_number=drawing_number,
            revision=revision,
            discipline=discipline,
            level=level,
            sheet=sheet,
            file_path=file_path,
            page=page,
        )
        return self.add_entity(entity)

    def get_drawings(self, project_id: str = "",
                     discipline: str = "",
                     level: str = "") -> List[DrawingEntity]:
        """Get drawings filtered by project, discipline, and level."""
        results = []
        for entity in self._entities.values():
            if entity.entity_type != EntityType.DRAWING:
                continue
            if project_id and entity.project_id != project_id:
                continue
            if discipline and entity.properties.get("discipline") != discipline:
                continue
            if level and entity.properties.get("level") != level:
                continue
            results.append(entity)
        return results

    # ── Statistics and reporting ──────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get hub statistics."""
        return {
            "total_entities": len(self._entities),
            "total_relationships": len(self._graph._edges),
            "entity_types": self._graph.get_stats()["node_types"],
            "graph": self._graph.get_stats(),
        }

    def clear(self):
        """Clear the hub."""
        self._entities.clear()
        self._graph.clear()


# Singleton instance
_hub = KnowledgeHub()


def get_hub() -> KnowledgeHub:
    """Get the global knowledge hub instance."""
    return _hub
