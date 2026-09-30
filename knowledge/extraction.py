"""
Structured entity extraction for the Engineering Knowledge Hub.

Extracts typed entities from documents:
- Requirements from code documents
- Drawings from drawing metadata
- Schedules from Excel files
- BIM elements from IFC data
- Evidence from all sources

This replaces flat text chunking with structured, typed objects.
"""
import re
import json
from typing import List, Dict, Any, Optional, Tuple

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()

from knowledge.entities import (
    EntityType, RequirementEntity, EvidenceEntity,
    DrawingEntity, ScheduleEntity, BIMElementEntity,
)
from knowledge.hub import get_hub


# ── Requirement extraction patterns ─────────────────────────
# These are starting patterns — they will be refined with evaluation datasets

REQUIREMENT_PATTERNS = [
    # Minimum/maximum dimensions
    (r"(?:minimum|min\.?)\s+(?:clear\s+)?(?:width|height|depth|size)\s*(?:of|is|:)?\s*(\d+(?:\.\d+)?)\s*(mm|cm|m|in|ft)", "minimum_dimension"),
    (r"(?:maximum|max\.?)\s+(?:clear\s+)?(?:width|height|depth|size)\s*(?:of|is|:)?\s*(\d+(?:\.\d+)?)\s*(mm|cm|m|in|ft)", "maximum_dimension"),
    # Width requirements
    (r"(?:door|corridor|passage|exit)\s+width\s*(?:of|is|must be|shall be|:)?\s*(?:at least|minimum|not less than)?\s*(\d+(?:\.\d+)?)\s*(mm|cm|m|in|ft)", "width_requirement"),
    # Height requirements
    (r"(?:ceiling|headroom|clear)\s+height\s*(?:of|is|must be|shall be|:)?\s*(?:at least|minimum|not less than)?\s*(\d+(?:\.\d+)?)\s*(mm|cm|m|in|ft)", "height_requirement"),
    # Area requirements
    (r"(?:floor\s+)?area\s*(?:of|is|must be|shall be|:)?\s*(?:at least|minimum|not less than)?\s*(\d+(?:\.\d+)?)\s*(m²|sqm|sq\.?\s*m|ft²|sqft)", "area_requirement"),
    # Count requirements
    (r"(?:number\s+of|at\s+least|minimum)\s+(\d+)\s+(?:exits|doors|parking\s+bays|toilets|WCs|spaces)", "count_requirement"),
    # Fire rating
    (r"(?:fire[\s-]?(?:resistance|rating|resistant))\s*(?:of|is|must be|shall be|:)?\s*(?:at least|minimum)?\s*(\d+)\s*(?:min|minutes|hr|hour)", "fire_rating"),
    # Travel distance
    (r"(?:travel\s+distance|exit\s+access\s+travel)\s*(?:of|is|must be|shall be|:)?\s*(?:not\s+more\s+than|maximum)?\s*(\d+(?:\.\d+)?)\s*(mm|cm|m|in|ft)", "travel_distance"),
    # Occupant load
    (r"(?:occupant\s+load|occupancy)\s*(?:of|is|must be|shall be|:)?\s*(\d+(?:\.\d+)?)\s*(?:persons|people|occupants)", "occupant_load"),
    # Slope/gradient
    (r"(?:slope|gradient|pitch)\s*(?:of|is|must be|shall be|:)?\s*(?:not\s+more\s+than|maximum)?\s*(\d+(?:\.\d+)?)\s*(%|degrees?|:\d+)", "slope"),
]


def extract_requirements_from_text(text: str, source_doc: str = "",
                                    source_page: int = None,
                                    project_id: str = "") -> List[Dict[str, Any]]:
    """
    Extract requirements from text using pattern matching.
    Returns list of requirement dicts with value, unit, and context.
    """
    requirements = []
    for pattern, req_type in REQUIREMENT_PATTERNS:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            value_str = match.group(1)
            unit = match.group(2) if len(match.groups()) > 1 else ""
            try:
                value = float(value_str)
            except ValueError:
                continue

            # Get surrounding context (100 chars before and after)
            start = max(0, match.start() - 100)
            end = min(len(text), match.end() + 100)
            context = text[start:end].strip()

            # Determine operator
            operator = ">="
            if "maximum" in req_type or "max" in req_type:
                operator = "<="

            requirements.append({
                "req_type": req_type,
                "value": value,
                "unit": unit,
                "operator": operator,
                "context": context,
                "source_doc": source_doc,
                "source_page": source_page,
                "confidence": "medium",  # Pattern matching is medium confidence
            })

    logger.info("Extracted {} requirements from {}", len(requirements), source_doc)
    return requirements


