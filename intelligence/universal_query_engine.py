"""
Universal Query Engine for Expo Design AI.
Dynamic, generalized query resolver that extracts verified engineering data
from ANY uploaded drawing or structured document without hardcoded filenames.
"""
import json
import re
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


def _norm(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', str(s).lower()).strip()


def _valid_doc_meta(doc: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    path = str(doc.get('path') or '')
    try:
        index_path = Path(path + '.index.json')
        if not index_path.exists():
            return None, None
        meta = json.loads(index_path.read_text(encoding='utf-8'))
        if meta.get('truncated') or meta.get('processing_complete') is False:
            return None, None
        expected_hash = meta.get('source_sha256')
        if expected_hash:
            with open(path, 'rb') as f:
                if hashlib.file_digest(f, 'sha256').hexdigest().casefold() != str(expected_hash).casefold():
                    return None, None
        return doc, meta
    except Exception:
        return None, None


def universal_query_answer(question: str, documents: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Generalized resolver for arbitrary uploaded engineering drawings and structured documents.
    """
    q = _norm(question)
    
    for doc in documents:
        valid_doc, meta = _valid_doc_meta(doc)
        if not valid_doc or not meta:
            continue
            
        filename = valid_doc.get("filename", "")
        pages = meta.get("pages", [])
        if not pages:
            continue

        for page_data in pages:
            page_no = page_data.get("page", 1)
            cite = f"[SOURCE: {filename} | PAGE {page_no}]"
            dwg = page_data.get("drawing_schema", {})
            infra = dwg.get("infrastructure", {})

            # 1. Civil: Stormwater Manholes / Chambers
            # Look for specific manhole tags mentioned in question
            m_mh = re.search(r'\b((?:New-)?(?:Expo-)?SW-MH-[0-9A-Za-z*]+|E-[0-9A-Za-z/-]+)\b', question, re.I)
            if m_mh:
                mh_tag = m_mh.group(1).strip()
                manholes = infra.get("manholes", {})
                # Try direct tag or normalized tag
                target_mh = manholes.get(mh_tag) or manholes.get(mh_tag.replace("New-", ""))
                if target_mh:
                    parts = []
                    if target_mh.get("ground_level"): parts.append(f"GL = {target_mh['ground_level']} m")
                    if target_mh.get("invert_level"): parts.append(f"IL = {target_mh['invert_level']} m")
                    if target_mh.get("depth"): parts.append(f"Depth = {target_mh['depth']} m")
                    if target_mh.get("easting"): parts.append(f"Easting = {target_mh['easting']}")
                    if target_mh.get("northing"): parts.append(f"Northing = {target_mh['northing']}")
                    
                    if parts:
                        answer = f"**Manhole {mh_tag}:** {', '.join(parts)}. {cite}"
                        return {
                            "status": "SUCCESS",
                            "answer": answer,
                            "sources": [{"source": filename, "page": page_no}]
                        }

            # 2. Civil: Catch Basins (CB)
            m_cb = re.search(r'\b(CB-\d+)\b', question, re.I)
            if m_cb:
                cb_tag = m_cb.group(1).upper()
                cbs = infra.get("catch_basins", {})
                target_cb = cbs.get(cb_tag)
                if target_cb:
                    answer = f"**Catch Basin {cb_tag}:** Cover Level = {target_cb['cover_level']}, Invert Level = {target_cb['invert_level']}, Height = {target_cb['height']}. {cite}"
                    return {
                        "status": "SUCCESS",
                        "answer": answer,
                        "sources": [{"source": filename, "page": page_no}]
                    }

            # 3. Civil: Pipes & Slopes
            if "pipe" in q and ("slope" in q or "diameter" in q or "length" in q):
                pipes = infra.get("pipes", [])
                # If specific length or diameter mentioned
                for p in pipes:
                    d_clean = _norm(p.get("diameter", ""))
                    l_clean = _norm(p.get("length", ""))
                    if (d_clean and d_clean in q) or (l_clean and l_clean in q):
                        answer = f"**Pipe {p['diameter']} {p['material']}:** Length = {p['length']}, Slope = {p['slope']}. {cite}"
                        return {
                            "status": "SUCCESS",
                            "answer": answer,
                            "sources": [{"source": filename, "page": page_no}]
                        }

            # 4. Structural: Beams
            m_beam = re.search(r'\b([0-9][A-Z]\d{2})\b', question, re.I)
            if m_beam:
                beam_tag = m_beam.group(1).upper()
                beams = dwg.get("schedules", {}).get("beams", {})
                if beam_tag in beams:
                    b_info = beams[beam_tag]
                    answer = f"**Beam {beam_tag}:** {b_info['width']} mm wide × {b_info['height']} mm high. {cite}"
                    return {
                        "status": "SUCCESS",
                        "answer": answer,
                        "sources": [{"source": filename, "page": page_no}]
                    }

            # 5. Structural: Drop Panels
            m_dp = re.search(r'\b(DP\d{2})\b', question, re.I)
            if m_dp:
                dp_tag = m_dp.group(1).upper()
                dps = dwg.get("schedules", {}).get("drop_panels", {})
                if dp_tag in dps:
                    dp_info = dps[dp_tag]
                    answer = f"**Drop Panel {dp_tag}:** {dp_info['width']} mm × {dp_info['length']} mm × {dp_info['depth']} mm. {cite}"
                    return {
                        "status": "SUCCESS",
                        "answer": answer,
                        "sources": [{"source": filename, "page": page_no}]
                    }

            # 6. General Notes Queries
            if ("general note" in q or "general notes" in q or "notes state" in q) and dwg.get("general_notes"):
                notes = dwg["general_notes"]
                # If asking about specific topic (e.g. pipe cover, dimension, projection)
                for note in notes:
                    n_norm = _norm(note)
                    if any(w in n_norm and w in q for w in ["cover", "encasement", "dimension", "scaled", "projection", "detention", "dltm"]):
                        answer = f"**General Note:** {note}. {cite}"
                        return {
                            "status": "SUCCESS",
                            "answer": answer,
                            "sources": [{"source": filename, "page": page_no}]
                        }
                # Return all notes if general request
                if "all" in q or "what are the notes" in q:
                    formatted_notes = "\n".join(f"- {n}" for n in notes)
                    answer = f"**General Notes:**\n{formatted_notes}\n\n{cite}"
                    return {
                        "status": "SUCCESS",
                        "answer": answer,
                        "sources": [{"source": filename, "page": page_no}]
                    }

    return None
