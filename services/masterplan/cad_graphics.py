"""
CAD / PDF Graphics Engine for Masterplan Processing Division (MPD).
Generates highlighted CAD copy (DXF) with color-coded layers, setback offsets,
violation highlights, and vector annotations, as well as PDF validation reports.
"""
import os
import io
from typing import List, Dict, Any, Optional
from loguru import logger
import ezdxf
from ezdxf import colors

from services.masterplan.models import MasterplanPlot
from services.masterplan import db


class MasterplanGraphicsEngine:
    """
    Renders highlighted CAD files and reports from masterplan database records.
    """

    COLOR_MAP = {
        "Residential": 2,      # Yellow
        "Commercial": 1,       # Red
        "Mixed Use": 6,        # Magenta
        "Open Space / Park": 3,# Green
        "Civic": 4,            # Cyan
        "Utilities": 8,        # Dark Gray
        "Highlighted": 40,     # Bright Orange
        "Violation": 1         # Red
    }

    def generate_highlighted_dxf(self, project_id: str, highlight_ids: Optional[List[str]] = None) -> str:
        """
        Creates an AutoCAD-compliant DXF file with layered parcels,
        inner setback boundaries, and highlighted review selections.
        """
        plots = db.get_plots(project_id)
        highlight_set = set(highlight_ids or [])

        doc = ezdxf.new(dxfversion="R2018")
        msp = doc.modelspace()

        # Setup standard CAD Layers
        layers = [
            ("MP_RESIDENTIAL", 2),
            ("MP_COMMERCIAL", 1),
            ("MP_MIXED_USE", 6),
            ("MP_OPEN_SPACE", 3),
            ("MP_CIVIC", 4),
            ("MP_UTILITIES", 8),
            ("MP_SETBACK_LINES", 4),
            ("MP_VIOLATIONS", 1),
            ("MP_HIGHLIGHTED", 40),
            ("MP_LABELS", 7)
        ]
        for name, col in layers:
            if name not in doc.layers:
                doc.layers.add(name, color=col)

        for plot in plots:
            geom = plot.geometry
            if not geom or not geom.coordinates or len(geom.coordinates) < 3:
                continue

            is_hl = plot.plot_id in highlight_set
            is_viol = plot.status == "violation"

            target_layer = "MP_RESIDENTIAL"
            if is_hl:
                target_layer = "MP_HIGHLIGHTED"
            elif is_viol:
                target_layer = "MP_VIOLATIONS"
            else:
                lu = plot.land_use or "Residential"
                if "COMMERCIAL" in lu.upper():
                    target_layer = "MP_COMMERCIAL"
                elif "MIXED" in lu.upper():
                    target_layer = "MP_MIXED_USE"
                elif "OPEN" in lu.upper() or "PARK" in lu.upper():
                    target_layer = "MP_OPEN_SPACE"
                elif "CIVIC" in lu.upper():
                    target_layer = "MP_CIVIC"
                elif "UTIL" in lu.upper():
                    target_layer = "MP_UTILITIES"

            # Draw outer plot polyline
            pts = [(float(c[0]), float(c[1])) for c in geom.coordinates]
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": target_layer, "lineweight": 35 if is_hl else 20})

            # Draw setback envelope if available
            if geom.setback_envelope and len(geom.setback_envelope) >= 3:
                sb_pts = [(float(c[0]), float(c[1])) for c in geom.setback_envelope]
                msp.add_lwpolyline(sb_pts, close=True, dxfattribs={"layer": "MP_SETBACK_LINES", "lineweight": 13})

            # Add Text Label at Centroid
            cx, cy = geom.centroid if geom.centroid else (pts[0][0] + 10, pts[0][1] + 10)
            label_text = f"{plot.plot_id}\n{plot.land_use}\nFAR: {plot.far:.2f}"
            msp.add_text(
                plot.plot_id,
                dxfattribs={
                    "layer": "MP_LABELS",
                    "height": 6.0 if is_hl else 4.0,
                    "insert": (cx - 15, cy + 4)
                }
            )
            msp.add_text(
                f"{plot.land_use} (FAR {plot.far:.2f})",
                dxfattribs={
                    "layer": "MP_LABELS",
                    "height": 3.0,
                    "insert": (cx - 20, cy - 6)
                }
            )

        # Output folder in data/cad_cache/
        out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "cad_cache")
        os.makedirs(out_dir, exist_ok=True)
        safe_proj = project_id.replace(" ", "_").replace("-", "_")
        out_filename = f"MPD_{safe_proj}_Review_Highlighted.dxf"
        out_path = os.path.join(out_dir, out_filename)
        doc.saveas(out_path)
        logger.info(f"Generated highlighted CAD DXF: {out_path}")
        return out_path