def extract_requirements_from_pdf_meta(meta: Dict[str, Any],
                                        project_id: str = "") -> List[Dict[str, Any]]:
    """Extract requirements from PDF metadata (per-page text)."""
    all_requirements = []
    for page in meta.get("pages", []):
        text = page.get("text", "")
        if text:
            reqs = extract_requirements_from_text(
                text, source_doc=meta.get("filename", ""),
                source_page=page.get("page"),
                project_id=project_id,
            )
            all_requirements.extend(reqs)
    return all_requirements


def extract_entities_from_excel(meta: Dict[str, Any],
                                 project_id: str = "") -> List[Dict[str, Any]]:
    """Extract schedule entities from Excel metadata."""
    schedules = []
    for sheet in meta.get("sheets", []):
        sheet_name = sheet.get("sheet", "")
        rows = sheet.get("rows", [])

        # Detect schedule type from sheet name
        schedule_type = "unknown"
        name_lower = sheet_name.lower()
        if "door" in name_lower:
            schedule_type = "door"
        elif "window" in name_lower:
            schedule_type = "window"
        elif "room" in name_lower or "space" in name_lower:
            schedule_type = "room"
        elif "finish" in name_lower:
            schedule_type = "finish"
        elif "hardware" in name_lower:
            schedule_type = "hardware"

        # Extract rows as schedule data
        schedule_rows = []
        for row in rows:
            if any(cell.strip() for cell in row):
                schedule_rows.append(row)

        if schedule_rows:
            schedules.append({
                "schedule_type": schedule_type,
                "source_sheet": sheet_name,
                "rows": schedule_rows,
                "source_doc": meta.get("filename", ""),
            })

    logger.info("Extracted {} schedules from {}", len(schedules), meta.get("filename", ""))
    return schedules


def extract_drawing_metadata(filename: str, project_id: str = "") -> Optional[Dict[str, Any]]:
    """Extract drawing metadata from filename using meta_parse."""
    import meta_parse
    meta = meta_parse.parse_drawing_meta(filename)
    if meta:
        return {
            "drawing_number": meta.get("base_id", ""),
            "title": meta.get("stem", ""),
            "revision": meta.get("revision", ""),
            "discipline": meta.get("discipline_hint", ""),
            "doctype": meta.get("doctype", ""),
            "source_doc": filename,
        }
    return None


def index_structured_entities(project_id: str, filename: str,
                              meta: Dict[str, Any]) -> Dict[str, int]:
    """
    Index structured entities from document metadata into the Knowledge Hub.
    Returns counts of indexed entities.
    """
    hub = get_hub()
    counts = {"requirements": 0, "drawings": 0, "schedules": 0, "evidence": 0}

    doc_type = meta.get("type", "")

    if doc_type == "pdf":
        # Extract requirements from PDF
        reqs = extract_requirements_from_pdf_meta(meta, project_id)
        for req in reqs:
            hub.add_requirement(
                project_id=project_id,
                req_id=f"auto-{counts['requirements']}",
                title=req["req_type"],
                value=req["value"],
                unit=req["unit"],
                operator=req["operator"],
                discipline="",
                code_reference="",
                source_doc=req["source_doc"],
                source_page=req["source_page"],
                confidence=req["confidence"],
                notes=req["context"],
            )
            counts["requirements"] += 1

    elif doc_type == "excel":
        # Extract schedules from Excel
        schedules = extract_entities_from_excel(meta, project_id)
        for sched in schedules:
            hub.add_entity(ScheduleEntity(
                entity_id=f"sched-{filename}-{sched['schedule_type']}",
                entity_type=EntityType.SCHEDULE,
                project_id=project_id,
                name=f"{sched['schedule_type'].title()} Schedule",
                properties={
                    "schedule_type": sched["schedule_type"],
                    "source_sheet": sched["source_sheet"],
                    "source_doc": sched["source_doc"],
                },
            ))
            counts["schedules"] += 1

    elif doc_type == "cad":
        # Extract drawing metadata
        drawing_meta = extract_drawing_metadata(filename, project_id)
        if drawing_meta:
            hub.add_drawing(
                project_id=project_id,
                drawing_number=drawing_meta["drawing_number"],
                title=drawing_meta["title"],
                revision=drawing_meta["revision"],
                discipline=drawing_meta["discipline"],
                file_path=filename,
            )
            counts["drawings"] += 1

    # Add evidence for each page/sheet
    if doc_type == "pdf":
        for page in meta.get("pages", []):
            text = page.get("text", "")
            if text:
                hub.add_evidence(
                    project_id=project_id,
                    evidence_type="text",
                    content=text[:500],  # First 500 chars as evidence
                    source_doc=filename,
                    source_page=page.get("page"),
                    confidence=0.8,
                )
                counts["evidence"] += 1

    logger.info("Indexed structured entities for {}: {}", filename, counts)
    return counts
