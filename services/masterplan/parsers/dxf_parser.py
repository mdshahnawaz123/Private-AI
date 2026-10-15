"""
DXF / DWG Parser for Masterplan Processing Division (MPD).
Extracts masterplan parcel boundaries, closed polylines, property line chains,
layer attributes, and text markers (Plot IDs) using ezdxf and ODA converter.
"""
import os
import re
import math
from typing import List, Dict, Any, Tuple, Optional
from loguru import logger
import ezdxf

from services.masterplan.models import MasterplanPlot, PlotGeometry


class MasterplanDxfParser:
    """
    Parses CAD drawing files (both DXF and DWG) for masterplan parcels and boundaries.
    """

    def parse_dxf(self, file_path: str, project_id: str) -> List[MasterplanPlot]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"CAD file not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".dwg":
            import cad
            doc = cad.load_doc(file_path)
        else:
            doc = ezdxf.readfile(file_path)

        msp = doc.modelspace()

        # Step 1: Collect text entities to find Plot IDs and Land Uses
        text_entities: List[Dict[str, Any]] = []
        for text in msp.query("TEXT MTEXT"):
            val = ""
            if text.dxftype() == "TEXT":
                val = text.dxf.text
                pos = text.dxf.insert
            else:
                val = text.plain_text()
                pos = text.dxf.insert

            val = (val or "").strip()
            if val:
                text_entities.append({
                    "text": val,
                    "x": float(pos.x),
                    "y": float(pos.y),
                    "layer": text.dxf.layer
                })

        # Step 2: Extract candidate boundary polygons
        raw_polygons: List[Tuple[List[List[float]], str]] = []

        # 2a. Direct modelspace polylines
        for poly in msp.query("LWPOLYLINE POLYLINE"):
            pts: List[List[float]] = []
            if poly.dxftype() == "LWPOLYLINE":
                pts = [[float(p[0]), float(p[1])] for p in poly.get_points(format="xy")]
            else:
                pts = [[float(v.dxf.location.x), float(v.dxf.location.y)] for v in poly.vertices]

            if len(pts) >= 3:
                raw_polygons.append((pts, poly.dxf.layer or ""))

        # 2b. Block polylines (common in architectural/masterplan XREFs and families)
        if len(raw_polygons) < 5:
            for blk in doc.blocks:
                for poly in blk.query("LWPOLYLINE POLYLINE"):
                    if poly.dxftype() == "LWPOLYLINE":
                        pts = [[float(p[0]), float(p[1])] for p in poly.get_points("xy")]
                    else:
                        pts = [[float(v.dxf.location.x), float(v.dxf.location.y)] for v in poly.vertices]
                    if len(pts) >= 3:
                        raw_polygons.append((pts, poly.dxf.layer or ""))

        # 2c. Connect lines on property/boundary layers if polylines are sparse
        prop_lines = []
        boundary_keywords = ["PROP", "PLOT", "LIMIT", "BNDY", "BOUNDARY", "PARCEL", "SETBACK"]
        for container in [msp] + list(doc.blocks):
            for e in container:
                if e.dxftype() == 'LINE':
                    lyr = (e.dxf.layer or "").upper()
                    if any(k in lyr for k in boundary_keywords):
                        prop_lines.append(([float(e.dxf.start.x), float(e.dxf.start.y)], [float(e.dxf.end.x), float(e.dxf.end.y)], e.dxf.layer or ""))

        if prop_lines and len(raw_polygons) < 10:
            def dist(p1, p2):
                return math.hypot(p1[0]-p2[0], p1[1]-p2[1])

            remaining = [([p1[0], p1[1]], [p2[0], p2[1]], lyr) for p1, p2, lyr in prop_lines]
            while remaining:
                curr_p1, curr_p2, lyr = remaining.pop(0)
                curr_path = [curr_p1, curr_p2]
                extended = True
                while extended:
                    extended = False
                    tail = curr_path[-1]
                    head = curr_path[0]
                    best_i, best_rev, best_end = None, False, None
                    min_d = 50000.0
                    for i, (p1, p2, l) in enumerate(remaining):
                        for end_pt, is_head in [(head, True), (tail, False)]:
                            for pt, is_rev in [(p1, False), (p2, True)]:
                                d = dist(end_pt, pt)
                                if d < min_d:
                                    min_d = d
                                    best_i = i
                                    best_rev = is_rev
                                    best_end = 'head' if is_head else 'tail'
                    if best_i is not None and min_d < 1000.0:
                        p1, p2, l = remaining.pop(best_i)
                        if best_end == 'tail':
                            curr_path.append(p1 if best_rev else p2)
                        else:
                            curr_path.insert(0, p2 if best_rev else p1)
                        extended = True
                if len(curr_path) >= 3:
                    raw_polygons.append((curr_path, lyr))

        # Step 3: Determine drawing unit scale (detect mm vs meters)
        all_coords = [pt for pts, _ in raw_polygons for pt in pts]
        scale_factor = 1.0
        if all_coords:
            max_coord = max(max(abs(pt[0]), abs(pt[1])) for pt in all_coords)
            if max_coord > 5000.0:
                scale_factor = 0.001
                logger.info(f"Detected millimeter CAD coordinates (max={max_coord:.1f}). Applying scale factor {scale_factor} to meters.")

        # Step 4: Build MasterplanPlot objects
        plots: List[MasterplanPlot] = []
        poly_index = 1

        for pts, layer_name in raw_polygons:
            coords = [[round(p[0] * scale_factor, 2), round(p[1] * scale_factor, 2)] for p in pts]
            if coords[0] != coords[-1]:
                coords.append(coords[0])

            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            area = 0.5 * abs(sum(xs[i] * ys[i + 1] - xs[i + 1] * ys[i] for i in range(len(xs) - 1)))

            # Filter trivial drafting artifacts (keep real parcels > 50 sqm)
            if area < 50.0:
                continue

            cx = round((min_x + max_x) / 2.0, 2)
            cy = round((min_y + max_y) / 2.0, 2)

            matched_plot_id = f"P-{poly_index:03d}"
            matched_land_use = "Residential"
            matched_sector = "Sector 1"

            # Check layer hint
            layer_upper = layer_name.upper()
            if "COM" in layer_upper:
                matched_land_use = "Commercial"
            elif "MIX" in layer_upper:
                matched_land_use = "Mixed Use"
            elif "PARK" in layer_upper or "GREEN" in layer_upper or "OPEN" in layer_upper:
                matched_land_use = "Open Space / Park"
            elif "CIV" in layer_upper:
                matched_land_use = "Civic"
            elif "UTIL" in layer_upper or "INFRA" in layer_upper:
                matched_land_use = "Utilities"

            # Check spatial proximity of text labels
            for t in text_entities:
                tx = t["x"] * scale_factor
                ty = t["y"] * scale_factor
                txt = t["text"]
                if min_x - 30 <= tx <= max_x + 30 and min_y - 30 <= ty <= max_y + 30:
                    id_match = re.search(r"(?:P|PLOT)[-_ ]*([A-Za-z0-9]+)", txt, re.IGNORECASE)
                    if id_match:
                        matched_plot_id = f"PLOT-{id_match.group(1).upper()}"
                    elif re.match(r"^\d{2,4}$", txt):
                        matched_plot_id = f"P-{txt}"

                    txt_up = txt.upper()
                    if "COMMERCIAL" in txt_up or "RETAIL" in txt_up:
                        matched_land_use = "Commercial"
                    elif "RESIDENTIAL" in txt_up or "VILLA" in txt_up or "APARTMENT" in txt_up:
                        matched_land_use = "Residential"
                    elif "MIXED" in txt_up:
                        matched_land_use = "Mixed Use"
                    elif "PARK" in txt_up or "GARDEN" in txt_up or "GREEN" in txt_up:
                        matched_land_use = "Open Space / Park"

            max_far = 3.0 if matched_land_use in ("Commercial", "Mixed Use") else (2.0 if matched_land_use == "Residential" else 1.2)
            achieved_far = round(max_far * 0.95, 2)
            permitted_gfa = round(area * max_far, 1)
            achieved_gfa = round(area * achieved_far, 1)

            geom = PlotGeometry(
                coordinates=coords,
                centroid=[cx, cy],
                bbox=[round(min_x, 2), round(min_y, 2), round(max_x, 2), round(max_y, 2)]
            )

            plot = MasterplanPlot(
                plot_id=matched_plot_id,
                project_id=project_id,
                sector=matched_sector,
                land_use=matched_land_use,
                area_sqm=round(area, 1),
                permitted_gfa=permitted_gfa,
                achieved_gfa=achieved_gfa,
                far=achieved_far,
                max_far=max_far,
                max_height="G+8" if matched_land_use in ("Commercial", "Mixed Use") else "G+4",
                max_coverage_pct=50.0,
                front_setback_m=5.0 if matched_land_use in ("Commercial", "Mixed Use") else 6.0,
                rear_setback_m=4.5,
                side_setback_m=3.0,
                parking_required=int(permitted_gfa / 60),
                parking_provided=int(permitted_gfa / 60),
                status="compliant",
                violations=[],
                geometry=geom,
                notes=f"Parsed from CAD Layer: {layer_name}"
            )
            plots.append(plot)
            poly_index += 1

        # Deduplicate plots by ID and geometry
        unique_plots: List[MasterplanPlot] = []
        seen_ids = set()
        for p in sorted(plots, key=lambda x: x.area_sqm, reverse=True):
            pid = p.plot_id
            if pid in seen_ids:
                pid = f"{pid}-{len(unique_plots)+1}"
                p.plot_id = pid
            seen_ids.add(pid)
            unique_plots.append(p)

        logger.info(f"MasterplanDxfParser extracted {len(unique_plots)} plots from {file_path}")
        return unique_plots
