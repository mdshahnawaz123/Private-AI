"""
CAD Intelligence & Drafting Service for Expo Design AI.
Inspired by and compatible with CADCraft (storytold/cadcraft: pure Rust AutoCAD clean-room engine).

Provides:
- DXF parsing via ezdxf: extracts layers, lines, circles, arcs, polylines, text, dimensions, blocks, hatches.
- DXF generation/export via ezdxf: converts structured web entities into clean AutoCAD DXF R2000 files.
- Built-in architectural sample drawings (Apartment Floor Plan, Structural Core Grid, Mechanical Part).
- Raster/vector rendering for Image Engine (sketch_to_render AI workflow).
- DWG extraction and integration.
"""
import io
import json
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple
import ezdxf
from ezdxf.enums import TextEntityAlignment
from loguru import logger

# AutoCAD Color Index (ACI) to RGB Hex mapping
ACI_COLORS = {
    1: "#ff0000",  # Red
    2: "#ffff00",  # Yellow
    3: "#00ff00",  # Green
    4: "#00ffff",  # Cyan
    5: "#0000ff",  # Blue
    6: "#ff00ff",  # Magenta
    7: "#ffffff",  # White/Black
    8: "#808080",  # Dark Gray
    9: "#c0c0c0",  # Light Gray
}


def aci_to_hex(color_index: Optional[int], default: str = "#ffffff") -> str:
    """Convert AutoCAD Color Index (ACI) to RGB Hex string."""
    if color_index is None or color_index == 256:  # ByLayer
        return default
    return ACI_COLORS.get(color_index, default)


