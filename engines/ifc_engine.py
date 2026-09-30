"""
IFC Engine for Expo Design AI (Phase 7).

Server-side IFC parsing and BIM data extraction.
Supports:
- Element extraction (IfcDoor, IfcWindow, IfcWall, IfcColumn, etc.)
- Property sets (Psets)
- Spatial hierarchy (Project → Site → Building → Storey → Element)
- Quantities and measurements
- Materials and classifications
- Relationships

Uses IfcOpenShell when available, falls back to browser-extracted data.
"""
import os
import json
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


@dataclass
class IFCElement:
    """A parsed IFC element."""
    guid: str = ""
    ifc_class: str = ""
    name: str = ""
    type_name: str = ""
    level: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)
    psets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    quantities: Dict[str, float] = field(default_factory=dict)
    material: str = ""
    system: str = ""
    classification: str = ""
    position: Dict[str, float] = field(default_factory=dict)
    dimensions: Dict[str, float] = field(default_factory=dict)


@dataclass
class IFCModel:
    """A parsed IFC model."""
    filename: str = ""
    ifc_schema: str = ""
    length_unit: str = "mm"
    true_north_deg: float = 0.0
    site_origin: Dict[str, float] = field(default_factory=dict)
    coordination_matrix: List[List[float]] = field(default_factory=list)
    elements: List[IFCElement] = field(default_factory=list)
    element_count: int = 0
    storeys: List[str] = field(default_factory=list)


