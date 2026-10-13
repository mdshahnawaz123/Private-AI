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

    def __init__(self, load_db: bool = False):
        self._graph = KnowledgeGraph()
        self._provenance = get_tracker()
        self._precedence = get_precedence()
        self._entities: Dict[str, EngineeringEntity] = {}
        self._batch_session = None
        self._in_batch = False
        if load_db:
            try:
                self.load_from_sqlite()
            except Exception as e:
                logger.warning("KnowledgeHub initial load_from_sqlite skipped: {}", e)

    def begin_batch(self):
        """Begin a batch transaction for inserting/updating entities."""
        import db
        if self._batch_session is not None:
            try:
                self._batch_session.close()
            except Exception:
                pass
        self._batch_session = db.SessionLocal()
        self._in_batch = True

    def commit_batch(self):
        """Commit all pending inserts/updates in the batch session."""
        if self._batch_session is not None:
            try:
                self._batch_session.commit()
            except Exception:
                self._batch_session.rollback()
                raise
            finally:
                self._batch_session.close()
                self._batch_session = None
                self._in_batch = False

    def rollback_batch(self):
        """Roll back the batch session."""
        if self._batch_session is not None:
            try:
                self._batch_session.rollback()
            finally:
                self._batch_session.close()
                self._batch_session = None
                self._in_batch = False

    def _get_session(self):
        if self._in_batch and self._batch_session is not None:
            return self._batch_session, False
        import db
        return db.SessionLocal(), True

    def _resolve_pid(self, project_id: Any) -> Optional[int]:
        if not project_id:
            return None
        try:
            import db
            with db.SessionLocal() as s:
                pid_cand = None
                if isinstance(project_id, int):
                    pid_cand = project_id
                elif str(project_id).isdigit():
                    pid_cand = int(project_id)
                if pid_cand is not None:
                    p = s.query(db.Project).filter_by(id=pid_cand).first()
                    if p:
                        return p.id
                p = s.query(db.Project).filter_by(name=str(project_id)).first()
                if p:
                    return p.id
        except Exception:
            return None
        return None

    def save_requirement_to_sqlite(self, entity: RequirementEntity) -> bool:
        pid = self._resolve_pid(entity.project_id)
        if not pid:
            return False
        req_id = getattr(entity, "requirement_id", None)
        if not req_id:
            req_id = entity.entity_id.replace("req-", "") if entity.entity_id.startswith("req-") else entity.entity_id
        try:
            import db
            s, should_close = self._get_session()
            try:
                req = s.query(db.Requirement).filter_by(project_id=pid, req_id=req_id).first()
                val_str = str(entity.value) if entity.value is not None else ""
                prov = entity.provenance
                if isinstance(prov, dict):
                    conf_val = prov.get("confidence") or "medium"
                    if hasattr(conf_val, "value"): conf_val = conf_val.value
                    conf_str = str(conf_val)
                    doc_str = prov.get("source_doc") or ""
                    page_val = prov.get("source_page")
                    clause_str = prov.get("source_clause") or ""
                    src_type_str = prov.get("source_type") or "code"
                else:
                    conf_val = getattr(prov, "confidence", "medium") if prov else "medium"
                    if hasattr(conf_val, "value"): conf_val = conf_val.value
                    conf_str = str(conf_val)
                    doc_str = getattr(prov, "source_doc", "") or "" if prov else ""
                    page_val = getattr(prov, "source_page", None) if prov else None
                    clause_str = getattr(prov, "source_clause", "") or "" if prov else ""
                    src_type_str = getattr(prov, "source_type", "code") or "code" if prov else "code"
                if req:
                    req.title = entity.name or ""
                    req.description = entity.description or entity.notes or ""
                    req.value = val_str
                    req.unit = entity.unit or ""
                    req.source_doc = doc_str
                    req.source_page = page_val
                    req.source_clause = clause_str
                    req.evidence = entity.notes or entity.description or ""
                    req.confidence = conf_str
                    req.discipline = entity.discipline or ""
                    req.status = entity.status or "draft"
                else:
                    req = db.Requirement(
                        project_id=pid,
                        req_id=req_id,
                        title=entity.name or "",
                        description=entity.description or entity.notes or "",
                        value=val_str,
                        unit=entity.unit or "",
                        source_type=src_type_str,
                        source_doc=doc_str,
                        source_page=page_val,
                        source_clause=clause_str,
                        evidence=entity.notes or entity.description or "",
                        confidence=conf_str,
                        status=entity.status or "draft",
                        version=entity.version or "1.0",
                        discipline=entity.discipline or "",
                    )
                    s.add(req)
                if should_close:
                    s.commit()
            finally:
                if should_close:
                    s.close()
            return True
        except Exception as e:
            logger.warning("Failed to save Requirement to SQLite: {}", e)
            return False

    def save_evidence_to_sqlite(self, entity: EvidenceEntity) -> bool:
        pid = self._resolve_pid(entity.project_id)
        if not pid:
            return False
        try:
            import db
            s, should_close = self._get_session()
            try:
                ev = s.query(db.Evidence).filter_by(project_id=pid, evidence_id=entity.entity_id).first()
                prov = entity.provenance
                if isinstance(prov, dict):
                    conf_val = float(prov.get("confidence_score") or 0.0)
                    doc_str = prov.get("source_doc") or ""
                    page_val = prov.get("source_page")
                    ev_type_str = entity.evidence_type or prov.get("source_type") or "text"
                else:
                    conf_val = float(getattr(prov, "confidence_score", 0.0) or 0.0) if prov else 0.0
                    doc_str = getattr(prov, "source_doc", "") or "" if prov else ""
                    page_val = getattr(prov, "source_page", None) if prov else None
                    ev_type_str = entity.evidence_type or getattr(prov, "source_type", "text") or "text" if prov else "text"
                if ev:
                    ev.evidence_type = ev_type_str
                    ev.content = entity.content or ""
                    ev.source_doc = doc_str
                    ev.source_page = page_val
                    ev.bounding_box = entity.bounding_box
                    ev.confidence = conf_val
                    ev.metadata_json = entity.properties
                else:
                    ev = db.Evidence(
                        project_id=pid,
                        evidence_id=entity.entity_id,
                        evidence_type=ev_type_str,
                        content=entity.content or "",
                        source_doc=doc_str,
                        source_page=page_val,
                        bounding_box=entity.bounding_box,
                        confidence=conf_val,
                        metadata_json=entity.properties,
                    )
                    s.add(ev)
                if should_close:
                    s.commit()
            finally:
                if should_close:
                    s.close()
            return True
        except Exception as e:
            logger.warning("Failed to save Evidence to SQLite: {}", e)
            return False

    def save_edge_to_sqlite(self, edge: GraphEdge, project_id: Any) -> bool:
        pid = self._resolve_pid(project_id)
        if not pid:
            return False
        try:
            import db
            s, should_close = self._get_session()
            try:
                existing = s.query(db.GraphEdge).filter_by(
                    project_id=pid,
                    src_id=edge.src_id,
                    dst_id=edge.dst_id,
                    relation=edge.relation
                ).first()
                if not existing:
                    props = getattr(edge, "properties", {}) or {}
                    ge = db.GraphEdge(
                        project_id=pid,
                        src_type=edge.src_type or "",
                        src_id=edge.src_id,
                        relation=edge.relation,
                        dst_type=edge.dst_type or "",
                        dst_id=edge.dst_id,
                        metadata_json={"confidence": edge.confidence, "properties": props},
                    )
                    s.add(ge)
                if should_close:
                    s.commit()
            finally:
                if should_close:
                    s.close()
            return True
        except Exception as e:
            logger.warning("Failed to save GraphEdge to SQLite: {}", e)
            return False

    def save_to_sqlite(self, project_id: Any = None):
        """Save all in-memory entities and edges to SQLite."""
        for entity in list(self._entities.values()):
            if project_id and str(entity.project_id) != str(project_id):
                continue
            if isinstance(entity, RequirementEntity):
                self.save_requirement_to_sqlite(entity)
            elif isinstance(entity, EvidenceEntity):
                self.save_evidence_to_sqlite(entity)
        for edge in self._graph._edges:
            src = self._entities.get(edge.src_id)
            edge_pid = src.project_id if src else project_id
            if edge_pid:
                self.save_edge_to_sqlite(edge, edge_pid)

    def load_from_sqlite(self, project_id: Any = None):
        """Load Requirement, Evidence, and GraphEdge tables from SQLite into memory."""
        try:
            import db
            pid = self._resolve_pid(project_id) if project_id else None
            with db.SessionLocal() as s:
                # 1. Load Requirements
                req_query = s.query(db.Requirement)
                if pid is not None:
                    req_query = req_query.filter_by(project_id=pid)
                for r in req_query.all():
                    val = None
                    if r.value:
                        try: val = float(r.value)
                        except (ValueError, TypeError): pass
                    entity = RequirementEntity(
                        entity_id=f"req-{r.req_id}",
                        entity_type=EntityType.REQUIREMENT,
                        project_id=str(r.project_id),
                        name=r.title or "",
                        description=r.description or "",
                        requirement_id=r.req_id,
                        value=val,
                        unit=r.unit or "",
                        discipline=r.discipline or "",
                        status=r.status or "draft",
                        version=r.version or "1.0",
                        notes=r.evidence or "",
                        provenance=self._provenance.create(
                            source_doc=r.source_doc or "",
                            source_page=r.source_page,
                            source_clause=r.source_clause or "",
                            source_type=r.source_type or "code",
                            confidence=r.confidence or "medium",
                        ),
                    )
                    self._entities[entity.entity_id] = entity
                    node = GraphNode(
                        node_id=entity.entity_id,
                        node_type=entity.entity_type.value,
                        name=entity.name,
                        properties=entity.properties,
                        project_id=entity.project_id,
                    )
                    self._graph.add_node(node)

                # 2. Load Evidence
                ev_query = s.query(db.Evidence)
                if pid is not None:
                    ev_query = ev_query.filter_by(project_id=pid)
                for e in ev_query.all():
                    entity = EvidenceEntity(
                        entity_id=e.evidence_id,
                        entity_type=EntityType.EVIDENCE,
                        project_id=str(e.project_id),
                        name=f"Evidence from {e.source_doc or 'unknown'}",
                        evidence_type=e.evidence_type or "text",
                        content=e.content or "",
                        unit="",
                        bounding_box=e.bounding_box,
                        properties=e.metadata_json or {},
                        provenance=self._provenance.create(
                            source_doc=e.source_doc or "",
                            source_page=e.source_page,
                            source_type=e.evidence_type or "text",
                            confidence_score=e.confidence or 0.0,
                        ),
                    )
                    self._entities[entity.entity_id] = entity
                    node = GraphNode(
                        node_id=entity.entity_id,
                        node_type=entity.entity_type.value,
                        name=entity.name,
                        properties=entity.properties,
                        project_id=entity.project_id,
                    )
                    self._graph.add_node(node)

                # 3. Load GraphEdges
                edge_query = s.query(db.GraphEdge)
                if pid is not None:
                    edge_query = edge_query.filter_by(project_id=pid)
                for ge in edge_query.all():
                    meta = ge.metadata_json or {}
                    edge = GraphEdge(
                        src_id=ge.src_id,
                        src_type=ge.src_type or "",
                        relation=ge.relation or "",
                        dst_id=ge.dst_id,
                        dst_type=ge.dst_type or "",
                        confidence=meta.get("confidence", 0.0) if isinstance(meta, dict) else 0.0,
                        properties=meta.get("properties", {}) if isinstance(meta, dict) else {},
                    )
                    self._graph.add_edge(edge)
            logger.info("KnowledgeHub loaded from SQLite: {} entities, {} edges",
                        len(self._entities), len(self._graph._edges))
        except Exception as e:
            logger.warning("KnowledgeHub load_from_sqlite failed: {}", e)

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

    def remove_project(self, project: str):
        """Remove the named project's cached entities and incident graph edges."""
        identities = {key for key, entity in self._entities.items() if entity.project_id == project}
        identities.update(key for key, node in self._graph._nodes.items() if node.project_id == project)
        for key in identities:
            self._entities.pop(key, None)
            self._graph._nodes.pop(key, None)
            self._provenance._provenance_store.pop(key, None)
        edges = [edge for edge in self._graph._edges if edge.src_id not in identities and edge.dst_id not in identities]
        self._graph._edges = []
        self._graph._adjacency.clear()
        self._graph._reverse_adjacency.clear()
        for edge in edges:
            self._graph.add_edge(edge)
        pid_int = self._resolve_pid(project)
        if pid_int:
            try:
                import db
                with db.SessionLocal() as s:
                    s.query(db.Requirement).filter_by(project_id=pid_int).delete()
                    s.query(db.Evidence).filter_by(project_id=pid_int).delete()
                    s.query(db.GraphEdge).filter_by(project_id=pid_int).delete()
                    s.commit()
            except Exception as e:
                logger.warning("remove_project sqlite delete failed: {}", e)

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
        self.save_edge_to_sqlite(edge, src.project_id)
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
            project_id=str(project_id),
            name=title,
            description=notes,
            requirement_id=req_id,
            value=value,
            unit=unit,
            operator=operator,
            applies_to=applies_to,
            discipline=discipline,
            code_reference=code_reference,
            notes=notes,
            provenance=self._provenance.create(
                source_doc=source_doc,
                source_page=source_page,
                source_clause=source_clause,
                source_type="code",
                extraction_method="native_text",
                confidence=confidence,
            ),
        )
        eid = self.add_entity(entity)
        self.save_requirement_to_sqlite(entity)
        return eid

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
                     confidence: float = 0.0, evidence_id: str = "") -> str:
        """Add evidence to the hub."""
        eid = evidence_id or f"ev-{len(self._entities)}"
        entity = EvidenceEntity(
            entity_id=eid,
            entity_type=EntityType.EVIDENCE,
            project_id=str(project_id),
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
        saved_id = self.add_entity(entity)
        self.save_evidence_to_sqlite(entity)
        return saved_id

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
_hub = KnowledgeHub(load_db=True)


def get_hub() -> KnowledgeHub:
    """Get the global knowledge hub instance."""
    return _hub