class CadService:
    """High-performance CAD parsing, drafting, and export service."""

    @staticmethod
    def parse_dxf_stream(file_stream: Any) -> Dict[str, Any]:
        """
        Parse DXF stream/file or ezdxf Drawing into structured JSON entities for the CADCraft canvas.
        Extracts layers, lines, polylines, circles, arcs, text, dimensions, and extents.
        """
        try:
            if hasattr(file_stream, "modelspace"):
                doc = file_stream
            elif isinstance(file_stream, str):
                if os.path.exists(file_stream):
                    doc = ezdxf.readfile(file_stream)
                else:
                    doc = ezdxf.read(io.StringIO(file_stream))
            elif isinstance(file_stream, io.BytesIO):
                text_content = file_stream.getvalue().decode("utf-8", errors="ignore")
                doc = ezdxf.read(io.StringIO(text_content))
            else:
                doc = ezdxf.read(file_stream)
        except Exception as exc:
            logger.error(f"Failed to parse DXF: {exc}")
            raise ValueError(f"Invalid or corrupted DXF file: {exc}")

        msp = doc.modelspace()
        layers: Dict[str, Dict[str, Any]] = {}

        # 1. Extract Layer table
        for layer in doc.layers:
            name = layer.dxf.name
            color_idx = layer.dxf.color
            color_hex = aci_to_hex(color_idx, default="#00ffff" if name.upper() == "DIMS" else "#ffffff")
            layers[name] = {
                "name": name,
                "color": color_hex,
                "visible": not layer.is_off(),
                "locked": layer.is_locked(),
                "linetype": layer.dxf.linetype or "CONTINUOUS",
            }

        entities: List[Dict[str, Any]] = []
        min_x = float("inf")
        min_y = float("inf")
        max_x = float("-inf")
        max_y = float("-inf")

        def _update_extents(x: float, y: float):
            nonlocal min_x, min_y, max_x, max_y
            if math.isfinite(x) and math.isfinite(y):
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

        entity_id_counter = 1

        # Explode block references (INSERT) to unpack nested walls, columns, stairs, parking, and building geometry
        try:
            for ins in list(msp.query("INSERT")):
                try:
                    ins.explode()
                except Exception:
                    pass
        except Exception as exc:
            logger.warning(f"Failed to explode block references: {exc}")

        # Unpack table entities (ACAD_TABLE) into virtual geometry (lines, text cells)
        try:
            for tbl in list(msp.query("ACAD_TABLE")):
                try:
                    for vent in tbl.virtual_entities():
                        msp.add_entity(vent)
                except Exception:
                    pass
        except Exception as exc:
            logger.debug(f"Failed to virtualize ACAD_TABLE: {exc}")

        # 2. Iterate ModelSpace entities
        for e in msp:
            etype = e.dxftype()
            layer_name = e.dxf.layer or "0"
            layer_color = layers.get(layer_name, {}).get("color", "#ffffff")
            color = aci_to_hex(getattr(e.dxf, "color", None), default=layer_color)

            if etype == "LINE":
                x1, y1 = float(e.dxf.start.x), float(e.dxf.start.y)
                x2, y2 = float(e.dxf.end.x), float(e.dxf.end.y)
                _update_extents(x1, y1)
                _update_extents(x2, y2)
                entities.append({
                    "id": f"ent_{entity_id_counter}",
                    "type": "LINE",
                    "layer": layer_name,
                    "color": color,
                    "x1": round(x1, 3),
                    "y1": round(y1, 3),
                    "x2": round(x2, 3),
                    "y2": round(y2, 3),
                })
                entity_id_counter += 1

            elif etype in ("LWPOLYLINE", "POLYLINE"):
                try:
                    pts = [[round(float(p[0]), 3), round(float(p[1]), 3)] for p in e.get_points()]
                    for p in pts:
                        _update_extents(p[0], p[1])
                    is_closed = bool(getattr(e, "is_closed", False) or getattr(e.dxf, "flags", 0) & 1)
                    if pts:
                        entities.append({
                            "id": f"ent_{entity_id_counter}",
                            "type": "POLYLINE",
                            "layer": layer_name,
                            "color": color,
                            "points": pts,
                            "closed": is_closed,
                        })
                        entity_id_counter += 1
                except Exception:
                    pass

            elif etype == "CIRCLE":
                cx, cy = float(e.dxf.center.x), float(e.dxf.center.y)
                r = float(e.dxf.radius)
                _update_extents(cx - r, cy - r)
                _update_extents(cx + r, cy + r)
                entities.append({
                    "id": f"ent_{entity_id_counter}",
                    "type": "CIRCLE",
                    "layer": layer_name,
                    "color": color,
                    "cx": round(cx, 3),
                    "cy": round(cy, 3),
                    "radius": round(r, 3),
                })
                entity_id_counter += 1

            elif etype == "ARC":
                cx, cy = float(e.dxf.center.x), float(e.dxf.center.y)
                r = float(e.dxf.radius)
                start_angle = float(e.dxf.start_angle)
                end_angle = float(e.dxf.end_angle)
                _update_extents(cx - r, cy - r)
                _update_extents(cx + r, cy + r)
                entities.append({
                    "id": f"ent_{entity_id_counter}",
                    "type": "ARC",
                    "layer": layer_name,
                    "color": color,
                    "cx": round(cx, 3),
                    "cy": round(cy, 3),
                    "radius": round(r, 3),
                    "start_angle": round(start_angle, 2),
                    "end_angle": round(end_angle, 2),
                })
                entity_id_counter += 1

            elif etype in ("TEXT", "MTEXT"):
                txt = getattr(e.dxf, "text", "") or ""
                if not txt and hasattr(e, "plain_text"):
                    txt = e.plain_text()
                pos = getattr(e.dxf, "insert", getattr(e.dxf, "align_point", None))
                if pos:
                    px, py = float(pos.x), float(pos.y)
                    h = float(getattr(e.dxf, "height", 2.5) or 2.5)
                    _update_extents(px, py)
                    entities.append({
                        "id": f"ent_{entity_id_counter}",
                        "type": "TEXT",
                        "layer": layer_name,
                        "color": color,
                        "x": round(px, 3),
                        "y": round(py, 3),
                        "text": txt.strip(),
                        "height": round(h, 2),
                    })
                    entity_id_counter += 1

            elif etype == "DIMENSION":
                label = getattr(e.dxf, "text", "") or ""
                dp = getattr(e.dxf, "defpoint", None)
                dp2 = getattr(e.dxf, "defpoint2", None)
                dp3 = getattr(e.dxf, "defpoint3", None)
                dp4 = getattr(e.dxf, "defpoint4", None)
                ang = getattr(e.dxf, "angle", 0.0) % 180.0
                x1 = y1 = x2 = y2 = None
                dist = 0.0

                if dp is not None and dp2 is not None and dp3 is not None and (dp2 != dp3):
                    if abs(ang) < 1.0 or abs(ang - 180.0) < 1.0:
                        x1, y1 = min(float(dp2.x), float(dp3.x)), float(dp.y)
                        x2, y2 = max(float(dp2.x), float(dp3.x)), float(dp.y)
                        dist = abs(float(dp3.x) - float(dp2.x))
                    elif abs(ang - 90.0) < 1.0:
                        x1, y1 = float(dp.x), min(float(dp2.y), float(dp3.y))
                        x2, y2 = float(dp.x), max(float(dp2.y), float(dp3.y))
                        dist = abs(float(dp3.y) - float(dp2.y))
                    else:
                        x1, y1 = float(dp2.x), float(dp2.y)
                        x2, y2 = float(dp3.x), float(dp3.y)
                        dist = math.hypot(x2 - x1, y2 - y1)
                elif dp is not None and dp4 is not None:
                    x1, y1 = float(dp.x), float(dp.y)
                    x2, y2 = float(dp4.x), float(dp4.y)
                    dist = math.hypot(x2 - x1, y2 - y1)
                elif dp is not None and dp2 is not None:
                    x1, y1 = float(dp.x), float(dp.y)
                    x2, y2 = float(dp2.x), float(dp2.y)
                    dist = math.hypot(x2 - x1, y2 - y1)

                if x1 is not None and x2 is not None:
                    _update_extents(x1, y1)
                    _update_extents(x2, y2)
                    if not label or label == "<>":
                        label = f"{dist:,.0f}"
                    entities.append({
                        "id": f"ent_{entity_id_counter}",
                        "type": "DIMENSION",
                        "layer": layer_name,
                        "color": color if color != "#ffffff" else "#00e5ff",
                        "x1": round(x1, 3),
                        "y1": round(y1, 3),
                        "x2": round(x2, 3),
                        "y2": round(y2, 3),
                        "text": label,
                    })
                    entity_id_counter += 1

            elif etype == "ELLIPSE":
                try:
                    cx, cy = float(e.dxf.center.x), float(e.dxf.center.y)
                    major = e.dxf.major_axis
                    ratio = float(e.dxf.ratio)
                    r = math.hypot(major.x, major.y)
                    rot = math.atan2(major.y, major.x)
                    pts = []
                    for step in range(36):
                        th = (step / 36.0) * 2 * math.pi
                        lx = r * math.cos(th)
                        ly = r * ratio * math.sin(th)
                        gx = cx + lx * math.cos(rot) - ly * math.sin(rot)
                        gy = cy + lx * math.sin(rot) + ly * math.cos(rot)
                        _update_extents(gx, gy)
                        pts.append([round(gx, 3), round(gy, 3)])
                    if pts:
                        entities.append({
                            "id": f"ent_{entity_id_counter}",
                            "type": "POLYLINE",
                            "layer": layer_name,
                            "color": color,
                            "points": pts,
                            "closed": True,
                        })
                        entity_id_counter += 1
                except Exception:
                    pass

            elif etype == "SPLINE":
                try:
                    pts = [[round(float(p[0]), 3), round(float(p[1]), 3)] for p in e.flattening(distance=0.5)]
                    if pts:
                        for p in pts:
                            _update_extents(p[0], p[1])
                        entities.append({
                            "id": f"ent_{entity_id_counter}",
                            "type": "POLYLINE",
                            "layer": layer_name,
                            "color": color,
                            "points": pts,
                            "closed": False,
                        })
                        entity_id_counter += 1
                except Exception:
                    pass

            elif etype in ("SOLID", "TRACE"):
                try:
                    pts = []
                    for vname in ("vtx0", "vtx1", "vtx2", "vtx3"):
                        v = getattr(e.dxf, vname, None)
                        if v is not None:
                            _update_extents(float(v.x), float(v.y))
                            pts.append([round(float(v.x), 3), round(float(v.y), 3)])
                    if len(pts) >= 3:
                        entities.append({
                            "id": f"ent_{entity_id_counter}",
                            "type": "POLYLINE",
                            "layer": layer_name,
                            "color": color,
                            "points": pts,
                            "closed": True,
                        })
                        entity_id_counter += 1
                except Exception:
                    pass

            elif etype == "INSERT":
                try:
                    pos = getattr(e.dxf, "insert", None)
                    if pos:
                        ix, iy = float(pos.x), float(pos.y)
                        _update_extents(ix, iy)
                        for a in getattr(e, "attribs", []):
                            atxt = (getattr(a.dxf, "text", "") or "").strip()
                            apos = getattr(a.dxf, "insert", None)
                            if atxt and apos:
                                _update_extents(float(apos.x), float(apos.y))
                                entities.append({
                                    "id": f"ent_{entity_id_counter}",
                                    "type": "TEXT",
                                    "layer": layer_name,
                                    "color": color,
                                    "x": round(float(apos.x), 3),
                                    "y": round(float(apos.y), 3),
                                    "text": atxt,
                                    "height": round(float(getattr(a.dxf, "height", 2.5) or 2.5), 2),
                                })
                                entity_id_counter += 1
                except Exception:
                    pass

            elif etype == "HATCH":
                try:
                    pat_name = getattr(e.dxf, "pattern_name", "SOLID")
                    paths = []
                    for bp in getattr(e, "paths", []):
                        if hasattr(bp, "vertices"):
                            v_pts = [[round(float(v[0]), 3), round(float(v[1]), 3)] for v in bp.vertices]
                            if v_pts:
                                paths.append(v_pts)
                                for pt in v_pts:
                                    _update_extents(pt[0], pt[1])
                        elif hasattr(bp, "edges"):
                            e_pts = []
                            for edge in bp.edges:
                                if hasattr(edge, "start"):
                                    e_pts.append([round(float(edge.start[0]), 3), round(float(edge.start[1]), 3)])
                                    _update_extents(edge.start[0], edge.start[1])
                            if e_pts:
                                paths.append(e_pts)
                    if paths:
                        entities.append({
                            "id": f"ent_{entity_id_counter}",
                            "type": "HATCH",
                            "layer": layer_name,
                            "color": color,
                            "pattern": pat_name,
                            "paths": paths,
                        })
                        entity_id_counter += 1
                except Exception as exc:
                    logger.debug(f"Hatch parse error: {exc}")

            elif etype in ("LEADER", "MULTILEADER"):
                try:
                    pts = []
                    if hasattr(e, "vertices"):
                        pts = [[round(float(v[0]), 3), round(float(v[1]), 3)] for v in e.vertices]
                    if pts:
                        for pt in pts:
                            _update_extents(pt[0], pt[1])
                        entities.append({
                            "id": f"ent_{entity_id_counter}",
                            "type": "LEADER",
                            "layer": layer_name,
                            "color": color,
                            "points": pts,
                            "text": getattr(e, "text", "") or ""
                        })
                        entity_id_counter += 1
                except Exception:
                    pass

        # Default extents if drawing is empty
        if min_x == float("inf"):
            min_x, min_y, max_x, max_y = 0.0, 0.0, 100.0, 100.0

        width = max(max_x - min_x, 10.0)
        height = max(max_y - min_y, 10.0)

        return {
            "success": True,
            "layers": list(layers.values()),
            "entities": entities,
            "entity_count": len(entities),
            "extents": {
                "min_x": round(min_x, 3),
                "min_y": round(min_y, 3),
                "max_x": round(max_x, 3),
                "max_y": round(max_y, 3),
                "width": round(width, 3),
                "height": round(height, 3),
                "center_x": round((min_x + max_x) / 2.0, 3),
                "center_y": round((min_y + max_y) / 2.0, 3),
            },
        }

    @staticmethod
    def generate_dxf(
        entities: List[Dict[str, Any]],
        layers: Optional[List[Dict[str, Any]]] = None,
        title: str = "Drawing"
    ) -> str:
        """
        Generate a compliant AutoCAD DXF R2010 (UTF-8) string from structured web entities.
        Can be opened directly in AutoCAD, CADCraft, Revit, or Rhino.
        """
        doc = ezdxf.new("R2010")
        msp = doc.modelspace()

        def _lname(n):
            # DXF layer names cannot contain < > / \ " : ; ? * | = ` and must not be empty
            n = re.sub(r'[<>/\\":;?*|=`]', "_", str(n or "0")).strip()[:255]
            return n or "0"

        def _f(v, default=0.0):
            try:
                x = float(v)
            except (TypeError, ValueError):
                return float(default)
            return x if math.isfinite(x) else float(default)

        # Add layers
        if layers:
            for l in layers:
                lname = _lname(l.get("name", "0"))
                if lname not in doc.layers:
                    doc.layers.add(lname)

        for ent in entities:
            etype = ent.get("type", "").upper()
            layer = _lname(ent.get("layer", "0"))
            if layer not in doc.layers:
                doc.layers.add(layer)

            dxf_attribs = {"layer": layer}

            if etype == "LINE":
                x1, y1 = _f(ent.get("x1"), 0.0), _f(ent.get("y1"), 0.0)
                x2, y2 = _f(ent.get("x2"), 0.0), _f(ent.get("y2"), 0.0)
                msp.add_line((x1, y1), (x2, y2), dxfattribs=dxf_attribs)

            elif etype in ("POLYLINE", "RECTANGLE"):
                pts = [(_f(p[0]), _f(p[1])) for p in (ent.get("points") or []) if isinstance(p, (list, tuple)) and len(p) >= 2]
                if not pts and etype == "RECTANGLE":
                    rx, ry = _f(ent.get("x"), 0.0), _f(ent.get("y"), 0.0)
                    rw, rh = _f(ent.get("width"), 10.0), _f(ent.get("height"), 10.0)
                    pts = [(rx, ry), (rx + rw, ry), (rx + rw, ry + rh), (rx, ry + rh)]
                if pts:
                    is_closed = bool(ent.get("closed", True if etype == "RECTANGLE" else False))
                    msp.add_lwpolyline(pts, close=is_closed, dxfattribs=dxf_attribs)

            elif etype == "CIRCLE":
                cx, cy = _f(ent.get("cx"), 0.0), _f(ent.get("cy"), 0.0)
                r = _f(ent.get("radius"), 5.0)
                msp.add_circle((cx, cy), radius=r, dxfattribs=dxf_attribs)

            elif etype == "ARC":
                cx, cy = _f(ent.get("cx"), 0.0), _f(ent.get("cy"), 0.0)
                r = _f(ent.get("radius"), 5.0)
                sa = _f(ent.get("start_angle"), 0.0)
                ea = _f(ent.get("end_angle"), 180.0)
                msp.add_arc((cx, cy), radius=r, start_angle=sa, end_angle=ea, dxfattribs=dxf_attribs)

            elif etype == "TEXT":
                txt = str(ent.get("text", ""))[:2000]
                tx, ty = _f(ent.get("x"), 0.0), _f(ent.get("y"), 0.0)
                h = _f(ent.get("height"), 2.5)
                msp.add_text(txt, dxfattribs={**dxf_attribs, "height": h}).set_placement((tx, ty))

            elif etype == "DIMENSION":
                x1, y1 = _f(ent.get("x1"), 0.0), _f(ent.get("y1"), 0.0)
                x2, y2 = _f(ent.get("x2"), 0.0), _f(ent.get("y2"), 0.0)
                dist = math.hypot(x2 - x1, y2 - y1)
                text = ent.get("text") or f"{dist:.0f}"
                # Add dimension linework and text
                msp.add_line((x1, y1), (x2, y2), dxfattribs=dxf_attribs)
                mid_x, mid_y = (x1 + x2) / 2.0, (y1 + y2) / 2.0 + 2.0
                msp.add_text(text, dxfattribs={**dxf_attribs, "height": 2.0}).set_placement((mid_x, mid_y))

            elif etype == "HATCH":
                paths = ent.get("paths") or []
                if paths:
                    try:
                        hatch = msp.add_hatch(dxfattribs=dxf_attribs)
                        pat = ent.get("pattern", "ANSI31")
                        try:
                            hatch.set_pattern_fill(pat, scale=float(ent.get("scale", 1.0) or 1.0))
                        except Exception:
                            hatch.set_solid_fill()
                        for p in paths:
                            poly_pts = [(_f(pt[0]), _f(pt[1])) for pt in p if isinstance(pt, (list, tuple)) and len(pt) >= 2]
                            if len(poly_pts) >= 3:
                                hatch.paths.add_polyline_path(poly_pts, is_closed=True)
                    except Exception as exc:
                        logger.debug(f"Failed to generate DXF hatch: {exc}")

            elif etype == "LEADER":
                pts = [(_f(p[0]), _f(p[1])) for p in (ent.get("points") or []) if isinstance(p, (list, tuple)) and len(p) >= 2]
                if len(pts) >= 2:
                    msp.add_lwpolyline(pts, close=False, dxfattribs=dxf_attribs)
                    if ent.get("text"):
                        last_pt = pts[-1]
                        msp.add_text(str(ent.get("text")), dxfattribs={**dxf_attribs, "height": 2.5}).set_placement((last_pt[0] + 1.0, last_pt[1]))

        stream = io.StringIO()
        doc.write(stream)
        # DXF R2010 is stored as UTF-8 (R2000 was Windows-1252), so m², °, Ø and Arabic text
        # survive save/reopen instead of turning into "mÂ²". Files are written as UTF-8.
        return stream.getvalue()

    @staticmethod
    def get_architectural_samples() -> List[Dict[str, Any]]:
        """Return library of pre-loaded architectural CAD sample drawings."""
        return [
            {
                "id": "sample_cadcraft_apartment",
                "title": "CADCraft Apartment Master Plan (Official Upstream)",
                "category": "Architectural",
                "description": "Official showcase apartment plan from storytold/cadcraft with wall pick-point hatching, room schedules, TrueType labels, and dimensions.",
                "tags": ["Apartment", "CADCraft", "Master Plan", "Hatch", "Official"],
            },
            {
                "id": "sample_apartment_plan",
                "title": "Apartment Floor Plan (2-Bedroom Residential)",
                "category": "Architectural",
                "description": "2-Bedroom residential floor plan with exterior walls, doors, windows, living/dining zones, and dimensions.",
                "tags": ["Apartment", "Residential", "Floor Plan", "CADCraft"],
            },
            {
                "id": "sample_structural_core",
                "title": "Structural Column Grid & Core",
                "category": "Structural",
                "description": "High-rise column grid with reinforced concrete columns, elevator core shear walls, and structural centerlines.",
                "tags": ["Structural", "Columns", "Grid", "Core"],
            },
            {
                "id": "sample_mechanical_bracket",
                "title": "Mechanical Mounting Bracket",
                "category": "Mechanical",
                "description": "Precision engineering bracket with bolt circle array, centerlines, fillet radii, and dimension callouts.",
                "tags": ["Mechanical", "Part", "Dimensions"],
            },
            {
                "id": "sample_expo_masterplan",
                "title": "25-6963_Expo City-REV.02 Masterplan ECD Layout_WIP.dwg",
                "category": "Masterplan",
                "description": "Full urban masterplan layout with residential, commercial, park, and road networks from Expo City project.",
                "tags": ["Masterplan", "Urban", "Expo City", "AutoCAD 2026"],
            },
        ]

    @classmethod
    def load_sample_drawing(cls, sample_id: str) -> Dict[str, Any]:
        """Generate structured CADCraft entities for the requested architectural sample."""
        if sample_id in ("sample_expo_masterplan", "sample_masterplan", "expo_masterplan"):
            cache_json = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "data", "cad_cache",
                "25-6963_Expo_City-REV.02_Masterplan_ECD_Layout_WIP.dwg_ad3d97d0f78f_9072557.json"
            )
            if os.path.exists(cache_json):
                try:
                    with open(cache_json, "r", encoding="utf-8") as f:
                        res = json.load(f)
                    res["title"] = "25-6963_Expo City-REV.02 Masterplan ECD Layout_WIP.dwg"
                    layer_color_map = {
                        "park": "#4ade80", "green": "#22c55e", "promenade": "#10b981",
                        "residential": "#f97316", "mixed": "#f59e0b", "commercial": "#ea580c",
                        "public": "#a855f7", "facility": "#c084fc", "hospitality": "#ec4899",
                        "water": "#38bdf8", "lake": "#0284c7", "road": "#ffffff",
                        "boundary": "#ef4444"
                    }
                    for layer in res.get("layers", []):
                        lname = layer.get("name", "").lower()
                        for key, col in layer_color_map.items():
                            if key in lname:
                                layer["color"] = col
                                break
                    layer_map = {l["name"]: l["color"] for l in res.get("layers", [])}
                    for ent in res.get("entities", []):
                        if ent.get("layer") in layer_map:
                            ent["color"] = layer_map[ent["layer"]]
                    return res
                except Exception as exc:
                    logger.warning(f"Failed to load masterplan cache: {exc}")

        if sample_id == "sample_cadcraft_apartment":
            repo_sample_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "vendor", "cadcraft", "examples", "apartment.dxf")
            if os.path.exists(repo_sample_path):
                try:
                    res = cls.parse_dxf_stream(repo_sample_path)
                    res["title"] = "CADCraft Apartment Master Plan (Official Upstream Showcase)"
                    return res
                except Exception as exc:
                    logger.warning(f"Failed to load upstream apartment.dxf: {exc}")
            return cls._build_apartment_floor_plan_sample()
        elif sample_id == "sample_structural_core":
            return cls._build_structural_grid_sample()
        elif sample_id == "sample_mechanical_bracket":
            return cls._build_mechanical_bracket_sample()
        else:
            return cls._build_apartment_floor_plan_sample()

    @classmethod
    def _build_apartment_floor_plan_sample(cls) -> Dict[str, Any]:
        """Builds a rich architectural apartment floor plan matching CADCraft examples/apartment.dxf."""
        layers = [
            {"name": "0", "color": "#808080", "visible": True, "locked": False, "linetype": "CONTINUOUS"},
            {"name": "WALLS", "color": "#e2e8f0", "visible": True, "locked": False, "linetype": "CONTINUOUS"},
            {"name": "DOORS", "color": "#2ecc71", "visible": True, "locked": False, "linetype": "CONTINUOUS"},
            {"name": "WINDOWS", "color": "#3498db", "visible": True, "locked": False, "linetype": "CONTINUOUS"},
            {"name": "FURNITURE", "color": "#f39c12", "visible": True, "locked": False, "linetype": "CONTINUOUS"},
            {"name": "ROOM_NAMES", "color": "#e67e22", "visible": True, "locked": False, "linetype": "CONTINUOUS"},
            {"name": "DIMS", "color": "#00e5ff", "visible": True, "locked": False, "linetype": "CONTINUOUS"},
        ]

        entities: List[Dict[str, Any]] = []
        eid = 1

        def add_line(x1, y1, x2, y2, layer, color=None):
            nonlocal eid
            entities.append({
                "id": f"ent_{eid}", "type": "LINE", "layer": layer,
                "color": color or [l["color"] for l in layers if l["name"] == layer][0],
                "x1": x1, "y1": y1, "x2": x2, "y2": y2
            })
            eid += 1

        def add_poly(pts, layer, closed=True):
            nonlocal eid
            entities.append({
                "id": f"ent_{eid}", "type": "POLYLINE", "layer": layer,
                "color": [l["color"] for l in layers if l["name"] == layer][0],
                "points": pts, "closed": closed
            })
            eid += 1

        def add_text(txt, x, y, layer, h=300):
            nonlocal eid
            entities.append({
                "id": f"ent_{eid}", "type": "TEXT", "layer": layer,
                "color": [l["color"] for l in layers if l["name"] == layer][0],
                "x": x, "y": y, "text": txt, "height": h
            })
            eid += 1

        def add_door(x, y, r, start_ang, end_ang, layer="DOORS"):
            nonlocal eid
            # Door panel line
            rad = math.radians(start_ang)
            add_line(x, y, x + r * math.cos(rad), y + r * math.sin(rad), layer)
            # Door swing arc
            entities.append({
                "id": f"ent_{eid}", "type": "ARC", "layer": layer,
                "color": "#2ecc71", "cx": x, "cy": y, "radius": r,
                "start_angle": start_ang, "end_angle": end_ang
            })
            eid += 1

        # Units in millimeters (12m x 9m apartment)
        # 1. Exterior Walls (Double wall line, 200mm thickness)
        add_poly([[0, 0], [12000, 0], [12000, 9000], [0, 9000]], "WALLS", closed=True)
        add_poly([[200, 200], [11800, 200], [11800, 8800], [200, 8800]], "WALLS", closed=True)

        # 2. Interior Partition Walls
        # Living / Master Bedroom partition at X = 7000
        add_line(7000, 200, 7000, 5200, "WALLS")
        add_line(7150, 200, 7150, 5200, "WALLS")

        # Kitchen / Corridor wall at Y = 5000
        add_line(200, 5000, 4500, 5000, "WALLS")
        add_line(200, 5150, 4500, 5150, "WALLS")

        # Bathroom walls (4500, 5000 to 7000, 8800)
        add_line(4500, 5000, 4500, 8800, "WALLS")
        add_line(4650, 5000, 4650, 8800, "WALLS")
        add_line(4650, 6800, 7000, 6800, "WALLS")
        add_line(4650, 6950, 7000, 6950, "WALLS")

        # Bedroom 2 partition at X = 7000 to 11800, Y = 5000
        add_line(7000, 5000, 11800, 5000, "WALLS")
        add_line(7000, 5150, 11800, 5150, "WALLS")

        # 3. Windows
        # Living room front window
        add_line(1500, 0, 4500, 0, "WINDOWS")
        add_line(1500, 200, 4500, 200, "WINDOWS")
        add_line(1500, 100, 4500, 100, "WINDOWS")

        # Master bedroom window
        add_line(8500, 0, 10500, 0, "WINDOWS")
        add_line(8500, 200, 10500, 200, "WINDOWS")
        add_line(8500, 100, 10500, 100, "WINDOWS")

        # Bedroom 2 window (top wall)
        add_line(8500, 8800, 10500, 8800, "WINDOWS")
        add_line(8500, 9000, 10500, 9000, "WINDOWS")
        add_line(8500, 8900, 10500, 8900, "WINDOWS")

        # Kitchen window
        add_line(1500, 8800, 3500, 8800, "WINDOWS")
        add_line(1500, 9000, 3500, 9000, "WINDOWS")
        add_line(1500, 8900, 3500, 8900, "WINDOWS")

        # 4. Doors with Swings
        # Main entrance door at bottom left (X=5000, Y=200)
        add_door(5200, 200, 900, 90, 180)
        # Master Bedroom door (X=7000, Y=4200)
        add_door(7150, 4200, 850, 0, 90)
        # Bedroom 2 door (X=7150, Y=5300)
        add_door(7150, 5300, 850, 270, 360)
        # Bathroom door (X=4650, Y=5400)
        add_door(4650, 5400, 750, 0, 90)

        # 5. Furniture & Fixtures
        # Master Bed (2000 x 1800)
        add_poly([[8500, 800], [10500, 800], [10500, 2600], [8500, 2600]], "FURNITURE")
        add_line(8500, 1400, 10500, 1400, "FURNITURE")
        # Bedroom 2 Bed
        add_poly([[8500, 6400], [10500, 6400], [10500, 8200], [8500, 8200]], "FURNITURE")
        add_line(8500, 7000, 10500, 7000, "FURNITURE")

        # Living Room Sofa & Coffee Table
        add_poly([[1200, 1200], [3800, 1200], [3800, 2100], [1200, 2100]], "FURNITURE")
        add_poly([[1800, 2600], [3200, 2600], [3200, 3400], [1800, 3400]], "FURNITURE")

        # Dining Table + 4 Chairs
        add_poly([[4200, 2000], [5800, 2000], [5800, 3200], [4200, 3200]], "FURNITURE")

        # Kitchen Counter L-shape
        add_poly([[400, 5400], [3800, 5400], [3800, 6200], [1200, 6200], [1200, 8600], [400, 8600]], "FURNITURE")

        # 6. Room Names & Annotations
        add_text("LIVING & DINING ROOM", 2600, 3800, "ROOM_NAMES", 350)
        add_text("AREA: 34.2 m²", 2800, 3400, "ROOM_NAMES", 240)

        add_text("MASTER SUITE", 8500, 3400, "ROOM_NAMES", 320)
        add_text("AREA: 19.5 m²", 8700, 3050, "ROOM_NAMES", 220)

        add_text("BEDROOM 2", 8700, 6000, "ROOM_NAMES", 300)
        add_text("AREA: 14.8 m²", 8900, 5650, "ROOM_NAMES", 220)

        add_text("KITCHEN", 1800, 7000, "ROOM_NAMES", 300)
        add_text("AREA: 11.2 m²", 1950, 6650, "ROOM_NAMES", 220)

        add_text("BATHROOM", 5000, 7600, "ROOM_NAMES", 280)
        add_text("AREA: 6.4 m²", 5150, 7250, "ROOM_NAMES", 200)

        # 7. Dimensions (Overall Building Outline)
        # Horizontal overall: 12000mm
        entities.append({
            "id": f"ent_{eid}", "type": "DIMENSION", "layer": "DIMS", "color": "#00e5ff",
            "x1": 0, "y1": -700, "x2": 12000, "y2": -700, "text": "12,000 mm"
        })
        eid += 1
        # Vertical overall: 9000mm
        entities.append({
            "id": f"ent_{eid}", "type": "DIMENSION", "layer": "DIMS", "color": "#00e5ff",
            "x1": -700, "y1": 0, "x2": -700, "y2": 9000, "text": "9,000 mm"
        })
        eid += 1

        return {
            "success": True,
            "title": "Apartment Floor Plan",
            "layers": layers,
            "entities": entities,
            "entity_count": len(entities),
            "extents": {
                "min_x": -1000, "min_y": -1000, "max_x": 13000, "max_y": 10000,
                "width": 14000, "height": 11000, "center_x": 6000, "center_y": 4500
            }
        }

    @classmethod
    def _build_structural_grid_sample(cls) -> Dict[str, Any]:
        """Builds a multi-bay structural grid with RC columns and core shear walls."""
        layers = [
            {"name": "0", "color": "#808080", "visible": True, "locked": False, "linetype": "CONTINUOUS"},
            {"name": "GRID", "color": "#ff5252", "visible": True, "locked": False, "linetype": "DASHED"},
            {"name": "COLUMNS", "color": "#ffffff", "visible": True, "locked": False, "linetype": "CONTINUOUS"},
            {"name": "CORE", "color": "#ffeb3b", "visible": True, "locked": False, "linetype": "CONTINUOUS"},
            {"name": "DIMS", "color": "#00e5ff", "visible": True, "locked": False, "linetype": "CONTINUOUS"},
            {"name": "TEXT", "color": "#ffffff", "visible": True, "locked": False, "linetype": "CONTINUOUS"},
        ]
        entities: List[Dict[str, Any]] = []
        eid = 1

        x_bays = [0, 8000, 16000, 24000]
        y_bays = [0, 8000, 16000]

        # Grid lines
        for i, x in enumerate(x_bays):
            label = str(i + 1)
            entities.append({"id": f"ent_{eid}", "type": "LINE", "layer": "GRID", "color": "#ff5252", "x1": x, "y1": -1500, "x2": x, "y2": 17500})
            eid += 1
            # Grid bubble circle
            entities.append({"id": f"ent_{eid}", "type": "CIRCLE", "layer": "GRID", "color": "#ff5252", "cx": x, "cy": 18200, "radius": 600})
            eid += 1
            entities.append({"id": f"ent_{eid}", "type": "TEXT", "layer": "TEXT", "color": "#ffffff", "x": x - 200, "y": 18000, "text": label, "height": 450})
            eid += 1

        for j, y in enumerate(y_bays):
            label = chr(65 + j)  # A, B, C
            entities.append({"id": f"ent_{eid}", "type": "LINE", "layer": "GRID", "color": "#ff5252", "x1": -1500, "y1": y, "x2": 25500, "y2": y})
            eid += 1
            # Grid bubble circle
            entities.append({"id": f"ent_{eid}", "type": "CIRCLE", "layer": "GRID", "color": "#ff5252", "cx": -2200, "cy": y, "radius": 600})
            eid += 1
            entities.append({"id": f"ent_{eid}", "type": "TEXT", "layer": "TEXT", "color": "#ffffff", "x": -2400, "y": y - 200, "text": label, "height": 450})
            eid += 1

        # Columns (800x800 RC columns at grid intersections)
        col_w = 800
        for x in x_bays:
            for y in y_bays:
                # Exclude center if inside core
                if x == 8000 and y == 8000:
                    continue
                entities.append({
                    "id": f"ent_{eid}", "type": "POLYLINE", "layer": "COLUMNS", "color": "#ffffff",
                    "points": [
                        [x - col_w/2, y - col_w/2], [x + col_w/2, y - col_w/2],
                        [x + col_w/2, y + col_w/2], [x - col_w/2, y + col_w/2]
                    ], "closed": True
                })
                eid += 1

        # Central Elevator / Core Shear Walls
        cw = 400
        entities.append({
            "id": f"ent_{eid}", "type": "POLYLINE", "layer": "CORE", "color": "#ffeb3b",
            "points": [
                [6500, 6500], [9500, 6500], [9500, 9500], [6500, 9500]
            ], "closed": True
        })
        eid += 1
        entities.append({
            "id": f"ent_{eid}", "type": "POLYLINE", "layer": "CORE", "color": "#ffeb3b",
            "points": [
                [6500 + cw, 6500 + cw], [9500 - cw, 6500 + cw], [9500 - cw, 9500 - cw], [6500 + cw, 9500 - cw]
            ], "closed": True
        })
        eid += 1

        entities.append({"id": f"ent_{eid}", "type": "TEXT", "layer": "TEXT", "color": "#ffeb3b", "x": 7200, "y": 7900, "text": "CORE / LIFTS", "height": 400})
        eid += 1

        # Dimensions
        entities.append({"id": f"ent_{eid}", "type": "DIMENSION", "layer": "DIMS", "color": "#00e5ff", "x1": 0, "y1": -800, "x2": 8000, "y2": -800, "text": "8,000"})
        eid += 1
        entities.append({"id": f"ent_{eid}", "type": "DIMENSION", "layer": "DIMS", "color": "#00e5ff", "x1": 8000, "y1": -800, "x2": 16000, "y2": -800, "text": "8,000"})
        eid += 1
        entities.append({"id": f"ent_{eid}", "type": "DIMENSION", "layer": "DIMS", "color": "#00e5ff", "x1": 16000, "y1": -800, "x2": 24000, "y2": -800, "text": "8,000"})
        eid += 1

        return {
            "success": True,
            "title": "Structural Column Grid & Core",
            "layers": layers,
            "entities": entities,
            "entity_count": len(entities),
            "extents": {
                "min_x": -3500, "min_y": -2000, "max_x": 27000, "max_y": 20000,
                "width": 30500, "height": 22000, "center_x": 12000, "center_y": 8000
            }
        }

    @classmethod
    def _build_mechanical_bracket_sample(cls) -> Dict[str, Any]:
        """Builds a 2D mechanical mounting bracket drawing with hole array and dimensions."""
        layers = [
            {"name": "0", "color": "#808080", "visible": True, "locked": False, "linetype": "CONTINUOUS"},
            {"name": "OUTLINE", "color": "#00e5ff", "visible": True, "locked": False, "linetype": "CONTINUOUS"},
            {"name": "HOLES", "color": "#ffffff", "visible": True, "locked": False, "linetype": "CONTINUOUS"},
            {"name": "CENTERLINES", "color": "#ff5252", "visible": True, "locked": False, "linetype": "CENTER"},
            {"name": "DIMS", "color": "#2ecc71", "visible": True, "locked": False, "linetype": "CONTINUOUS"},
            {"name": "TEXT", "color": "#ffffff", "visible": True, "locked": False, "linetype": "CONTINUOUS"},
        ]
        entities: List[Dict[str, Any]] = []
        eid = 1

        # Outer bracket plate: 200mm x 120mm
        entities.append({
            "id": f"ent_{eid}", "type": "POLYLINE", "layer": "OUTLINE", "color": "#00e5ff",
            "points": [[-100, -60], [100, -60], [100, 60], [-100, 60]], "closed": True
        })
        eid += 1

        # Center bore hole: radius 25mm
        entities.append({"id": f"ent_{eid}", "type": "CIRCLE", "layer": "HOLES", "color": "#ffffff", "cx": 0, "cy": 0, "radius": 25})
        eid += 1
        # Pitch circle diameter: 80mm
        entities.append({"id": f"ent_{eid}", "type": "CIRCLE", "layer": "CENTERLINES", "color": "#ff5252", "cx": 0, "cy": 0, "radius": 40})
        eid += 1

        # 4 Mounting bolt holes (diameter 10mm -> radius 5mm) on PCD 80mm
        for angle in [45, 135, 225, 315]:
            rad = math.radians(angle)
            hx = round(40 * math.cos(rad), 2)
            hy = round(40 * math.sin(rad), 2)
            entities.append({"id": f"ent_{eid}", "type": "CIRCLE", "layer": "HOLES", "color": "#ffffff", "cx": hx, "cy": hy, "radius": 5})
            eid += 1

        # 4 Corner mounting holes
        for cx, cy in [(-80, -40), (80, -40), (80, 40), (-80, 40)]:
            entities.append({"id": f"ent_{eid}", "type": "CIRCLE", "layer": "HOLES", "color": "#ffffff", "cx": cx, "cy": cy, "radius": 6})
            eid += 1

        # Centerlines
        entities.append({"id": f"ent_{eid}", "type": "LINE", "layer": "CENTERLINES", "color": "#ff5252", "x1": -110, "y1": 0, "x2": 110, "y2": 0})
        eid += 1
        entities.append({"id": f"ent_{eid}", "type": "LINE", "layer": "CENTERLINES", "color": "#ff5252", "x1": 0, "y1": -70, "x2": 0, "y2": 70})
        eid += 1

        # Dimensions
        entities.append({"id": f"ent_{eid}", "type": "DIMENSION", "layer": "DIMS", "color": "#2ecc71", "x1": -100, "y1": -75, "x2": 100, "y2": -75, "text": "200.0"})
        eid += 1
        entities.append({"id": f"ent_{eid}", "type": "DIMENSION", "layer": "DIMS", "color": "#2ecc71", "x1": 115, "y1": -60, "x2": 115, "y2": 60, "text": "120.0"})
        eid += 1

        entities.append({"id": f"ent_{eid}", "type": "TEXT", "layer": "TEXT", "color": "#ffffff", "x": -45, "y": -95, "text": "FLANGE MOUNTING BRACKET", "height": 6})
        eid += 1

        return {
            "success": True,
            "title": "Mechanical Mounting Bracket",
            "layers": layers,
            "entities": entities,
            "entity_count": len(entities),
            "extents": {
                "min_x": -130, "min_y": -110, "max_x": 130, "max_y": 90,
                "width": 260, "height": 200, "center_x": 0, "center_y": -10
            }
        }
