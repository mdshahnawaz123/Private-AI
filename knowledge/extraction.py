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


def _resolve_project_id(project_id):
    """Normalize a project identifier to the integer projects.id FK.

    ScheduleRow.project_id / Quantity.project_id are integer FKs to projects.id.
    Callers historically passed a project *name* here, which caused
    `sqlite3.IntegrityError: FOREIGN KEY constraint failed` (P0 bug). Accept
    either an int id or a name/slug and return the int id, or None if it can't
    be resolved (caller should then skip indexing rather than insert a bad FK).
    """
    if isinstance(project_id, int):
        return project_id
    try:
        if str(project_id).isdigit():
            return int(project_id)
    except Exception:
        pass
    import db
    s = db.SessionLocal()
    try:
        p = s.query(db.Project).filter_by(name=project_id).first()
        return p.id if p else None
    except Exception as e:
        logger.warning("Could not resolve project id for {!r}: {}", project_id, e)
        return None
    finally:
        s.close()


# ── Phase 2: Structured Table Extraction ───────────────────

def parse_generic_tables(text, source_doc="", page=None, revision="", source_type="PDF_TEXT"):
    """Parse markdown-style tables (| a | b | ...) from vision/extraction text into
    structured rows. table_name = the nearest heading line above the block. This is
    general-purpose: it captures area, parking, lift, unit-mix and any other table
    the vision model transcribes, not just a few hardcoded patterns."""
    import re as _re
    rows = []
    lines = (text or "").split("\n")
    def _is_sep(c):
        return bool(_re.fullmatch(r'\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*', c))
    def _cells(c):
        c = c.strip()
        if c.startswith("|"): c = c[1:]
        if c.endswith("|"): c = c[:-1]
        return [x.strip() for x in c.split("|")]
    i = 0
    last_heading = ""
    while i < len(lines):
        ln = lines[i]
        if ("|" in ln) and len(_cells(ln)) >= 2 and not _is_sep(ln):
            block = []
            j = i
            while j < len(lines) and ("|" in lines[j]) and len(_cells(lines[j])) >= 2:
                if not _is_sep(lines[j]):
                    block.append(_cells(lines[j]))
                j += 1
            if len(block) >= 2:
                header = block[0]
                ncol = len(header)
                for r in block[1:]:
                    r = (r + [""] * ncol)[:ncol]
                    key = r[0] if r else ""
                    if not key:
                        continue
                    vals = {}
                    for ci in range(1, ncol):
                        col = header[ci] if ci < len(header) and header[ci] else ("col%d" % ci)
                        vals[col] = r[ci]
                    rows.append({"doc": source_doc, "page": page,
                                 "table_name": last_heading or (header[0] if header else "Table"),
                                 "row_key": key, "row_values": vals, "revision": revision, "source_type": source_type})
            i = j
            continue
        s2 = ln.strip().strip("#").strip()
        if s2 and "|" not in s2 and len(s2) <= 60 and _re.search(r'[A-Za-z]', s2):
            if s2.isupper() or _re.match(r'^[A-Z0-9][\w &()/.\-,]+$', s2):
                last_heading = s2
        i += 1
    return rows


