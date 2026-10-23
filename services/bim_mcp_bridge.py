"""Direct Model Context Protocol (MCP) Bridge linking BIM Models to Qwen AI Model.

Provides full programmatic inspection, semantic search, quantity takeoff, spatial reasoning,
and 3D viewer control over IFC models indexed in SQLite (data/ifc_index.db).
Exposes tools for both standard MCP servers (mcp.server.mcpserver) and Ollama function-calling agent loops.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional
import httpx

from config import resolve_role
from services.ifc_index import connect
from services import ifc_query as Q

logger = logging.getLogger("bim_mcp_bridge")

# Synonyms for natural language queries against BIM element names and types
SYNONYM_MAP: Dict[str, List[str]] = {
    "light": ["%light%", "%lighting%", "%luminaire%", "%lamp%"],
    "lights": ["%light%", "%lighting%", "%luminaire%", "%lamp%"],
    "street light": ["%street%light%", "%lighting%column%", "%lighting_structure%"],
    "street lights": ["%street%light%", "%lighting%column%", "%lighting_structure%"],
    "street lighting": ["%street%light%", "%lighting%column%", "%lighting_structure%"],
    "lighting": ["%lighting%", "%luminaire%", "%light%"],
    "luminaire": ["%luminaire%"],
    "luminaires": ["%luminaire%"],
    "pole": ["%pole%", "%lighting_column%"],
    "poles": ["%pole%", "%lighting_column%"],
    "plant": ["%palm%", "%tree%", "%shrub%", "%canopy%", "%ground cover%", "%plant%", "%vegetation%"],
    "plants": ["%palm%", "%tree%", "%shrub%", "%canopy%", "%ground cover%", "%plant%", "%vegetation%"],
    "tree": ["%tree%", "%canopy%"],
    "trees": ["%tree%", "%canopy%"],
    "palm": ["%palm%"],
    "palms": ["%palm%"],
    "shrub": ["%shrub%"],
    "shrubs": ["%shrub%"],
    "vegetation": ["%palm%", "%tree%", "%shrub%", "%canopy%", "%ground cover%", "%vegetation%"],
    "landscape": ["%palm%", "%tree%", "%shrub%", "%canopy%", "%ground cover%", "%landscape%"],
    "column": ["%column%", "%pillar%"],
    "columns": ["%column%", "%pillar%"],
    "wall": ["%wall%"],
    "walls": ["%wall%"],
    "door": ["%door%"],
    "doors": ["%door%"],
    "window": ["%window%", "%glazing%"],
    "windows": ["%window%", "%glazing%"],
    "slab": ["%slab%", "%floor%"],
    "slabs": ["%slab%", "%floor%"],
    "floor": ["%floor%", "%slab%"],
    "floors": ["%floor%", "%slab%"],
    "beam": ["%beam%", "%girder%", "%joist%"],
    "beams": ["%beam%", "%girder%", "%joist%"],
    "pipe": ["%pipe%", "%fitting%"],
    "pipes": ["%pipe%", "%fitting%"],
    "duct": ["%duct%", "%damper%"],
    "ducts": ["%duct%", "%damper%"],
    "stair": ["%stair%"],
    "stairs": ["%stair%"],
    "railing": ["%railing%", "%balustrade%"],
    "railings": ["%railing%", "%balustrade%"],
    "furniture": ["%furnish%", "%table%", "%chair%", "%desk%"],
    "road": ["%pav%", "%paving%", "%vehicular%", "%curb%", "%street%", "%road%", "%loop%"],
    "roads": ["%pav%", "%paving%", "%vehicular%", "%curb%", "%street%", "%road%", "%loop%"],
    "road surface": ["%pav%", "%paving%", "%vehicular%", "%curb%", "%street%", "%road%", "%loop%"],
    "road surfaces": ["%pav%", "%paving%", "%vehicular%", "%curb%", "%street%", "%road%", "%loop%"],
    "surface": ["%pav%", "%paving%", "%curb%", "%slab%"],
    "surfaces": ["%pav%", "%paving%", "%curb%", "%slab%"],
    "pavement": ["%pav%", "%paving%"],
    "pavements": ["%pav%", "%paving%"],
    "paving": ["%pav%", "%paving%"],
    "curb": ["%curb%"],
    "curbs": ["%curb%"],
    "asphalt": ["%pav%", "%asphalt%", "%road%"]
}

CLASS_MAP: Dict[str, List[str]] = {
    "road": ["IFCSLAB", "IFCBUILDINGELEMENTPROXY"],
    "roads": ["IFCSLAB", "IFCBUILDINGELEMENTPROXY"],
    "road surface": ["IFCSLAB", "IFCBUILDINGELEMENTPROXY"],
    "road surfaces": ["IFCSLAB", "IFCBUILDINGELEMENTPROXY"],
    "surface": ["IFCSLAB", "IFCBUILDINGELEMENTPROXY"],
    "surfaces": ["IFCSLAB", "IFCBUILDINGELEMENTPROXY"],
    "pavement": ["IFCSLAB", "IFCBUILDINGELEMENTPROXY"],
    "pavements": ["IFCSLAB", "IFCBUILDINGELEMENTPROXY"],
    "paving": ["IFCSLAB", "IFCBUILDINGELEMENTPROXY"],
    "curb": ["IFCSLAB", "IFCBUILDINGELEMENTPROXY"],
    "curbs": ["IFCSLAB", "IFCBUILDINGELEMENTPROXY"],
    "asphalt": ["IFCSLAB", "IFCBUILDINGELEMENTPROXY"],
    "light": ["IFCBUILDINGELEMENTPROXY", "IFCFLOWTERMINAL"],
    "lights": ["IFCBUILDINGELEMENTPROXY", "IFCFLOWTERMINAL"],
    "street light": ["IFCBUILDINGELEMENTPROXY"],
    "street lights": ["IFCBUILDINGELEMENTPROXY"],
    "street lighting": ["IFCBUILDINGELEMENTPROXY"],
    "lighting": ["IFCBUILDINGELEMENTPROXY", "IFCFLOWTERMINAL"],
    "luminaire": ["IFCBUILDINGELEMENTPROXY", "IFCFLOWTERMINAL"],
    "plant": ["IFCBUILDINGELEMENTPROXY"],
    "plants": ["IFCBUILDINGELEMENTPROXY"],
    "tree": ["IFCBUILDINGELEMENTPROXY"],
    "trees": ["IFCBUILDINGELEMENTPROXY"],
    "palm": ["IFCBUILDINGELEMENTPROXY"],
    "palms": ["IFCBUILDINGELEMENTPROXY"],
    "shrub": ["IFCBUILDINGELEMENTPROXY"],
    "shrubs": ["IFCBUILDINGELEMENTPROXY"],
    "vegetation": ["IFCBUILDINGELEMENTPROXY"],
    "column": ["IFCCOLUMN"],
    "columns": ["IFCCOLUMN"],
    "wall": ["IFCWALL", "IFCWALLSTANDARDCASE"],
    "walls": ["IFCWALL", "IFCWALLSTANDARDCASE"],
    "door": ["IFCDOOR"],
    "doors": ["IFCDOOR"],
    "window": ["IFCWINDOW"],
    "windows": ["IFCWINDOW"],
    "slab": ["IFCSLAB"],
    "slabs": ["IFCSLAB"],
    "floor": ["IFCSLAB"],
    "floors": ["IFCSLAB"],
    "beam": ["IFCBEAM"],
    "beams": ["IFCBEAM"],
    "space": ["IFCSPACE"],
    "spaces": ["IFCSPACE"],
    "room": ["IFCSPACE"],
    "rooms": ["IFCSPACE"],
    "stair": ["IFCSTAIR", "IFCSTAIRFLIGHT"],
    "stairs": ["IFCSTAIR", "IFCSTAIRFLIGHT"],
    "railing": ["IFCRAILING"],
    "railings": ["IFCRAILING"],
    "roof": ["IFCROOF"],
    "roofs": ["IFCROOF"],
    "pipe": ["IFCFLOWTERMINAL", "IFCFLOWSEGMENT"],
    "furniture": ["IFCFURNISHINGELEMENT"]
}



def dynamic_semantic_expand(term: str) -> List[str]:
    """Dynamically discover architectural and BIM synonyms for any term using Qwen 3.5 9B.
    Results are cached in SQLite for sub-millisecond retrieval on future calls.
    """
    clean_term = term.strip().lower()
    if not clean_term:
        return []

    # 1. Check in-memory SYNONYM_MAP
    if clean_term in SYNONYM_MAP:
        return SYNONYM_MAP[clean_term]

    # 2. Check SQLite semantic_synonym_cache
    try:
        con = connect()
        cur = con.execute("SELECT synonyms FROM semantic_synonym_cache WHERE term = ?", (clean_term,))
        row = cur.fetchone()
        con.close()
        if row and row[0]:
            syns = json.loads(row[0])
            SYNONYM_MAP[clean_term] = syns
            return syns
    except Exception:
        pass

    # 3. Dynamic Qwen 3.5 9B Reasoning
    try:
        role = resolve_role("chat")
        prompt = (
            f"Given the building/architectural term '{clean_term}', return 3 to 7 likely "
            "BIM/Revit naming abbreviations, IFC class hints, or search tokens (lowercase). "
            "For example: 'road surface' -> ['pav', 'road', 'curb', 'asphalt', 'vehicular']. "
            "Return JSON: {\"synonyms\": [\"term1\", \"term2\", ...]}"
        )
        with httpx.Client(timeout=8.0, trust_env=False) as client:
            resp = client.post(role["base_url"] + "/api/chat", json={
                "model": role["model"],
                "stream": False,
                "think": False,
                "format": "json",
                "options": {"temperature": 0, "num_predict": 120},
                "messages": [{"role": "user", "content": prompt}]
            })
            if resp.status_code == 200:
                data = resp.json()
                content = json.loads(data["message"]["content"])
                raw_syns = content.get("synonyms", [])
                formatted_syns = []
                for s in raw_syns:
                    s_clean = s.strip().lower().replace("%", "")
                    if s_clean and len(s_clean) >= 2:
                        formatted_syns.append(f"%{s_clean}%")
                if not formatted_syns:
                    formatted_syns = [f"%{clean_term}%"]

                try:
                    con = connect()
                    con.execute(
                        "INSERT OR REPLACE INTO semantic_synonym_cache (term, synonyms) VALUES (?, ?)",
                        (clean_term, json.dumps(formatted_syns))
                    )
                    con.commit()
                    con.close()
                except Exception:
                    pass

                SYNONYM_MAP[clean_term] = formatted_syns
                return formatted_syns
    except Exception as e:
        logger.warning(f"Dynamic semantic expansion failed for '{clean_term}': {e}")

    fallback = [f"%{clean_term}%"]
    SYNONYM_MAP[clean_term] = fallback
    return fallback


def discover_types(project: str, keyword: str = "") -> List[Dict[str, Any]]:
    """Discover actual Revit type names and IFC classes in the model for dynamic inspection."""
    con = connect()
    try:
        kw = (keyword or "").strip().lower()
        where = ["project = ?"]
        params = [project]
        if kw:
            syns = dynamic_semantic_expand(kw)
            like_clauses = []
            for t in syns:
                like_clauses.append("(type_name LIKE ? OR name LIKE ? OR category LIKE ?)")
                params.extend([t, t, t])
            where.append(f"({' OR '.join(like_clauses)})")
        where_sql = " AND ".join(where)
        cur = con.execute(
            f"SELECT type_name, cls, count(*) as count "
            f"FROM elements WHERE {where_sql} GROUP BY type_name, cls ORDER BY count DESC LIMIT 30",
            params
        )
        return [{"type_name": r[0], "ifc_class": r[1], "count": r[2]} for r in cur.fetchall()]
    finally:
        con.close()


def search_elements(
    project: str,
    keyword: str = "",
    ifc_class: str = "",
    storey: str = "",
    limit: int = 50
) -> Dict[str, Any]:
    """Search elements in the BIM model database by keyword, class, or storey.
    Performs intelligent semantic term expansion (e.g. 'plant' matches palms, trees, shrubs, canopies).
    """
    con = connect()
    try:
        kw = (keyword or "").strip().lower()
        where_clauses = ["project = ?"]
        params: List[Any] = [project]

        if storey:
            where_clauses.append("storey = ?")
            params.append(storey)

        target_classes = []
        if ifc_class:
            target_classes = [ifc_class.upper()]
        elif kw in CLASS_MAP:
            target_classes = CLASS_MAP[kw]

        if target_classes:
            placeholders = ",".join(["?"] * len(target_classes))
            where_clauses.append(f"cls IN ({placeholders})")
            params.extend(target_classes)

        # Keyword matching with dynamic semantic expansion and fallback
        if kw:
            synonyms = SYNONYM_MAP.get(kw) or dynamic_semantic_expand(kw)
            if synonyms:
                like_clauses = []
                for t in synonyms:
                    like_clauses.append("(name LIKE ? OR type_name LIKE ? OR material LIKE ? OR category LIKE ?)")
                    params.extend([t, t, t, t])
                where_clauses.append(f"({' OR '.join(like_clauses)})")
            else:
                tokens = [t for t in re.split(r'[\s_,-]+', kw) if len(t) >= 2]
                if len(tokens) > 1:
                    token_clauses = []
                    for tok in tokens:
                        token_clauses.append("(name LIKE ? OR type_name LIKE ? OR material LIKE ? OR category LIKE ?)")
                        params.extend([f"%{tok}%", f"%{tok}%", f"%{tok}%", f"%{tok}%"])
                    where_clauses.append(f"({' AND '.join(token_clauses)})")
                else:
                    like = f"%{kw}%"
                    where_clauses.append("(name LIKE ? OR type_name LIKE ? OR material LIKE ? OR category LIKE ?)")
                    params.extend([like, like, like, like])

        where_sql = " AND ".join(where_clauses)

        # 1. Total matching count
        count_cur = con.execute(f"SELECT COUNT(*) FROM elements WHERE {where_sql}", params)
        total_count = count_cur.fetchone()[0]

        # 2. Breakdown by type_name
        type_cur = con.execute(
            f"SELECT COALESCE(type_name, '(unnamed type)') as tname, cls, COUNT(*) as cnt "
            f"FROM elements WHERE {where_sql} GROUP BY type_name, cls ORDER BY cnt DESC LIMIT 20",
            params
        )
        type_breakdown = [{"type_name": r[0], "ifc_class": r[1], "count": r[2]} for r in type_cur.fetchall()]

        # 3. Sample individual elements
        elem_cur = con.execute(
            f"SELECT id, model, step_id, gid, cls, name, type_name, storey, area, volume, length "
            f"FROM elements WHERE {where_sql} LIMIT ?",
            params + [max(1, min(limit, 200))]
        )
        cols = [d[0] for d in elem_cur.description]
        elements = [dict(zip(cols, row)) for row in elem_cur.fetchall()]

        return {
            "success": True,
            "project": project,
            "query_keyword": keyword,
            "ifc_class": ifc_class,
            "storey": storey,
            "total_count": total_count,
            "types_found": len(type_breakdown),
            "top_types": type_breakdown,
            "sample_elements": elements
        }
    finally:
        con.close()


def get_element_details(
    project: str = "",
    element_id: Optional[int] = None,
    guid: Optional[str] = None,
    step_id: Optional[int] = None,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """Get full properties, dimensions, and metadata for a specific BIM element."""
    con = connect()
    try:
        where = []
        params = []
        if element_id is not None:
            where.append("id = ?")
            params.append(element_id)
        if guid:
            where.append("gid = ?")
            params.append(guid)
        if step_id is not None:
            where.append("step_id = ?")
            params.append(step_id)
        if model:
            where.append("model = ?")
            params.append(model)
        if project:
            where.append("project = ?")
            params.append(project)

        if not where:
            return {"success": False, "error": "Specify element_id, guid, or step_id"}

        cur = con.execute(f"SELECT * FROM elements WHERE {' AND '.join(where)} LIMIT 1", params)
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": "Element not found"}

        cols = [d[0] for d in cur.description]
        elem = dict(zip(cols, row))
        eid = elem["id"]

        # Fetch all property sets
        pcur = con.execute("SELECT pset, name, value FROM props WHERE element_id = ? ORDER BY pset, name", (eid,))
        psets: Dict[str, Dict[str, str]] = {}
        for pset, name, val in pcur.fetchall():
            if pset not in psets:
                psets[pset] = {}
            psets[pset][name] = val

        elem["property_sets"] = psets
        return {"success": True, "element": elem}
    finally:
        con.close()


def spatial_summary(project: str) -> Dict[str, Any]:
    """Return building spatial hierarchy with storeys, elevations, and element distribution."""
    storeys_data = Q.storeys(project)
    summary_data = Q.summary(project)
    return {
        "success": True,
        "project": project,
        "storeys": storeys_data,
        "total_storeys": len(storeys_data),
        "classes_summary": summary_data.get("classes", [])
    }


def takeoff_summary(
    project: str,
    group_by: str = "class",
    ifc_class: Optional[str] = None,
    storey: Optional[str] = None,
    keyword: Optional[str] = None
) -> Dict[str, Any]:
    """Calculate quantity takeoff (QTO) aggregations grouped by class, type, storey, or material."""
    con = connect()
    try:
        group_cols = {
            "class": "cls",
            "type": "type_name",
            "storey": "storey",
            "material": "material",
            "model": "model"
        }
        col = group_cols.get(group_by.lower(), "cls")

        where = ["project = ?"]
        params = [project]
        if ifc_class:
            where.append("cls = ?")
            params.append(ifc_class.upper())
        if storey:
            where.append("storey = ?")
            params.append(storey)
        if keyword:
            kw = keyword.strip().lower()
            synonyms = SYNONYM_MAP.get(kw, [f"%{kw}%"])
            like_clauses = []
            for t in synonyms:
                like_clauses.append("(name LIKE ? OR type_name LIKE ? OR material LIKE ?)")
                params.extend([t, t, t])
            where.append(f"({' OR '.join(like_clauses)})")

        where_sql = " AND ".join(where)

        sql = (
            f"SELECT COALESCE({col}, '(none)') as group_name, "
            f"COUNT(*) as count, "
            f"ROUND(SUM(COALESCE(area, 0)), 2) as total_area, "
            f"ROUND(SUM(COALESCE(volume, 0)), 2) as total_volume, "
            f"ROUND(SUM(COALESCE(length, 0)), 2) as total_length "
            f"FROM elements WHERE {where_sql} "
            f"GROUP BY {col} ORDER BY count DESC LIMIT 100"
        )
        cur = con.execute(sql, params)
        rows = [
            {
                "group": r[0],
                "count": r[1],
                "area_m2": r[2],
                "volume_m3": r[3],
                "length_m": r[4]
            }
            for r in cur.fetchall()
        ]

        total_cnt = sum(r["count"] for r in rows)
        total_area = round(sum(r["area_m2"] or 0 for r in rows), 2)
        total_vol = round(sum(r["volume_m3"] or 0 for r in rows), 2)

        return {
            "success": True,
            "project": project,
            "group_by": group_by,
            "total_count": total_cnt,
            "total_area_m2": total_area,
            "total_volume_m3": total_vol,
            "groups": rows
        }
    finally:
        con.close()


def list_models(project: str) -> Dict[str, Any]:
    """List loaded IFC models and identify engineering disciplines."""
    con = connect()
    try:
        cur = con.execute(
            "SELECT model, COUNT(*) as n FROM elements WHERE project=? GROUP BY model ORDER BY n DESC",
            (project,)
        )
        models = []
        for name, count in cur.fetchall():
            uname = (name or "").upper()
            discipline = "General Architecture"
            if "-LA-" in uname or "LANDSCAPE" in uname:
                discipline = "Landscape & External Works"
            elif "-ST-" in uname or "STRUCT" in uname:
                discipline = "Structural Engineering"
            elif "-ME-" in uname or "MEP" in uname or "HVAC" in uname:
                discipline = "Building Services (MEP)"
            elif "-CI-" in uname or "CIVIL" in uname:
                discipline = "Civil & Infrastructure"
            models.append({
                "model_name": name,
                "element_count": count,
                "discipline": discipline
            })
        return {
            "success": True,
            "project": project,
            "model_count": len(models),
            "models": models
        }
    finally:
        con.close()



def measure_distance(
    project: str,
    element_id_1: Optional[int] = None,
    element_id_2: Optional[int] = None,
    keyword_1: Optional[str] = None,
    keyword_2: Optional[str] = None
) -> Dict[str, Any]:
    """Calculate the exact 3D Euclidean distance, horizontal distance, and vertical elevation
    difference between two elements in the BIM model using IfcOpenShell local placement geometry.
    """
    import math
    import os
    import ifcopenshell
    import ifcopenshell.util.placement
    from services.ifc_index import find_ifc_files

    con = connect()
    try:
        def resolve_element(eid, kw):
            if eid is not None:
                r = con.execute("SELECT id, model, step_id, name, type_name FROM elements WHERE project=? AND id=?", (project, eid)).fetchone()
                if r: return r
            if kw:
                r = con.execute("SELECT id, model, step_id, name, type_name FROM elements WHERE project=? AND (name LIKE ? OR type_name LIKE ?) LIMIT 1", (project, f"%{kw}%", f"%{kw}%")).fetchone()
                if r: return r
            return None

        el_info_1 = resolve_element(element_id_1, keyword_1)
        el_info_2 = resolve_element(element_id_2, keyword_2)

        if not el_info_1 or not el_info_2:
            return {"success": False, "error": "Could not resolve both elements for measurement"}

        eid1, model1, step1, name1, type1 = el_info_1
        eid2, model2, step2, name2, type2 = el_info_2

        files = find_ifc_files(project)
        path1 = next((f for f in files if os.path.basename(f) == model1), None)
        path2 = next((f for f in files if os.path.basename(f) == model2), None)

        if not path1 or not path2:
            return {"success": False, "error": f"IFC file on disk not found for {model1} or {model2}"}

        ifc1 = ifcopenshell.open(path1)
        ifc2 = ifc1 if path1 == path2 else ifcopenshell.open(path2)

        obj1 = ifc1.by_id(step1)
        obj2 = ifc2.by_id(step2)

        if not getattr(obj1, 'ObjectPlacement', None) or not getattr(obj2, 'ObjectPlacement', None):
            return {"success": False, "error": "One or both elements lack 3D ObjectPlacement"}

        m1 = ifcopenshell.util.placement.get_local_placement(obj1.ObjectPlacement)
        m2 = ifcopenshell.util.placement.get_local_placement(obj2.ObjectPlacement)

        p1 = (m1[0][3], m1[1][3], m1[2][3])
        p2 = (m2[0][3], m2[1][3], m2[2][3])

        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        dz = p2[2] - p1[2]

        dist_3d = math.sqrt(dx*dx + dy*dy + dz*dz)
        dist_2d = math.sqrt(dx*dx + dy*dy)

        return {
            "success": True,
            "project": project,
            "element_1": {"id": eid1, "name": name1, "type": type1, "coordinates": {"x": round(p1[0], 2), "y": round(p1[1], 2), "z": round(p1[2], 2)}},
            "element_2": {"id": eid2, "name": name2, "type": type2, "coordinates": {"x": round(p2[0], 2), "y": round(p2[1], 2), "z": round(p2[2], 2)}},
            "distance_3d_meters": round(dist_3d, 2),
            "horizontal_distance_meters": round(dist_2d, 2),
            "vertical_difference_meters": round(abs(dz), 2),
            "measurement_summary": f"Exact 3D Distance: {dist_3d:.2f} m (Horizontal: {dist_2d:.2f} m, Vertical dZ: {abs(dz):.2f} m)"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        con.close()


def create_viewer_action(
    project: str,
    action: str,
    keyword: Optional[str] = None,
    ifc_class: Optional[str] = None,
    element_ids: Optional[List[int]] = None,
    color: Optional[str] = None
) -> Dict[str, Any]:
    """Prepare a verified 3D viewer action (isolate, hide, show, color, reset, fit)
    with exact element step_ids resolved from the SQLite database.
    """
    valid_actions = {"isolate", "hide", "show", "color", "reset", "fit"}
    act = (action or "").strip().lower()
    if act not in valid_actions:
        return {"success": False, "error": f"Invalid action '{action}'. Must be one of {valid_actions}"}

    if act in ("reset", "fit"):
        return {
            "success": True,
            "action": act,
            "project": project,
            "message": f"Action '{act}' ready for viewer execution."
        }

    con = connect()
    try:
        where = ["project = ?"]
        params = [project]

        if element_ids:
            ph = ",".join(["?"] * len(element_ids))
            where.append(f"id IN ({ph})")
            params.extend(element_ids)
        else:
            kw = (keyword or "").strip().lower()
            target_classes = []
            if ifc_class:
                target_classes = [ifc_class.upper()]
            elif kw in CLASS_MAP:
                target_classes = CLASS_MAP[kw]

            if target_classes:
                ph = ",".join(["?"] * len(target_classes))
                where.append(f"cls IN ({ph})")
                params.extend(target_classes)

            if kw:
                synonyms = SYNONYM_MAP.get(kw) or dynamic_semantic_expand(kw)
                like_clauses = []
                for t in synonyms:
                    like_clauses.append("(name LIKE ? OR type_name LIKE ? OR material LIKE ? OR category LIKE ?)")
                    params.extend([t, t, t, t])
                where.append(f"({' OR '.join(like_clauses)})")

        where_sql = " AND ".join(where)
        cur = con.execute(f"SELECT model, step_id FROM elements WHERE {where_sql} AND step_id IS NOT NULL LIMIT 10000", params)
        items = [{"model": r[0], "step_id": r[1]} for r in cur.fetchall()]

        return {
            "success": True,
            "action": act,
            "project": project,
            "target_count": len(items),
            "color": color,
            "items": items,
            "message": f"Resolved {len(items)} elements for viewer action '{act}'."
        }
    finally:
        con.close()


# Schema definitions for standard MCP server and Ollama Tool Calling
BIM_MCP_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bim_measure_distance",
            "description": "Measure the exact 3D Euclidean distance, horizontal distance, and elevation difference between any two elements in the BIM model using real geometry (e.g. distance between two trees, columns, or doors).",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project ID"},
                    "element_id_1": {"type": "integer", "description": "First element database ID"},
                    "element_id_2": {"type": "integer", "description": "Second element database ID"},
                    "keyword_1": {"type": "string", "description": "Keyword to find first element (e.g. 'palm', 'tree', 'column')"},
                    "keyword_2": {"type": "string", "description": "Keyword to find second element (e.g. 'palm', 'tree', 'door')"}
                },
                "required": ["project"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bim_search_elements",
            "description": "Search BIM elements in SQLite database by keyword (e.g. 'plant', 'tree', 'palm', 'shrub', 'column', 'door', 'slab') or IFC class. Returns element counts, breakdown by type, and sample IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project ID, e.g. 'C3082 - SiteWide' or 'C3085 - 3EH -Expo Hills'"},
                    "keyword": {"type": "string", "description": "Search keyword (matches name, type_name, material, category, or semantic synonym like plant/vegetation)"},
                    "ifc_class": {"type": "string", "description": "Optional IFC class filter, e.g. 'IFCBUILDINGELEMENTPROXY', 'IFCWALL', 'IFCCOLUMN'"},
                    "storey": {"type": "string", "description": "Optional level or storey name"},
                    "limit": {"type": "integer", "description": "Maximum sample elements to return (default 50)"}
                },
                "required": ["project", "keyword"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bim_get_element_details",
            "description": "Fetch complete IFC property sets, dimensions (length, width, height, area, volume), and metadata for a specific BIM element.",
            "parameters": {
                "type": "object",
                "properties": {
                    "element_id": {"type": "integer", "description": "Database element ID"},
                    "guid": {"type": "string", "description": "IFC GlobalId (GUID)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bim_spatial_summary",
            "description": "Get building spatial hierarchy (storeys, elevations, element counts, total areas, and volumes per level).",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project ID"}
                },
                "required": ["project"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bim_takeoff_summary",
            "description": "Calculate quantity takeoff (QTO) aggregations (count, area m2, volume m3, length m) grouped by class, type, storey, or material.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project ID"},
                    "group_by": {"type": "string", "enum": ["class", "type", "storey", "material", "model"], "description": "Grouping column"},
                    "ifc_class": {"type": "string", "description": "Optional IFC class filter"},
                    "storey": {"type": "string", "description": "Optional storey filter"},
                    "keyword": {"type": "string", "description": "Optional keyword filter"}
                },
                "required": ["project"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bim_list_models",
            "description": "List all IFC models loaded for the project with element counts and disciplines.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project ID"}
                },
                "required": ["project"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bim_viewer_action",
            "description": "Apply a 3D view action in the viewer (isolate, hide, show, color, select, fit, reset) targeting specific elements, keywords, or categories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Project ID"},
                    "action": {"type": "string", "enum": ["isolate", "hide", "show", "color", "fit", "reset"]},
                    "keyword": {"type": "string", "description": "Target elements matching keyword (e.g. 'plant', 'palm', 'column', 'door')"},
                    "ifc_class": {"type": "string", "description": "Target IFC class (e.g. 'IFCBUILDINGELEMENTPROXY', 'IFCWALL')"},
                    "element_ids": {"type": "array", "items": {"type": "integer"}, "description": "Specific element IDs to target"},
                    "color": {"type": "string", "description": "Hex color code (e.g. '#4d7cfe' or '#ff4444') for color action"}
                },
                "required": ["project", "action"]
            }
        }
    }
]


def dispatch_tool_call(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a tool call against the BIM database/services."""
    try:
        if tool_name == "bim_search_elements":
            return search_elements(
                project=arguments.get("project", ""),
                keyword=arguments.get("keyword", ""),
                ifc_class=arguments.get("ifc_class", ""),
                storey=arguments.get("storey", ""),
                limit=int(arguments.get("limit", 50))
            )
        elif tool_name == "bim_get_element_details":
            return get_element_details(
                project=arguments.get("project", ""),
                element_id=arguments.get("element_id"),
                guid=arguments.get("guid")
            )
        elif tool_name == "bim_spatial_summary":
            return spatial_summary(project=arguments.get("project", ""))
        elif tool_name == "bim_takeoff_summary":
            return takeoff_summary(
                project=arguments.get("project", ""),
                group_by=arguments.get("group_by", "class"),
                ifc_class=arguments.get("ifc_class"),
                storey=arguments.get("storey"),
                keyword=arguments.get("keyword")
            )
        elif tool_name == "bim_list_models":
            return list_models(project=arguments.get("project", ""))
        elif tool_name == "bim_measure_distance":
            return measure_distance(
                project=arguments.get("project", ""),
                element_id_1=arguments.get("element_id_1"),
                element_id_2=arguments.get("element_id_2"),
                keyword_1=arguments.get("keyword_1"),
                keyword_2=arguments.get("keyword_2")
            )
        elif tool_name == "bim_viewer_action":
            return create_viewer_action(
                project=arguments.get("project", ""),
                action=arguments.get("action", ""),
                keyword=arguments.get("keyword"),
                ifc_class=arguments.get("ifc_class"),
                element_ids=arguments.get("element_ids"),
                color=arguments.get("color")
            )
        else:
            return {"error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        logger.exception("Error executing BIM tool {}", tool_name)
        return {"error": str(e)}


async def run_qwen_mcp_agent(
    project: str,
    query: str,
    context: str = "",
    selection: str = "",
    chat_history: Optional[List[Dict[str, str]]] = None,
    max_steps: int = 4
) -> Dict[str, Any]:
    """Agentic reasoning loop connecting Qwen 3.5 9B with BIM Model MCP tools."""
    role = resolve_role("chat")
    base_url = role["base_url"]
    model_name = role["model"]

    system_prompt = (
        "You are Expo Design AI, an intelligent BIM engineering assistant with direct MCP bridge access "
        "to the BIM model database and 3D viewer. You have tools to search elements, retrieve element properties, "
        "generate quantity takeoffs, inspect spatial storeys, and trigger viewer actions (isolate, color, hide, show, reset, fit).\n\n"
        "GUIDELINES:\n"
        "1. For questions about specific objects (e.g. plants, palms, trees, columns, doors, walls, slabs, pipes), "
        "ALWAYS use `bim_search_elements` to inspect the exact database records and subtype names.\n"
        "2. Note that in Revit/IFC models, vegetation and site elements are typically categorized under IFCBUILDINGELEMENTPROXY "
        "with type names such as EDS_11P_PALM, EDS_11P_TREE_CANOPY, EDS_11P_ACCENT SHRUB, etc. Use `bim_search_elements` with keyword 'plant' or 'palm'.\n"
        "3. When the user asks to isolate, show, hide, or highlight elements in the 3D viewer, call `bim_viewer_action`.\n"
        "4. Quote exact counts, level names, and quantities from tool results. NEVER fabricate or guess.\n"
        f"Active Project: {project}\n"
    )
    if selection:
        system_prompt += f"\nCurrently Selected Element:\n{selection}\n"

    messages = [{"role": "system", "content": system_prompt}]
    if chat_history:
        for msg in chat_history[-4:]:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
    messages.append({"role": "user", "content": query})

    tool_calls_executed = []
    viewer_action_result = None

    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
        for step in range(max_steps):
            payload = {
                "model": model_name,
                "messages": messages,
                "tools": BIM_MCP_TOOLS,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 1200}
            }
            res = await client.post(f"{base_url}/api/chat", json=payload)
            res.raise_for_status()
            data = res.json()
            message = data.get("message", {})

            tool_calls = message.get("tool_calls")
            if not tool_calls:
                # Qwen finished reasoning and provided final text answer
                final_content = message.get("content", "")
                return {
                    "answer": final_content,
                    "tool_calls_executed": tool_calls_executed,
                    "viewer_action": viewer_action_result
                }

            # Add assistant's tool-calling message to history
            messages.append(message)

            # Execute each requested tool call
            for tc in tool_calls:
                fn = tc.get("function", {})
                t_name = fn.get("name")
                t_args = fn.get("arguments", {})
                if isinstance(t_args, str):
                    try:
                        t_args = json.loads(t_args)
                    except Exception:
                        t_args = {}

                # Guarantee project context
                if "project" not in t_args or not t_args["project"]:
                    t_args["project"] = project

                result = dispatch_tool_call(t_name, t_args)
                tool_calls_executed.append({"tool": t_name, "arguments": t_args, "result": result})

                if t_name == "bim_viewer_action" and result.get("success"):
                    viewer_action_result = result

                # Provide tool result back to Qwen
                messages.append({
                    "role": "tool",
                    "content": json.dumps(result, ensure_ascii=False)
                })

        # Fallback if loop exceeded max_steps
        payload = {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 1000}
        }
        res = await client.post(f"{base_url}/api/chat", json=payload)
        res.raise_for_status()
        final_content = res.json().get("message", {}).get("content", "")
        return {
            "answer": final_content,
            "tool_calls_executed": tool_calls_executed,
            "viewer_action": viewer_action_result
        }