class IFCEngine:
    """
    Server-side IFC parsing engine.
    Uses IfcOpenShell when available.
    """

    def __init__(self):
        self._ifcopenshell_available = False
        self._check_backend()

    def _check_backend(self):
        """Check if IfcOpenShell is available."""
        try:
            import ifcopenshell  # noqa: F401
            self._ifcopenshell_available = True
            logger.info("IfcOpenShell available")
        except ImportError:
            logger.info("IfcOpenShell not available — use browser-extracted data")

    def is_available(self) -> bool:
        """Check if server-side IFC parsing is available."""
        return self._ifcopenshell_available

    def get_backend(self) -> str:
        """Get the backend name."""
        return "ifcopenshell" if self._ifcopenshell_available else "browser"

    def parse_file(self, file_path: str) -> Optional[IFCModel]:
        """
        Parse an IFC file and extract all elements.
        Returns IFCModel with all extracted data.
        """
        if not self._ifcopenshell_available:
            logger.warning("IfcOpenShell not available — cannot parse IFC file")
            return None

        try:
            import ifcopenshell
            import ifcopenshell.geom

            ifc_file = ifcopenshell.open(file_path)
            model = IFCModel(
                filename=os.path.basename(file_path),
                ifc_schema=ifc_file.schema,
            )

            # Extract project info
            projects = ifc_file.by_type("IfcProject")
            if projects:
                project = projects[0]
                model.length_unit = self._get_length_unit(ifc_file)
                model.true_north_deg = self._get_true_north(ifc_file)

            # Extract storeys
            storeys = ifc_file.by_type("IfcBuildingStorey")
            model.storeys = [s.Name or f"Storey_{i}" for i, s in enumerate(storeys)]

            # Extract elements
            element_types = [
                "IfcDoor", "IfcWindow", "IfcWall", "IfcColumn", "IfcBeam",
                "IfcSlab", "IfcRoof", "IfcStair", "IfcRamp", "IfcSpace",
                "IfcFurniture", "IfcEquipment", "IfcPipeSegment", "IfcDuctSegment",
            ]

            for elem_type in element_types:
                elements = ifc_file.by_type(elem_type)
                for elem in elements:
                    parsed = self._parse_element(elem, ifc_file)
                    if parsed:
                        model.elements.append(parsed)

            model.element_count = len(model.elements)
            logger.info("Parsed IFC file: {} elements from {}", model.element_count, file_path)
            return model

        except Exception as e:
            logger.error("IFC parsing failed: {}", e)
            return None

    def _get_length_unit(self, ifc_file) -> str:
        """Get the length unit from the IFC file."""
        try:
            units = ifc_file.by_type("IfcUnitAssignment")
            if units:
                for unit in units[0].Units:
                    if unit.is_a("IfcSIUnit") and unit.UnitType == "LENGTHUNIT":
                        return unit.Name or "mm"
        except Exception:
            pass
        return "mm"

    def _get_true_north(self, ifc_file) -> float:
        """Get true north from the IFC file."""
        try:
            contexts = ifc_file.by_type("IfcGeometricRepresentationContext")
            for ctx in contexts:
                if ctx.TrueNorth:
                    # Convert direction to degrees
                    import math
                    direction = ctx.TrueNorth.DirectionRatios
                    if len(direction) >= 2:
                        angle = math.degrees(math.atan2(direction[1], direction[0]))
                        return angle
        except Exception:
            pass
        return 0.0

    def _parse_element(self, elem, ifc_file) -> Optional[IFCElement]:
        """Parse a single IFC element."""
        try:
            guid = getattr(elem, "GlobalId", "")
            ifc_class = elem.is_a()
            name = getattr(elem, "Name", "") or ""
            type_name = ""

            # Get type name
            if hasattr(elem, "IsTypedBy") and elem.IsTypedBy:
                for rel in elem.IsTypedBy:
                    if hasattr(rel, "RelatingType") and rel.RelatingType:
                        type_name = getattr(rel.RelatingType, "Name", "") or ""

            # Get level/storey
            level = self._get_element_storey(elem, ifc_file)

            # Get properties
            properties = self._get_properties(elem)

            # Get property sets
            psets = self._get_psets(elem)

            # Get quantities
            quantities = self._get_quantities(elem, ifc_file)

            # Get material
            material = self._get_material(elem, ifc_file)

            # Get system
            system = self._get_system(elem, ifc_file)

            # Get classification
            classification = self._get_classification(elem, ifc_file)

            return IFCElement(
                guid=guid,
                ifc_class=ifc_class,
                name=name,
                type_name=type_name,
                level=level,
                properties=properties,
                psets=psets,
                quantities=quantities,
                material=material,
                system=system,
                classification=classification,
            )

        except Exception as e:
            logger.warning("Failed to parse element: {}", e)
            return None

    def _get_element_storey(self, elem, ifc_file) -> str:
        """Get the storey/level of an element."""
        try:
            if hasattr(elem, "ContainedInStructure") and elem.ContainedInStructure:
                for rel in elem.ContainedInStructure:
                    if hasattr(rel, "RelatingStructure") and rel.RelatingStructure:
                        structure = rel.RelatingStructure
                        if structure.is_a("IfcBuildingStorey"):
                            return getattr(structure, "Name", "") or ""
        except Exception:
            pass
        return ""

    def _get_properties(self, elem) -> Dict[str, Any]:
        """Get basic properties of an element."""
        props = {}
        try:
            for attr in ["Name", "Description", "ObjectType", "Tag", "PredefinedType"]:
                val = getattr(elem, attr, None)
                if val:
                    props[attr] = val
        except Exception:
            pass
        return props

    def _get_psets(self, elem) -> Dict[str, Dict[str, Any]]:
        """Get property sets (Psets) of an element."""
        psets = {}
        try:
            if hasattr(elem, "IsDefinedBy") and elem.IsDefinedBy:
                for rel in elem.IsDefinedBy:
                    if hasattr(rel, "RelatingPropertyDefinition"):
                        pset = rel.RelatingPropertyDefinition
                        if pset.is_a("IfcPropertySet"):
                            pset_name = getattr(pset, "Name", "Unknown")
                            props = {}
                            for prop in pset.HasProperties:
                                prop_name = getattr(prop, "Name", "")
                                prop_val = getattr(prop, "NominalValue", None)
                                if prop_val is not None:
                                    props[prop_name] = prop_val.wrappedValue if hasattr(prop_val, 'wrappedValue') else str(prop_val)
                            psets[pset_name] = props
        except Exception:
            pass
        return psets

    def _get_quantities(self, elem, ifc_file) -> Dict[str, float]:
        """Get quantities of an element."""
        quantities = {}
        try:
            if hasattr(elem, "IsDefinedBy") and elem.IsDefinedBy:
                for rel in elem.IsDefinedBy:
                    if hasattr(rel, "RelatingPropertyDefinition"):
                        qto = rel.RelatingPropertyDefinition
                        if qto.is_a("IfcElementQuantity"):
                            for qto_prop in qto.Quantities:
                                qto_name = getattr(qto_prop, "Name", "")
                                if hasattr(qto_prop, "LengthValue"):
                                    quantities[qto_name] = qto_prop.LengthValue
                                elif hasattr(qto_prop, "AreaValue"):
                                    quantities[qto_name] = qto_prop.AreaValue
                                elif hasattr(qto_prop, "VolumeValue"):
                                    quantities[qto_name] = qto_prop.VolumeValue
                                elif hasattr(qto_prop, "CountValue"):
                                    quantities[qto_name] = qto_prop.CountValue
                                elif hasattr(qto_prop, "WeightValue"):
                                    quantities[qto_name] = qto_prop.WeightValue
        except Exception:
            pass
        return quantities

    def _get_material(self, elem, ifc_file) -> str:
        """Get material of an element."""
        try:
            if hasattr(elem, "HasAssociations") and elem.HasAssociations:
                for rel in elem.HasAssociations:
                    if hasattr(rel, "RelatingMaterial"):
                        mat = rel.RelatingMaterial
                        if hasattr(mat, "Name"):
                            return mat.Name
                        if hasattr(mat, "Materials") and mat.Materials:
                            return ", ".join(m.Name for m in mat.Materials if hasattr(m, 'Name'))
        except Exception:
            pass
        return ""

    def _get_system(self, elem, ifc_file) -> str:
        """Get system of an element."""
        try:
            if hasattr(elem, "HasAssignments") and elem.HasAssignments:
                for rel in elem.HasAssignments:
                    if hasattr(rel, "RelatingGroup"):
                        group = rel.RelatingGroup
                        if hasattr(group, "Name"):
                            return group.Name
        except Exception:
            pass
        return ""

    def _get_classification(self, elem, ifc_file) -> str:
        """Get classification of an element."""
        try:
            if hasattr(elem, "HasAssociations") and elem.HasAssociations:
                for rel in elem.HasAssociations:
                    if hasattr(rel, "RelatingClassification"):
                        cls = rel.RelatingClassification
                        if hasattr(cls, "Identification"):
                            return cls.Identification
                        if hasattr(cls, "Name"):
                            return cls.Name
        except Exception:
            pass
        return ""

    def ingest_from_browser(self, model_data: Dict[str, Any]) -> IFCModel:
        """
        Ingest BIM data extracted by the browser (web-ifc).
        This is the primary method when IfcOpenShell is not available.
        """
        model = IFCModel(
            filename=model_data.get("filename", ""),
            ifc_schema=model_data.get("ifc_schema", ""),
            length_unit=model_data.get("length_unit", "mm"),
            true_north_deg=model_data.get("true_north_deg", 0.0),
            site_origin=model_data.get("site_origin", {}),
            coordination_matrix=model_data.get("coordination_matrix", []),
            storeys=model_data.get("storeys", []),
        )

        for elem_data in model_data.get("elements", []):
            elem = IFCElement(
                guid=elem_data.get("guid", ""),
                ifc_class=elem_data.get("ifc_class", ""),
                name=elem_data.get("name", ""),
                type_name=elem_data.get("type_name", ""),
                level=elem_data.get("level", ""),
                properties=elem_data.get("properties", {}),
                psets=elem_data.get("psets", {}),
                quantities=elem_data.get("quantities", {}),
                material=elem_data.get("material", ""),
                system=elem_data.get("system", ""),
                classification=elem_data.get("classification", ""),
                position=elem_data.get("position", {}),
                dimensions=elem_data.get("dimensions", {}),
            )
            model.elements.append(elem)

        model.element_count = len(model.elements)
        logger.info("Ingested BIM data from browser: {} elements", model.element_count)
        return model

    def query_elements(self, model: IFCModel,
                       ifc_class: str = "",
                       level: str = "",
                       guid: str = "") -> List[IFCElement]:
        """Query elements from a parsed model."""
        results = []
        for elem in model.elements:
            if ifc_class and elem.ifc_class != ifc_class:
                continue
            if level and elem.level != level:
                continue
            if guid and elem.guid != guid:
                continue
            results.append(elem)
        return results

    def get_element_count_by_class(self, model: IFCModel) -> Dict[str, int]:
        """Get element counts grouped by IFC class."""
        counts = {}
        for elem in model.elements:
            counts[elem.ifc_class] = counts.get(elem.ifc_class, 0) + 1
        return counts

    def get_element_count_by_level(self, model: IFCModel) -> Dict[str, int]:
        """Get element counts grouped by level."""
        counts = {}
        for elem in model.elements:
            level = elem.level or "Unknown"
            counts[level] = counts.get(level, 0) + 1
        return counts


# Singleton instance
_ifc_engine = IFCEngine()


def get_ifc_engine() -> IFCEngine:
    """Get the global IFC engine instance."""
    return _ifc_engine