def extract_structured_tables_from_pdf(meta: Dict[str, Any],
                                        project_id: str = "default") -> List[Dict[str, Any]]:
    """
    Extract structured tables from PDF metadata.
    Detects TOS/TOPR level tables, legends, and schedules.
    Returns list of table rows with row_key and row_values.
    """
    import re
    rows = []
    filename = meta.get("filename", "")

    for page in meta.get("pages", []):
        text = page.get("text", "")
        page_num = page.get("page")
        if not text:
            continue

        # Detect TOS/TOPR level tables
        if "TOS" in text or "TOPR" in text:
            # Pattern: TOS/TOPR followed by level value
            tos_pattern = r'TOS\s+(\d+\.\d+)'
            topr_pattern = r'TOPR\s+(\d+\.\d+)'
            tower_pattern = r'TOWER\s*(\d+)'

            towers = re.findall(tower_pattern, text, re.IGNORECASE)
            tos_values = re.findall(tos_pattern, text, re.IGNORECASE)
            topr_values = re.findall(topr_pattern, text, re.IGNORECASE)

            for i, tower in enumerate(towers):
                row_key = f"TOS Tower {tower}"
                row_values = {"tower": tower}
                if i < len(tos_values):
                    row_values["TOS"] = tos_values[i]
                if i < len(topr_values):
                    row_values["TOPR"] = topr_values[i]
                rows.append({
                    "doc": filename,
                    "page": page_num,
                    "table_name": "TOS/TOPR Levels",
                    "row_key": row_key,
                    "row_values": row_values,
                    "revision": meta.get("revision", ""),
                })

        # General tables from the clean vision transcription (preferred) or text layer.
        has_vision = bool(page.get("tables") or page.get("vision"))
        _tbl_src = page.get("tables") or page.get("vision") or ""
        if "|" not in _tbl_src:
            _tbl_src = text if ("|" in text) else ""
            has_vision = False
        
        if _tbl_src:
            stype = "PDF_IMAGE" if has_vision else "PDF_TEXT"
            rows.extend(parse_generic_tables(_tbl_src, filename, page_num, meta.get("revision", ""), source_type=stype))

        # Detect legend codes (e.g., LX-PT, 1 BED-A, etc.)
        legend_pattern = r'\b([A-Z]{1,3}-[A-Z]{1,3})\b'
        legends = re.findall(legend_pattern, text)
        for legend in legends:
            rows.append({
                "doc": filename,
                "page": page_num,
                "table_name": "Legend",
                "row_key": legend,
                "row_values": {"code": legend},
                "revision": meta.get("revision", ""),
            })

    return rows


