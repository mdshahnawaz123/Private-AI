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
from typing import List, Dict, Any, Optional

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()

from engines.ifc_engine import get_ifc_engine, IFCModel, IFCElement
from knowledge.hub import get_hub


class BIMService:
    """
    Service for managing BIM model data.
    Bridges the IFC engine and the Knowledge Hub.
    """

    def __init__(self):
        self._ifc_engine = get_ifc_engine()
        self._hub = get_hub()
        self._models: Dict[str, IFCModel] = {}

    def register_model(self, model: IFCModel, project_id: str = "default",
                       document_id: int = None) -> str:
        """Register a BIM model."""
        model_id = f"bim-{model.filename}"
        self._models[model_id] = model

        # Add to Knowledge Hub
        self._hub.add_entity(
            type="bim_model",
            project_id=project_id,
            name=model.filename,
            properties={
                "ifc_schema": model.ifc_schema,
                "length_unit": model.length_unit,
                "true_north_deg": model.true_north_deg,
                "element_count": model.element_count,
                "storeys": model.storeys,
            },
        )

        # Add elements to Knowledge Hub
        for elem in model.elements:
            self._hub.add_bim_element(
                project_id=project_id,
                guid=elem.guid,
                ifc_class=elem.ifc_class,
                name=elem.name,
                level=elem.level,
                position=elem.position,
                dimensions=elem.dimensions,
                material=elem.material,
                system=elem.system,
                classification=elem.classification,
            )

        logger.info("Registered BIM model: {} ({} elements)", model.filename, model.element_count)
        return model_id

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
        models = []
        for model_id, model in self._models.items():
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
        elements = self._hub.get_bim_elements(project_id=project_id)
        counts = {}
        for elem in elements:
            counts[elem.ifc_class] = counts.get(elem.ifc_class, 0) + 1
        return counts

    def get_element_count_by_level(self, project_id: str = "default") -> Dict[str, int]:
        """Get element counts by level."""
        elements = self._hub.get_bim_elements(project_id=project_id)
        counts = {}
        for elem in elements:
            level = elem.level or "Unknown"
            counts[level] = counts.get(level, 0) + 1
        return counts

    def get_stats(self, project_id: str = "default") -> Dict[str, Any]:
        """Get BIM statistics."""
        elements = self._hub.get_bim_elements(project_id=project_id)
        return {
            "total_elements": len(elements),
            "by_class": self.get_element_count_by_class(project_id),
            "by_level": self.get_element_count_by_level(project_id),
            "models": len([m for m in self._models.values()]),
        }


# Singleton instance
_bim_service = BIMService()


def get_bim_service() -> BIMService:
    """Get the global BIM service instance."""
    return _bim_service
