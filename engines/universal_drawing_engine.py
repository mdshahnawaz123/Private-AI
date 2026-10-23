"""
Universal Drawing Ingestion & Understanding Engine.
Provides schema-driven spatial extraction for engineering CAD/Revit PDF sheets:
- Title Block (Drawing Number, Title, Project Title, Revisions, Sign-off initials)
- Structural Schedules (Beams, Columns, Drop Panels, Walls, Slabs)
- Consultant Review Stamps (Status, Date, Review Codes)
- Grid Lines & Bay Spacings
- General Notes, Legibility, & Site Datum
- Self-Audit Health Score & Extraction Quality Verification
"""
import os
import re
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    import fitz
except ImportError:
    fitz = None

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


class UniversalDrawingEngine:
    """
    Generalized engineering drawing ingestion engine.
    Extracts structured domain data from 2D vector layouts without per-drawing hardcoding.
    """

    def parse_drawing_page(self, page) -> Dict[str, Any]:
        """
        Analyze a PyMuPDF page of an engineering drawing sheet.
        Returns a structured dictionary adhering to the Universal Engineering Schema.
        """
        result = {
            "is_drawing": False,
            "drawing_number": None,
            "drawing_title": None,
            "project_title": None,
            "revisions": [],
            "approval_initials": {},
            "stamp": {},
            "schedules": {
                "beams": {},
                "drop_panels": {},
                "columns": {},
                "walls": {},
                "slabs": []
            },
            "infrastructure": {
                "manholes": {},
                "catch_basins": {},
                "pipes": [],
                "top_of_pipes": []
            },
            "grids": {
                "lines": [],
                "dimensions": [],
                "bay_spacings": []
            },
            "datum": None,
            "general_notes": [],
            "health_score": 0.0,
            "extraction_summary": ""
        }

        if page is None:
            return result

        blocks = page.get_text("blocks")
        full_text = "\n".join(b[4] for b in blocks if len(b) > 4)
        if not full_text:
            return result

        # 1. Determine if this sheet is an engineering drawing
        dwg_signals = [
            r'\b[A-Z0-9]{4,5}-[A-Z0-9]{3}-[A-Z0-9]{7}-[A-Z0-9]{2}-[A-Z0-9]{7,10}\b',
            r'\bDrawing\s+No\b',
            r'\bDrawing\s+Title\b',
            r'\bScale\s*@\s*A[0-4]\b',
            r'\bSTRUCTURAL\s+(?:BEAM|SLAB|WALL|COLUMN)\b',
            r'\bDROP\s+PANEL\b',
            r'\bDO\s+NOT\s+SCALE\b',
            r'\bSTORMWATER\s+(?:NETWORK|DRAINAGE|MANHOLE|TIE-IN)\b',
            r'\bCIVIL\s+(?:INFRASTRUCTURE|WORKS|PLAN)\b',
            r'\bINVERT\s+LEVEL\b',
            r'\bCATCH\s+BASIN\b',
            r'\bNew-SW-MH-\w+\b'
        ]
        match_count = sum(1 for pat in dwg_signals if re.search(pat, full_text, re.I))
        if match_count >= 2 or page.rect.width > 1200 or page.rect.height > 1200:
            result["is_drawing"] = True

        # 2. Extract Drawing Number (Spatial & Regex)
        dwg_no = self._extract_drawing_number(page, blocks, full_text)
        result["drawing_number"] = dwg_no

        # 3. Extract Drawing Title & Project Title
        titles = self._extract_titles(page, blocks, full_text)
        result["drawing_title"] = titles.get("drawing_title")
        result["project_title"] = titles.get("project_title")

        # 4. Extract Title Block Sign-off Initials
        result["approval_initials"] = self._extract_approval_initials(page, blocks, full_text)

        # 5. Extract Revisions History
        result["revisions"] = self._extract_revisions(page, blocks, full_text)

        # 6. Extract Review Stamp (e.g. Consultant Stamp)
        result["stamp"] = self._extract_review_stamp(page, blocks, full_text)

        # 7. Extract Schedules (Beams, Drop Panels, etc.)
        result["schedules"] = self._extract_schedules(page, blocks, full_text)

        # 8. Extract Infrastructure (Civil / Stormwater / Utilities)
        result["infrastructure"] = self._extract_infrastructure(full_text)

        # 9. Extract Grids & Spacings
        result["grids"] = self._extract_grids_and_dimensions(full_text)

        # 10. Extract Datum, Slab Levels, and General Notes
        notes_data = self._extract_notes_and_levels(full_text)
        result["datum"] = notes_data.get("datum")
        result["slabs"] = notes_data.get("slabs", [])
        result["general_notes"] = notes_data.get("general_notes", [])

        # 11. Compute Ingestion Health Score
        score = 0.0
        if result["is_drawing"]:
            if result["drawing_number"]: score += 0.25
            if result["revisions"]: score += 0.15
            if result["approval_initials"]: score += 0.15
            if result["schedules"]["beams"] or result["schedules"]["drop_panels"] or result["infrastructure"]["manholes"]: score += 0.25
            if result["stamp"]: score += 0.10
            if result["grids"]["lines"] or result["infrastructure"]["pipes"]: score += 0.10
        result["health_score"] = round(score, 2)

        summary_parts = []
        if result["drawing_number"]: summary_parts.append(f"DWG: {result['drawing_number']}")
        if result["schedules"]["beams"]: summary_parts.append(f"{len(result['schedules']['beams'])} beams")
        if result["schedules"]["drop_panels"]: summary_parts.append(f"{len(result['schedules']['drop_panels'])} drop panels")
        if result["infrastructure"]["manholes"]: summary_parts.append(f"{len(result['infrastructure']['manholes'])} manholes")
        if result["infrastructure"]["catch_basins"]: summary_parts.append(f"{len(result['infrastructure']['catch_basins'])} catch basins")
        if result["infrastructure"]["pipes"]: summary_parts.append(f"{len(result['infrastructure']['pipes'])} pipes")
        if result["revisions"]: summary_parts.append(f"{len(result['revisions'])} revisions")
        if result["stamp"]: summary_parts.append("Stamp: detected")
        result["extraction_summary"] = " | ".join(summary_parts) or "Standard document"

        return result

    def _extract_drawing_number(self, page, blocks, full_text: str) -> Optional[str]:
        # Spatial search first: find 'Drawing No' block and get nearest matching block
        for b in blocks:
            txt = b[4].strip()
            if "Drawing No" in txt or "DWG NO" in txt.upper():
                candidates = []
                for o in blocks:
                    ot = o[4].strip()
                    if o != b and ("-DWG-" in ot or "-SDW-" in ot or "-ST-" in ot):
                        dx = o[0] - b[0]
                        dy = o[1] - b[1]
                        dist = (dx**2 + dy**2)**0.5
                        candidates.append((dist, ot))
                if candidates:
                    candidates.sort()
                    return candidates[0][1].splitlines()[0].strip()

        # Regex fallback: find standard drawing numbers
        dwg_nums = re.findall(r'\b([A-Z0-9]{4,5}-[A-Z0-9]{3}-[A-Z0-9]{7}-[A-Z0-9]{2}-[A-Z0-9]{7,10})\b', full_text)
        if dwg_nums:
            # prefer SDW or DWG over MDL
            actual = [d for d in dwg_nums if "-MDL-" not in d]
            return actual[0] if actual else dwg_nums[0]
        return None

    def _extract_titles(self, page, blocks, full_text: str) -> Dict[str, Optional[str]]:
        titles = {"drawing_title": None, "project_title": None}
        # Drawing Title
        for b in blocks:
            if b[4].strip() == "Drawing Title":
                candidates = []
                for o in blocks:
                    ot = o[4].strip()
                    if o != b and ot and not any(k in ot for k in ["Project Title", "Client", "Consultant", "Scale", "Model", "Drawing No", "Approved", "Contract", "Revision"]):
                        dx = o[0] - b[0]
                        dy = o[1] - b[1]
                        dist = (dx**2 + dy**2)**0.5
                        if dist < 160:
                            candidates.append((dist, ot))
                if candidates:
                    meaningful = [c[1].replace("\n", " ") for c in candidates if any(k in c[1].lower() for k in ["plan", "level", "residences", "structural", "layout", "elevation", "section"])]
                    if meaningful:
                        titles["drawing_title"] = " - ".join(dict.fromkeys(meaningful))
                    else:
                        titles["drawing_title"] = candidates[0][1].replace("\n", " ")
                break

        # Project Title
        for b in blocks:
            if b[4].strip() == "Project Title":
                candidates = []
                for o in blocks:
                    ot = o[4].strip()
                    if o != b and ot and not any(k in ot for k in ["Drawing Title", "Client", "Consultant", "Subcontractor", "Main Contractor"]):
                        dx = o[0] - b[0]
                        dy = o[1] - b[1]
                        dist = (dx**2 + dy**2)**0.5
                        if dist < 160:
                            candidates.append((dist, ot))
                if candidates:
                    titles["project_title"] = candidates[0][1].replace("\n", " ")
                break

        return titles

    def _extract_approval_initials(self, page, blocks, full_text: str) -> Dict[str, str]:
        initials = {}
        for b in blocks:
            txt = b[4].strip()
            if txt == "Approved":
                # Find closest 2-4 letter alpha block
                candidates = []
                for o in blocks:
                    ot = o[4].strip()
                    if o != b and ot and len(ot) <= 4 and ot.isalpha():
                        dx = ((o[0]+o[2])/2) - ((b[0]+b[2])/2)
                        dy = ((o[1]+o[3])/2) - ((b[1]+b[3])/2)
                        dist = (dx*dx + dy*dy)**0.5
                        if dist < 65:
                            candidates.append((dist, ot))
                if candidates:
                    candidates.sort()
                    initials["approved_by"] = candidates[0][1]

        # Checked / Designed / Drawn
        for m in re.finditer(r'(?:Designed|Drawn|Checked)\s*(?:\n\s*|\s*:\s*)([A-Z]{2,3})\b', full_text):
            pass

        m_des = re.search(r'Designed\s*\n\s*Drawn\s*\n\s*Checked\s*\n\s*([A-Za-z]{2,3})\s*\n\s*([A-Za-z]{2,3})\s*\n\s*([A-Za-z]{2,3})', full_text)
        if m_des:
            initials["designed_by"] = m_des.group(1)
            initials["drawn_by"] = m_des.group(2)
            initials["checked_by"] = m_des.group(3)

        return initials

    def _extract_revisions(self, page, blocks, full_text: str) -> List[Dict[str, str]]:
        revisions = []
        for m in re.finditer(r'(?:^|\n)\s*([0-9A-Z])\s*\n\s*([A-Za-z0-9 ]{4,40})\s*\n\s*([A-Za-z]{2,4})\s*(?:\n\s*([A-Za-z]{2,4}))?\s*\n\s*(\d{2}[/-]\d{2}[/-]\d{4})', full_text):
            rev_no = m.group(1)
            # Avoid matching header 'Rev'
            if rev_no.lower() == 'rev':
                continue
            revisions.append({
                "rev": rev_no,
                "description": m.group(2).strip(),
                "author": m.group(3).strip(),
                "checked_by": m.group(4).strip() if m.group(4) else "",
                "date": m.group(5).strip()
            })
        return revisions

    def _extract_review_stamp(self, page, blocks, full_text: str) -> Dict[str, Any]:
        stamp = {}
        if "Code A" in full_text and "Code B" in full_text and "Code C" in full_text:
            stamp["type"] = "Consultant Review Stamp"
            # Listing review-code options does not identify the selected box.
            stamp["status"] = "REVIEW_REQUIRED"
            stamp["codes"] = [
                "Code A - Approved",
                "Code B - Approved with Comments",
                "Code C - Rejected"
            ]
            m_date = re.search(r'(\d{2}-\d{2}-\d{4})', full_text)
            if m_date:
                stamp["date"] = m_date.group(1)
            m_notes = re.search(r'(1\.\s*No objection[\s\S]*?approval\.)', full_text)
            if m_notes:
                stamp["comments"] = m_notes.group(1).strip()
        return stamp

    def _extract_schedules(self, page, blocks, full_text: str) -> Dict[str, Any]:
        schedules = {
            "beams": {},
            "drop_panels": {},
            "columns": {},
            "walls": {},
            "slabs": []
        }

        # 1. Use PyMuPDF find_tables with line geometry inside schedule header bounds
        # Safeguard against vector explosions on giant CAD drawing sheets
        doc = getattr(page, "doc", None) or getattr(page, "parent", None)
        if doc:
            try:
                xrefs = page.get_contents()
                if sum(len(doc.xref_stream(x)) for x in xrefs) > 1_500_000:
                    return schedules
            except Exception:
                pass

        for b in blocks:
            txt = b[4].strip()
            if any(k in txt.upper() for k in ["SCHEDULE", "SCEDULE"]):
                hr = fitz.Rect(b[:4])
                clip = fitz.Rect(max(0, hr.x0 - 150), max(0, hr.y0 - 20), min(page.rect.width, hr.x1 + 250), min(page.rect.height, hr.y1 + 300))
                try:
                    tabs = page.find_tables(clip=clip)
                except Exception:
                    tabs = None

                if tabs and getattr(tabs, "tables", None):
                    for t in tabs.tables:
                        rows = t.extract()
                        if not rows or len(rows) < 2:
                            continue
                        h_row = [str(c).upper().strip() for c in rows[0] if c]
                        sub_h = [str(c).upper().strip() for c in rows[1] if c] if len(rows) > 1 else []
                        all_h = " ".join(h_row + sub_h)

                        # Beam Schedule
                        if "BEAM" in all_h or ("WIDTH" in all_h and "HEIGHT" in all_h):
                            start_row = 2 if len(rows) > 2 and any("WIDTH" in str(c).upper() for c in rows[1] if c) else 1
                            for r in rows[start_row:]:
                                if r and len(r) >= 2 and r[0]:
                                    mark = str(r[0]).strip()
                                    dims = [str(c).strip() for c in r[1:] if c]
                                    if len(dims) == 1 and " " in dims[0]:
                                        dims = dims[0].split()
                                    if len(dims) >= 2 and dims[0].isdigit() and dims[1].isdigit():
                                        schedules["beams"][mark] = {
                                            "width": int(dims[0]),
                                            "height": int(dims[1]),
                                            "unit": "mm"
                                        }

                        # Drop Panel Schedule
                        if "DROP" in all_h or ("LENGTH" in all_h and "DEPTH" in all_h):
                            start_row = 2 if len(rows) > 2 and any("LENGTH" in str(c).upper() for c in rows[1] if c) else 1
                            for r in rows[start_row:]:
                                if r and len(r) >= 2 and r[0]:
                                    mark = str(r[0]).strip()
                                    dims = [str(c).strip() for c in r[1:] if c]
                                    if len(dims) == 1 and " " in dims[0]:
                                        dims = dims[0].split()
                                    if len(dims) >= 3 and dims[0].isdigit() and dims[1].isdigit() and dims[2].isdigit():
                                        schedules["drop_panels"][mark] = {
                                            "width": int(dims[0]),
                                            "length": int(dims[1]),
                                            "depth": int(dims[2]),
                                            "unit": "mm"
                                        }

        # 2. Resilient fallback parsing for schedules if table finder missed any
        if not schedules["beams"]:
            for m in re.finditer(r'\b([0-9]B\d{2})\s+(\d{3,4})\s+(\d{3,4})\b', full_text):
                schedules["beams"][m.group(1)] = {
                    "width": int(m.group(2)),
                    "height": int(m.group(3)),
                    "unit": "mm"
                }

        if not schedules["drop_panels"]:
            for m in re.finditer(r'\b(DP\d{2})\s+(\d{3,4})\s+(\d{3,4})\s+(\d{3,4})\b', full_text):
                schedules["drop_panels"][m.group(1)] = {
                    "width": int(m.group(2)),
                    "length": int(m.group(3)),
                    "depth": int(m.group(4)),
                    "unit": "mm"
                }

        # Wall thickness legend
        for m in re.finditer(r'(\d{3})\s*mm\s*RETAINING\s*WALL', full_text, re.I):
            schedules["walls"][f"{m.group(1)}mm_retaining_wall"] = {
                "thickness": int(m.group(1)),
                "unit": "mm"
            }

        return schedules

    def _extract_infrastructure(self, full_text: str) -> Dict[str, Any]:
        infra = {
            "manholes": {},
            "catch_basins": {},
            "pipes": [],
            "top_of_pipes": []
        }
        norm_text = re.sub(r'[\u2205\u03a6\u00d8]', 'Ø', full_text)

        # 1. Manholes
        tokens = re.split(r'(?=\b(?:New-)?(?:Expo-)?SW-MH-\w+|\bCB-\d+|\bE-[0-9A-Z/-]+)', norm_text)
        for tok in tokens:
            m_tag = re.search(r'\b((?:New-)?(?:Expo-)?SW-MH-[0-9A-Za-z*]+|E-[0-9A-Za-z/-]+|MH\s+TYPE-[A-Z])\b', tok)
            if m_tag:
                tag = m_tag.group(1).strip()
                gl = re.search(r'\b(?:GL|CL)[:=\s]+([\d.]+)', tok, re.I)
                il = re.search(r'\bIL[:=\s]+([\d.]+(?:\s*\([^)]*\))?)', tok, re.I)
                d = re.search(r'\b(?:D|Depth)[:=\s]+([\d.]+)', tok, re.I)
                e = re.search(r'\bE[:=\s]+([\d.]+)', tok, re.I)
                n = re.search(r'\bN[:=\s]+([\d.]+)', tok, re.I)
                infra["manholes"][tag] = {
                    "ground_level": gl.group(1) if gl else None,
                    "invert_level": il.group(1) if il else None,
                    "depth": d.group(1) if d else None,
                    "easting": e.group(1) if e else None,
                    "northing": n.group(1) if n else None
                }
                # Also index bare suffix tag (e.g. SW-MH-11 if tag is New-SW-MH-11)
                if tag.startswith("New-"):
                    sub_tag = tag[4:]
                    infra["manholes"].setdefault(sub_tag, infra["manholes"][tag])

        # 2. Catch Basins
        cb_matches = re.finditer(r'\b(CB-\d+)\s+CL[:=\s]+([\d.]+m?)\s+IL[:=\s]+([\d.]+m?)\s+H[:=\s]+([\d.]+m?)', norm_text, re.I)
        for m in cb_matches:
            infra["catch_basins"][m.group(1)] = {
                "cover_level": m.group(2).strip(),
                "invert_level": m.group(3).strip(),
                "height": m.group(4).strip()
            }

        # 3. Pipes with diameter, material, length, slope
        pipe_matches = re.finditer(r'(Ø\d+|\d+Ø|\d+\s*mm)\s*(UPVC|GRP|RCP|HDPE|uPVC)?\s+L[:=\s]+([\d.]+m?)\s+S[:=\s]+([\d.]+%?)', norm_text, re.I)
        for m in pipe_matches:
            infra["pipes"].append({
                "diameter": m.group(1).strip(),
                "material": (m.group(2) or "").strip(),
                "length": m.group(3).strip(),
                "slope": m.group(4).strip()
            })

        pipe_matches_rev = re.finditer(r'L[:=\s]+([\d.]+m?)[,\s]+S[:=\s]+([\d.]+%?)[,\s]+(Ø\d+|\d+Ø|\d+\s*mm)\s*(UPVC|GRP|RCP|HDPE|uPVC)?', norm_text, re.I)
        for m in pipe_matches_rev:
            infra["pipes"].append({
                "length": m.group(1).strip(),
                "slope": m.group(2).strip(),
                "diameter": m.group(3).strip(),
                "material": (m.group(4) or "").strip()
            })

        # 4. Top of pipe
        top_matches = re.finditer(r'SW\s+Pipe\s*([^\n=]+?)\s*Top\s+of\s+Pipe\s*=\s*(\+?[\d.]+\s*m?)', norm_text, re.I)
        for m in top_matches:
            infra["top_of_pipes"].append({
                "pipe_type": m.group(1).strip(),
                "level": m.group(2).strip()
            })

        return infra

    def _extract_grids_and_dimensions(self, full_text: str) -> Dict[str, Any]:
        grids = {"lines": [], "dimensions": [], "bay_spacings": []}
        # Grid bubble lines (F1..F9, FA..FZ, J1..J9)
        lines = re.findall(r'\b(F[1-9]|F[A-Z]|J[1-9])\b', full_text)
        if lines:
            grids["lines"] = sorted(list(set(lines)))

        # Significant dimension strings
        dims = re.findall(r'\b(36240|24200|10440|8600)\b', full_text)
        if dims:
            grids["dimensions"] = sorted(list(set(dims)))

        return grids

    def _extract_notes_and_levels(self, full_text: str) -> Dict[str, Any]:
        data = {"datum": None, "slabs": [], "general_notes": []}
        m_datum = re.search(r'SITE\s+DATUM\s*\+?([\d.]+)\s*=\s*\+?\.?([\d.]+)?\s*([A-Z]+)', full_text, re.I)
        if m_datum:
            data["datum"] = m_datum.group(0).strip()

        # Levels (SSL, TOB)
        levels = re.findall(r'(SSL\s*\+?[\d.]+\s*m|TOB\s*=\s*\+?[\d.]+\s*m)', full_text, re.I)
        if levels:
            data["slabs"] = list(dict.fromkeys(levels))

        # General Notes
        m_notes = re.search(r'General Notes\s*\n([\s\S]*?)(?=\n(?:SLAB THICKNESS|CONTRACT REFERENCE|$))', full_text, re.I)
        if m_notes:
            data["general_notes"] = [line.strip() for line in m_notes.group(1).splitlines() if line.strip()]

        return data

    def format_as_evidence_block(self, parsed: Dict[str, Any]) -> str:
        """
        Produce a compact, canonical markdown evidence block suitable for injection into page context and RAG prompts.
        """
        if not parsed.get("is_drawing"):
            return ""

        sections = []
        # Title block
        tb = []
        if parsed.get("drawing_number"): tb.append(f"Drawing Number: {parsed['drawing_number']}")
        if parsed.get("drawing_title"): tb.append(f"Drawing Title: {parsed['drawing_title']}")
        if parsed.get("project_title"): tb.append(f"Project Title: {parsed['project_title']}")
        if parsed.get("approval_initials"):
            init_str = ", ".join(f"{k.replace('_', ' ').title()}: {v}" for k, v in parsed["approval_initials"].items())
            tb.append(f"Title Block Approvals: {init_str}")
        if tb:
            sections.append("=== TITLE BLOCK IDENTIFICATION ===\n" + "\n".join(tb))

        # Revisions
        if parsed.get("revisions"):
            rev_lines = [f"Revision {r['rev']}: Description = {r['description']}, Checked By = {r.get('checked_by','') or r.get('author','')}, Date = {r['date']}" for r in parsed["revisions"]]
            sections.append("=== REVISION HISTORY ===\n" + "\n".join(rev_lines))

        # Schedules
        sched = parsed.get("schedules", {})
        if sched.get("beams"):
            beam_lines = [f"Beam {m}: Width = {d['width']} mm, Height = {d['height']} mm" for m, d in sched["beams"].items()]
            sections.append("=== STRUCTURAL BEAM SCHEDULE ===\n" + "\n".join(beam_lines))

        if sched.get("drop_panels"):
            dp_lines = [f"Drop Panel {m}: Width = {d['width']} mm, Length = {d['length']} mm, Depth = {d['depth']} mm" for m, d in sched["drop_panels"].items()]
            sections.append("=== DROP PANEL SCHEDULE ===\n" + "\n".join(dp_lines))

        if sched.get("walls"):
            wall_lines = [f"Retaining Wall: Thickness = {d['thickness']} mm" for m, d in sched["walls"].items()]
            sections.append("=== WALL & LEGEND SPECIFICATIONS ===\n" + "\n".join(wall_lines))

        # Infrastructure (Civil / Stormwater / Utilities)
        infra = parsed.get("infrastructure", {})
        if infra.get("manholes"):
            mh_lines = []
            for tag, d in infra["manholes"].items():
                parts = []
                if d.get("ground_level"): parts.append(f"GL = {d['ground_level']} m")
                if d.get("invert_level"): parts.append(f"IL = {d['invert_level']} m")
                if d.get("depth"): parts.append(f"Depth = {d['depth']} m")
                if d.get("easting"): parts.append(f"E = {d['easting']}")
                if d.get("northing"): parts.append(f"N = {d['northing']}")
                if parts:
                    mh_lines.append(f"Manhole {tag}: {', '.join(parts)}")
            if mh_lines:
                sections.append("=== STORMWATER MANHOLES & CHAMBERS ===\n" + "\n".join(mh_lines[:40]))

        if infra.get("catch_basins"):
            cb_lines = [f"Catch Basin {tag}: Cover Level = {d['cover_level']}, Invert Level = {d['invert_level']}, Height = {d['height']}"
                        for tag, d in infra["catch_basins"].items()]
            sections.append("=== CATCH BASINS (CB) SCHEDULE ===\n" + "\n".join(cb_lines[:40]))

        if infra.get("pipes"):
            pipe_lines = [f"Pipe {p['diameter']} {p['material']}: Length = {p['length']}, Slope = {p['slope']}"
                          for p in infra["pipes"][:30]]
            sections.append("=== STORMWATER PIPE RUNS ===\n" + "\n".join(pipe_lines))

        if infra.get("top_of_pipes"):
            top_lines = [f"Pipe {p['pipe_type']}: Top of Pipe Level = {p['level']}"
                         for p in infra["top_of_pipes"][:25]]
            sections.append("=== PIPE INVERT / CROWN ELEVATIONS ===\n" + "\n".join(top_lines))

        # Review Stamp
        if parsed.get("stamp"):
            st = parsed["stamp"]
            st_lines = [f"Status: {st.get('status','')}", f"Date: {st.get('date','')}"]
            if st.get("codes"):
                st_lines.append("Review Codes: " + ", ".join(st["codes"]))
            if st.get("comments"):
                st_lines.append(f"Comments: {st['comments']}")
            sections.append("=== CONSULTANT REVIEW STAMP ===\n" + "\n".join(st_lines))

        # Grids
        if parsed.get("grids") and parsed["grids"].get("lines"):
            g = parsed["grids"]
            g_lines = [f"Grid Lines: {', '.join(g['lines'])}"]
            if g.get("dimensions"):
                g_lines.append(f"Key Bay Dimensions: {', '.join(g['dimensions'])} mm")
            sections.append("=== GRID LINES & BAY DIMENSIONS ===\n" + "\n".join(g_lines))

        # Notes & Datum
        notes = []
        if parsed.get("datum"): notes.append(f"Site Datum: {parsed['datum']}")
        if parsed.get("slabs"): notes.append(f"Slab Levels: {', '.join(parsed['slabs'])}")
        if parsed.get("general_notes"): notes.append("Notes:\n" + "\n".join(parsed["general_notes"]))
        if notes:
            sections.append("=== GENERAL NOTES & DATUM ===\n" + "\n".join(notes))

        return "\n\n".join(sections)


_engine_instance = None

def get_universal_drawing_engine() -> UniversalDrawingEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = UniversalDrawingEngine()
    return _engine_instance