def extract_structured_tables_from_excel(meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Structured tables from an uploaded .xlsx/.xls (extract.extract_excel's
    meta shape: {"type":"excel","sheets":[{"sheet":name,"rows":[[cell,...],...]}]}).
    Reuses parse_generic_tables by rendering each sheet as a pipe table, the same
    row/column model already used for PDFs — so Schedules behaves identically
    regardless of whether the data came from a drawing or a spreadsheet."""
    filename = meta.get("filename", "")
    revision = meta.get("revision", "")
    rows: List[Dict[str, Any]] = []
    for sheet in (meta.get("sheets") or []):
        name = sheet.get("sheet") or "Sheet"
        srows = sheet.get("rows") or []
        if not srows:
            continue
        lines = [name] + ["| " + " | ".join(str(c) for c in r) + " |" for r in srows if any(str(c).strip() for c in r)]
        rows.extend(parse_generic_tables("\n".join(lines), filename, None, revision))
    return rows


def extract_structured_tables_from_docx(meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Structured tables from an uploaded .docx (extract.extract_docx's meta
    shape: {"type":"docx","tables":[[[cell,...],...], ...]})."""
    filename = meta.get("filename", "")
    revision = meta.get("revision", "")
    rows: List[Dict[str, Any]] = []
    for idx, tbl in enumerate(meta.get("tables") or []):
        if not tbl:
            continue
        name = "Table %d" % (idx + 1)
        lines = [name] + ["| " + " | ".join(str(c) for c in r) + " |" for r in tbl if any(str(c).strip() for c in r)]
        rows.extend(parse_generic_tables("\n".join(lines), filename, None, revision))
    return rows


def index_structured_tables(project_id, filename: str,
                            meta: Dict[str, Any]) -> int:
    """
    Index structured table rows into the database.
    Each row is stored as a separate retrievable unit.

    `project_id` may be an integer projects.id OR a project name/slug; it is
    normalized to the integer FK. If it cannot be resolved, indexing is skipped
    (avoids the FOREIGN KEY IntegrityError seen in the field).
    """
    import db

    project_id = _resolve_project_id(project_id)
    if project_id is None:
        logger.warning("index_structured_tables: unresolved project id for {} — skipping", filename)
        return 0

    # Dispatch on the document type's metadata shape. Previously this always
    # called the PDF extractor, which only reads meta["pages"] — so an uploaded
    # .xlsx/.docx (meta shaped by extract_excel/extract_docx instead) silently
    # produced zero ScheduleRow rows even though the upload itself succeeded.
    _mtype = meta.get("type")
    if _mtype == "excel":
        rows = extract_structured_tables_from_excel(meta)
    elif _mtype == "docx":
        rows = extract_structured_tables_from_docx(meta)
    else:
        rows = extract_structured_tables_from_pdf(meta, project_id)
    count = 0

    # Replace this document's previous rows so a re-read refreshes values and does
    # not accumulate duplicates. Keyed by (project, doc).
    _clr = db.SessionLocal()
    try:
        _clr.query(db.ScheduleRow).filter_by(project_id=project_id, doc=filename).delete()
        _clr.commit()
    except Exception:
        _clr.rollback()
    finally:
        _clr.close()

    for row in rows:
        db_session = db.SessionLocal()
        try:
            # Dedup within this document by (page, table, row_key) so the same row
            # label in different tables (e.g. "Ground Floor" in BUA vs NSA) is kept.
            existing = db_session.query(db.ScheduleRow).filter_by(
                project_id=project_id,
                doc=row["doc"],
                page=row["page"],
                table_name=row["table_name"],
                row_key=row["row_key"],
            ).first()
            if not existing:
                new_row = db.ScheduleRow(
                    project_id=project_id,
                    doc=row["doc"],
                    page=row["page"],
                    table_name=row["table_name"],
                    row_key=row["row_key"],
                    row_values=row["row_values"],
                    revision=row["revision"],
                )
                db_session.add(new_row)
                db_session.commit()
                count += 1
        finally:
            db_session.close()

    logger.info("Indexed {} structured table rows for {}", count, filename)
    return count


# ── Phase 2: Quantities Store ───────────────────────────────

def extract_quantities_from_pdf(meta: Dict[str, Any],
                                 project_id: str = "default") -> List[Dict[str, Any]]:
    """
    Extract numeric quantities from PDF metadata.
    Captures TOS/TOPR levels, areas, dimensions, and other numeric values.
    """
    quantities = []
    filename = meta.get("filename", "")

    for page in meta.get("pages", []):
        text = page.get("text", "")
        page_num = page.get("page")
        if not text:
            continue

        import re

        # Extract TOS/TOPR levels
        tos_pattern = r'TOS\s+(\d+\.\d+)'
        topr_pattern = r'TOPR\s+(\d+\.\d+)'
        tower_pattern = r'TOWER\s*(\d+)'

        towers = re.findall(tower_pattern, text, re.IGNORECASE)
        tos_values = re.findall(tos_pattern, text, re.IGNORECASE)
        topr_values = re.findall(topr_pattern, text, re.IGNORECASE)

        for i, tower in enumerate(towers):
            if i < len(tos_values):
                quantities.append({
                    "project_id": project_id,
                    "building": f"Tower {tower}",
                    "metric": "TOS",
                    "value": tos_values[i],
                    "unit": "m",
                    "source_doc": filename,
                    "source_page": page_num,
                    "revision": meta.get("revision", ""),
                })
            if i < len(topr_values):
                quantities.append({
                    "project_id": project_id,
                    "building": f"Tower {tower}",
                    "metric": "TOPR",
                    "value": topr_values[i],
                    "unit": "m",
                    "source_doc": filename,
                    "source_page": page_num,
                    "revision": meta.get("revision", ""),
                })

        # Extract dimensions (e.g., 6,250, 9,050, etc.)
        dim_pattern = r'\b(\d{1,3}(?:,\d{3})+(?:\.\d+)?)\s*(mm|cm|m)\b'
        dims = re.findall(dim_pattern, text, re.IGNORECASE)
        for value, unit in dims:
            quantities.append({
                "project_id": project_id,
                "building": "",
                "metric": "dimension",
                "value": value.replace(",", ""),
                "unit": unit.lower(),
                "source_doc": filename,
                "source_page": page_num,
                "revision": meta.get("revision", ""),
            })

    return quantities


def index_quantities(project_id, filename: str,
                     meta: Dict[str, Any]) -> int:
    """
    Index quantities into the database.

    `project_id` may be an integer projects.id OR a project name/slug; it is
    normalized to the integer FK. If it cannot be resolved, indexing is skipped
    (avoids the FOREIGN KEY IntegrityError seen in the field).
    """
    import db

    project_id = _resolve_project_id(project_id)
    if project_id is None:
        logger.warning("index_quantities: unresolved project id for {} — skipping", filename)
        return 0

    quantities = extract_quantities_from_pdf(meta, project_id)
    count = 0

    for q in quantities:
        db_session = db.SessionLocal()
        try:
            # Check if quantity already exists
            existing = db_session.query(db.Quantity).filter_by(
                project_id=project_id,
                building=q["building"],
                metric=q["metric"],
                source_doc=q["source_doc"],
                source_page=q["source_page"],
            ).first()

            if not existing:
                new_q = db.Quantity(
                    project_id=q["project_id"],
                    building=q["building"],
                    metric=q["metric"],
                    value=q["value"],
                    unit=q["unit"],
                    source_doc=q["source_doc"],
                    source_page=q["source_page"],
                    revision=q["revision"],
                )
                db_session.add(new_q)
                db_session.commit()   # Phase 2 fix: persist the quantity (was rolled back on close)
                count += 1
        finally:
            db_session.close()

    logger.info("Indexed {} quantities for {}", count, filename)
    return count


def index_visual_structured_records(project_id, filename: str, meta: Dict[str, Any]) -> int:
    """
    Phase 5A: Additive visual extraction branch for StructuredRecord.
    Reads vision markdown from meta, normalizes it, and stores it in StructuredRecord.
    """
    import db
    import re
    project_id = _resolve_project_id(project_id)
    if project_id is None: return 0

    count = 0
    _mtype = meta.get("type")
    if _mtype != "pdf": return 0
    
    # We only process pages where vision was used (e.g. source_type == "PDF_IMAGE")
    # Actually, we can just process all tables in meta that are from vision.
    
    # Let's extract the rows using our existing parse_generic_tables
    rows = []
    for page in meta.get("pages", []):
        vis = page.get("vision", "")
        if "|" in vis:
            page_num = page.get("page")
            # Parse it
            r = parse_generic_tables(vis, filename, page_num, meta.get("revision", ""), source_type="PDF_IMAGE")
            rows.extend(r)
            
    if not rows:
        return 0

    db_session = db.SessionLocal()
    try:
        # We don't blindly delete all StructuredRecords for the doc, because digital extraction
        # might have also populated it (e.g. run_structured_record_extraction). 
        # But wait, does the system run run_structured_record_extraction automatically? No!
        # So we should delete ONLY the visual ones? Or all? Let's delete visual ones.
        db_session.query(db.StructuredRecord).filter_by(
            project_id=project_id, doc=filename, extraction_method="VISION"
        ).delete()
        db_session.commit()
    except Exception:
        db_session.rollback()

    for r in rows:
        table_name = r.get("table_name", "")
        row_key = r.get("row_key", "")
        vals = r.get("row_values", {})
        
        # Normalize into StructuredRecord
        # Torsional Irregularity: table_name="Torsional Irregularity"
        # row_key="Left Part", vals={"direction": "X", "ratio": "1.009", ...}
        
        # Determine entity
        entity = row_key
        # Check if it has tower/level for backwards compatibility
        tower = ""
        level = ""
        t_match = re.search(r'TOWER\s*(\d+)', entity, re.IGNORECASE)
        if t_match:
            tower = t_match.group(1)
        l_match = re.search(r'(LEVEL\s*\d+|ROOF)', entity, re.IGNORECASE)
        if l_match:
            level = l_match.group(1)
            
        for col, raw_val in vals.items():
            if not raw_val or str(raw_val).strip() == "-": continue
            # Attempt to parse float
            val = None
            raw_clean = str(raw_val).replace(',', '').strip()
            try:
                val = float(raw_clean)
            except ValueError:
                pass
                
            rec = db.StructuredRecord(
                project_id=project_id,
                doc=r["doc"],
                revision=r.get("revision", ""),
                page=r.get("page"),
                schedule=table_name,
                tower=tower,
                level=level,
                field=col,
                raw_value=str(raw_val),
                value=val,
                unit=None,  # Unit parsing could be added if needed
                entity=entity,
                row_label=row_key,
                column_label=col,
                confidence="HIGH",
                extraction_method="VISION",
                source_type=r.get("source_type", "PDF_IMAGE")
            )
            db_session.add(rec)
            count += 1
            
    try:
        db_session.commit()
    except Exception as e:
        logger.error(f"Failed to commit visual structured records: {e}")
        db_session.rollback()
    finally:
        db_session.close()

    logger.info("Indexed {} visual structured records for {}", count, filename)
    return count
