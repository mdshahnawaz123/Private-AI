"""
Typed entity models for the Engineering Knowledge Hub.

These are the structured objects that replace flat text chunks:
Document, Drawing, Requirement, Evidence, BIMElement, Schedule, etc.
Every entity maintains provenance — where it came from.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class EntityType(Enum):
    DOCUMENT = "document"
    DRAWING = "drawing"
    REQUIREMENT = "requirement"
    EVIDENCE = "evidence"
    BIM_ELEMENT = "bim_element"
    SCHEDULE = "schedule"
    SCHEDULE_ROW = "schedule_row"
    ROOM = "room"
    DOOR = "door"
    WINDOW = "window"
    WALL = "wall"
    CLAUSE = "clause"
    PROJECT = "project"
    DISCIPLINE = "discipline"
    REFERENCE = "reference"
    RELATIONSHIP = "relationship"


class ConfidenceLevel(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


@dataclass
class Provenance:
    """Where did this information come from?"""
    source_doc: str = ""
    source_page: Optional[int] = None
    source_clause: str = ""
    source_type: str = ""  # code, spec, bep, eir, company, drawing
    extraction_method: str = ""  # native_text, vision, ocr, manual
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    confidence_score: float = 0.0
    extracted_by: str = ""  # model name or "human"
    extracted_at: str = ""  # ISO timestamp
    verified_by: Optional[str] = None
    verified_at: Optional[str] = None
    version: str = ""


@dataclass
class EngineeringEntity:
    """Base class for all engineering entities."""
    entity_id: str = ""
    entity_type: EntityType = EntityType.DOCUMENT
    project_id: str = ""
    name: str = ""
    description: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)
    provenance: Provenance = field(default_factory=Provenance)
    tags: List[str] = field(default_factory=list)
    status: str = "draft"  # draft, verified, published, superseded
    version: str = "1.0"
    created_at: str = ""
    updated_at: str = ""


@dataclass
class RequirementEntity(EngineeringEntity):
    """A code requirement with value, unit, and provenance."""
    requirement_id: str = ""
    value: Optional[float] = None
    unit: str = ""
    operator: str = ""  # >=, <=, =, >, <
    applies_to: str = ""  # what entity type this applies to
    discipline: str = ""
    code_reference: str = ""  # e.g., "DBC 2021 Section 10.3.2"
    notes: str = ""


@dataclass
class EvidenceEntity(EngineeringEntity):
    """A piece of evidence supporting or refuting a requirement."""
    evidence_type: str = ""  # text, table, drawing, bim_element, schedule_row, image
    content: str = ""
    actual_value: Optional[float] = None
    unit: str = ""
    location: str = ""  # where in the source (page, section, coordinate)
    bounding_box: Optional[Dict[str, float]] = None  # {x, y, w, h}


@dataclass
class BIMElementEntity(EngineeringEntity):
    """A BIM element (door, wall, column, etc.)."""
    guid: str = ""
    ifc_class: str = ""
    type_name: str = ""
    level: str = ""
    position: Dict[str, float] = field(default_factory=dict)  # {x, y, z}
    dimensions: Dict[str, float] = field(default_factory=dict)  # {length, width, height}
    material: str = ""
    system: str = ""
    classification: str = ""


@dataclass
class DrawingEntity(EngineeringEntity):
    """A drawing with metadata."""
    drawing_number: str = ""
    revision: str = ""
    discipline: str = ""
    level: str = ""
    sheet: str = ""
    sheet_date: str = ""
    file_path: str = ""
    page: Optional[int] = None


@dataclass
class ScheduleEntity(EngineeringEntity):
    """A schedule (door, window, room, finish, etc.)."""
    schedule_type: str = ""
    source_sheet: str = ""
    rows: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Relationship:
    """A relationship between two entities."""
    src_type: EntityType = EntityType.DOCUMENT
    src_id: str = ""
    relation: str = ""  # located_in, required_by, references, etc.
    dst_type: EntityType = EntityType.DOCUMENT
    dst_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
