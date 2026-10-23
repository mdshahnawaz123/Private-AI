"""
BIM Service for Expo Design AI (Phase 7).

Manages BIM model data:
- Model registration
- Element storage and querying
- Model metadata
- Integration with Knowledge Hub
"""
import os
import json
import datetime
import hashlib
import threading
from dataclasses import asdict
from typing import List, Dict, Any, Optional

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()

from engines.ifc_engine import get_ifc_engine, IFCModel, IFCElement
from knowledge.hub import get_hub
from knowledge.entities import EngineeringEntity, BIMElementEntity, EntityType


class BIMService:
    """
    Service for managing BIM model data.
    Bridges the IFC engine and the Knowledge Hub.
    """

    def __init__(self):
        self._ifc_engine = get_ifc_engine()
        self._hub = get_hub()
        self._models: Dict[str, IFCModel] = {}
        self._projects = {}
        self._lock = threading.RLock()

    @staticmethod
    def _model_id(project_id, filename):
        return 'bim-' + hashlib.sha256((str(project_id) + '\0' + filename).encode()).hexdigest()[:32]

    def _publish(self, model, project_id):
        """Publish an already persisted model with project/model-scoped entities."""
        model_id = self._model_id(project_id, model.filename)
        prefix = model_id + ':'
        entities = [EngineeringEntity(
            entity_id=model_id, entity_type=EntityType.DOCUMENT,
            project_id=project_id, name=model.filename,
            properties={'kind': 'bim_model', 'ifc_schema': model.ifc_schema,
                        'length_unit': model.length_unit, 'element_count': len(model.elements),
                        'storeys': model.storeys})]
        for elem in model.elements:
            entities.append(BIMElementEntity(
                entity_id=prefix + elem.guid, entity_type=EntityType.BIM_ELEMENT,
                project_id=project_id, name=elem.name, guid=elem.guid,
                ifc_class=elem.ifc_class, type_name=elem.type_name, level=elem.level,
                position=elem.position, dimensions=elem.dimensions, material=elem.material,
                system=elem.system, classification=elem.classification,
                properties={**elem.properties, 'model_id': model_id, 'ifc_class': elem.ifc_class,
                            'level': elem.level, 'psets': elem.psets,
                            'quantities': elem.quantities}))
        # Save the affected cache so a failed add or commit can be rolled back.
        old_entities = dict(self._hub._entities)
        old_nodes = dict(self._hub._graph._nodes)
        try:
            for key in list(self._hub._entities):
                if key == model_id or key.startswith(prefix):
                    self._hub._entities.pop(key, None)
                    self._hub._graph._nodes.pop(key, None)
            for entity in entities:
                self._hub.add_entity(entity)
        except Exception:
            self._hub._entities = old_entities
            self._hub._graph._nodes = old_nodes
            raise
        return model_id, old_entities, old_nodes

    def register_model(self, model: IFCModel, project_id: str = "default",
                       document_id: int = None) -> str:
        """Replace one project/model atomically; failed writes publish no phantom model."""
        import db
        if not model.filename or any(not e.guid for e in model.elements):
            raise ValueError('A BIM filename and stable element GUIDs are required')
        if len({e.guid for e in model.elements}) != len(model.elements):
            raise ValueError('Duplicate element GUIDs in the same model')
        with self._lock, db.SessionLocal() as session:
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
            project = session.query(db.Project).filter_by(name=project_id).first()
            if project is None or project.deleted_at is not None:
                raise ValueError('Active project required for BIM registration')
            if document_id is not None and not session.query(db.Document).filter_by(
                    id=document_id, project_id=project.id).first():
                raise ValueError('BIM document belongs to a different project')
            row = session.query(db.BimModel).filter_by(project_id=project.id, filename=model.filename).first()
            if row is None:
                row = db.BimModel(project_id=project.id, filename=model.filename)
                session.add(row)
                session.flush()
            row.document_id = document_id
            for field in ('ifc_schema', 'length_unit', 'true_north_deg', 'site_origin', 'coordination_matrix'):
                setattr(row, field, getattr(model, field))
            row.element_count = len(model.elements)
            session.query(db.BimElement).filter_by(bim_model_id=row.id).delete()
            for elem in model.elements:
                session.add(db.BimElement(
                    project_id=project.id, bim_model_id=row.id, guid=elem.guid,
                    ifc_class=elem.ifc_class, name=elem.name, type_name=elem.type_name,
                    level=elem.level, material=elem.material, system=elem.system,
                    classification=elem.classification, psets={'expo_payload_v1': asdict(elem)},
                    x=elem.position.get('x'), y=elem.position.get('y'), z=elem.position.get('z'),
                    length=elem.dimensions.get('length'), width=elem.dimensions.get('width'),
                    height=elem.dimensions.get('height'), thickness=elem.dimensions.get('thickness'),
                    area=elem.quantities.get('area'), volume=elem.quantities.get('volume')))
            session.flush()
            model_id, old_entities, old_nodes = self._publish(model, project_id)
            try:
                session.commit()
            except Exception:
                self._hub._entities = old_entities
                self._hub._graph._nodes = old_nodes
                raise
            self._models[model_id] = model
            self._projects[model_id] = project_id
            return model_id

    def _hydrate(self, project_id):
        """Refresh from persistent rows; deleted projects cannot survive in caches."""
        import db
        with self._lock, db.SessionLocal() as session:
            project = session.query(db.Project).filter_by(name=project_id).first()
            rows = session.query(db.BimModel).filter_by(project_id=project.id).all() if project and project.deleted_at is None else []
            keep = {self._model_id(project_id, r.filename) for r in rows}
            for key in [k for k, p in self._projects.items() if p == project_id and k not in keep]:
                self._models.pop(key, None)
                self._projects.pop(key, None)
                for eid in list(self._hub._entities):
                    if eid == key or eid.startswith(key + ':'):
                        self._hub._entities.pop(eid, None)
                        self._hub._graph._nodes.pop(eid, None)
            for row in rows:
                elements = []
                for item in session.query(db.BimElement).filter_by(bim_model_id=row.id).all():
                    payload = (item.psets or {}).get('expo_payload_v1')
                    elements.append(IFCElement(**payload) if payload else IFCElement(
                        guid=item.guid, ifc_class=item.ifc_class, name=item.name,
                        type_name=item.type_name, level=item.level, material=item.material,
                        system=item.system, classification=item.classification, psets=item.psets or {}))
                model = IFCModel(filename=row.filename, ifc_schema=row.ifc_schema,
                    length_unit=row.length_unit, true_north_deg=row.true_north_deg or 0,
                    site_origin=row.site_origin or {}, coordination_matrix=row.coordination_matrix or [],
                    elements=elements, element_count=len(elements),
                    storeys=sorted({e.level for e in elements if e.level}))
                key, _, _ = self._publish(model, project_id)
                self._models[key] = model
                self._projects[key] = project_id

    def ingest_from_browser(self, model_data: Dict[str, Any],
                            project_id: str = "default") -> str:
        """
        Ingest BIM data extracted by the browser (web-ifc).
        This is the primary ingestion method.
        """
        model = self._ifc_engine.ingest_from_browser(model_data)
        return self.register_model(model, project_id)

    def parse_file(self, file_path: str, project_id: str = "default") -> Optional[str]:
        """Parse an IFC file and register it."""
        model = self._ifc_engine.parse_file(file_path)
        if model:
            return self.register_model(model, project_id)
        return None

    def get_model(self, model_id: str) -> Optional[IFCModel]:
        """Get a registered model."""
        return self._models.get(model_id)

    def list_models(self, project_id: str = "") -> List[Dict[str, Any]]:
        """List all registered models."""
        if project_id:
            self._hydrate(project_id)
        models = []
        for model_id, model in self._models.items():
            if project_id and self._projects.get(model_id) != project_id:
                continue
            models.append({
                "model_id": model_id,
                "filename": model.filename,
                "ifc_schema": model.ifc_schema,
                "element_count": model.element_count,
                "storeys": model.storeys,
            })
        return models

    def query_elements(self, project_id: str = "default",
                       ifc_class: str = "",
                       level: str = "",
                       guid: str = "") -> List[Dict[str, Any]]:
        """Query BIM elements."""
        self._hydrate(project_id)
        # Query from Knowledge Hub
        elements = self._hub.get_bim_elements(
            project_id=project_id,
            ifc_class=ifc_class,
            level=level,
        )

        # Filter by GUID if specified
        if guid:
            elements = [e for e in elements if e.guid == guid]

        return [
            {
                "guid": e.guid,
                "ifc_class": e.ifc_class,
                "name": e.name,
                "type_name": e.type_name,
                "level": e.level,
                "material": e.material,
                "system": e.system,
                "classification": e.classification,
                "position": e.position,
                "dimensions": e.dimensions,
            }
            for e in elements
        ]

    def get_element_by_guid(self, guid: str, project_id: str = "default") -> Optional[Dict[str, Any]]:
        """Get a single element by GUID."""
        elements = self.query_elements(project_id=project_id, guid=guid)
        return elements[0] if elements else None

    def get_element_count_by_class(self, project_id: str = "default") -> Dict[str, int]:
        """Get element counts by IFC class."""
        self._hydrate(project_id)
        elements = self._hub.get_bim_elements(project_id=project_id)
        counts = {}
        for elem in elements:
            counts[elem.ifc_class] = counts.get(elem.ifc_class, 0) + 1
        return counts

    def get_element_count_by_level(self, project_id: str = "default") -> Dict[str, int]:
        """Get element counts by level."""
        self._hydrate(project_id)
        elements = self._hub.get_bim_elements(project_id=project_id)
        counts = {}
        for elem in elements:
            level = elem.level or "Unknown"
            counts[level] = counts.get(level, 0) + 1
        return counts

    def get_stats(self, project_id: str = "default") -> Dict[str, Any]:
        """Get BIM statistics."""
        self._hydrate(project_id)
        elements = self._hub.get_bim_elements(project_id=project_id)
        by_class, by_level = {}, {}
        for element in elements:
            by_class[element.ifc_class] = by_class.get(element.ifc_class, 0) + 1
            level = element.level or 'Unknown'
            by_level[level] = by_level.get(level, 0) + 1
        return {
            "total_elements": len(elements),
            "by_class": by_class,
            "by_level": by_level,
            "models": sum(p == project_id for p in self._projects.values()),
        }


# Singleton instance
_bim_service = BIMService()


def get_bim_service() -> BIMService:
    """Get the global BIM service instance."""
    return _bim_service
