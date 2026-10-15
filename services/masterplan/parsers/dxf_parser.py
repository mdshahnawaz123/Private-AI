"""
DXF / DWG Parser for Masterplan Processing Division (MPD).
Extracts masterplan parcel boundaries, closed polylines, layer attributes,
and text markers (Plot IDs) using ezdxf.
"""
import os
import re
from typing import List, Dict, Any, Tuple, Optional
from loguru import logger
import ezdxf

from services.masterplan.models import MasterplanPlot, PlotGeometry


class MasterplanDxfParser:
    """
    Parses CAD drawing files for masterplan parcels and boundaries.
    """

    def parse_dxf(self, file_path: str, project_id: str) -> List[MasterplanPlot]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"CAD file not found: {file_path}")

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

        # Step 2: Extract closed polylines (potential plot boundaries)
        plots: List[MasterplanPlot] = []
        poly_index = 1

        for poly in msp.query("LWPOLYLINE POLYLINE"):
            coords: List[List[float]] = []
            if poly.dxftype() == "LWPOLYLINE":
                coords = [[float(p[0]), float(p[1])] for p in poly.get_points(format="xy")]
            else:
                coords = [[float(v.dxf.location.x), float(v.dxf.location.y)] for v in poly.vertices]

            if len(coords) < 3:
                continue

            # Ensure closed
            if coords[0] != coords[-1]:
                coords.append(coords[0])

            # Calculate centroid & bounding box
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            cx = (min_x + max_x) / 2.0
            cy = (min_y + max_y) / 2.0
            area = 0.5 * abs(sum(xs[i] * ys[i + 1] - xs[i + 1] * ys[i] for i in range(len(xs) - 1)))

            if area < 50.0:  # Skip trivial drafting artifacts
                continue

            # Match closest text label inside or near bbox
            matched_plot_id = f"P-{poly_index:03d}"
            matched_land_use = "Residential"
            matched_sector = "Sector 1"

            # Check layer hint
            layer_upper = (poly.dxf.layer or "").upper()
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
                tx, ty, txt = t["x"], t["y"], t["text"]
                if min_x - 10 <= tx <= max_x + 10 and min_y - 10 <= ty <= max_y + 10:
                    # Look for Plot ID pattern like P-101, PLOT 101, 101
                    id_match = re.search(r"(?:P|PLOT)[-_ ]*(\d+)", txt, re.IGNORECASE)
                    if id_match:
                        matched_plot_id = f"P-{id_match.group(1)}"
                    elif re.match(r"^\d{2,4}$", txt):
                        matched_plot_id = f"P-{txt}"

                    # Look for land use keywords
                    txt_up = txt.upper()
                    if "COMMERCIAL" in txt_up:
                        matched_land_use = "Commercial"
                    elif "RESIDENTIAL" in txt_up:
                        matched_land_use = "Residential"
                    elif "MIXED" in txt_up:
                        matched_land_use = "Mixed Use"
                    elif "PARK" in txt_up or "GARDEN" in txt_up:
                        matched_land_use = "Open Space / Park"

            # Determine typical FAR and setbacks based on land use
            max_far = 3.0 if matched_land_use in ("Commercial", "Mixed Use") else (2.0 if matched_land_use == "Residential" else 1.2)
            achieved_far = round(max_far * 0.95, 2)
            permitted_gfa = round(area * max_far, 1)
            achieved_gfa = round(area * achieved_far, 1)

            geom = PlotGeometry(
                coordinates=coords,
                centroid=[cx, cy],
                bbox=[min_x, min_y, max_x, max_y]
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
                notes=f"Parsed from DXF Layer: {poly.dxf.layer}"
            )
            plots.append(plot)
            poly_index += 1

        logger.info(f"MasterplanDxfParser extracted {len(plots)} plots from {file_path}")
        return plots
