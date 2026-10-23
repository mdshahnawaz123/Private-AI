path = r'C:\3EH\ExpoDesignAI - Copy\services\bim_mcp_bridge.py'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

func_code = '''
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
'''

target = 'def create_viewer_action('
assert target in text
text = text.replace(target, func_code + '\n\ndef create_viewer_action(', 1)

# Add to BIM_MCP_TOOLS schema
tool_schema = '''    {
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
'''
target_schema = 'BIM_MCP_TOOLS = [\n'
assert target_schema in text
text = text.replace(target_schema, target_schema + tool_schema, 1)

# Add to dispatch_tool_call
dispatch_target = 'elif tool_name == "bim_viewer_action":'
dispatch_code = '''elif tool_name == "bim_measure_distance":
            return measure_distance(
                project=arguments.get("project", ""),
                element_id_1=arguments.get("element_id_1"),
                element_id_2=arguments.get("element_id_2"),
                keyword_1=arguments.get("keyword_1"),
                keyword_2=arguments.get("keyword_2")
            )
        '''
assert dispatch_target in text
text = text.replace(dispatch_target, dispatch_code + dispatch_target, 1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

print('Updated services/bim_mcp_bridge.py with measure_distance')
