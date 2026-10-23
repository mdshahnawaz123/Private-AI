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

try:
    from shapely.geometry import Polygon, Point
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False

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
            try:
                doc = ezdxf.readfile(file_path)
            except Exception as read_err:
                import ezdxf.recover
                logger.warning(f"Standard DXF read failed ({read_err}); attempting fault-tolerant ezdxf recovery...")
                doc, auditor = ezdxf.recover.readfile(file_path)
                if auditor and auditor.has_errors:
                    logger.info(f"ezdxf recovery repaired {len(auditor.errors)} issues in {os.path.basename(file_path)}")

        msp = doc.modelspace()
        from services.masterplan.parsers.hatch_link import linked_hatches
        hatch_records = linked_hatches(doc, os.path.basename(file_path))
        has_hatches = bool(msp.query('HATCH')) or any(bool(block.query('HATCH')) for block in doc.blocks)
        if hatch_records or has_hatches:
            logger.info('Linked {} unambiguous hatch parcels; polygon fallback not mixed into this dataset', len(hatch_records))
            return [MasterplanPlot(project_id=project_id, provenance=[{"filename":os.path.basename(file_path),"page":"CAD Model Space","kind":"cad"}], **record) for record in hatch_records]

        # Step 0: Explode INSERT block references in modelspace to unpack nested text tags and boundary lines (limit depth to protect memory)
        try:
            for ins in list(msp.query("INSERT"))[:500]:
                try:
                    ins.explode()
                except Exception:
                    pass
        except Exception as exc:
            logger.warning(f"Note during block explosion: {exc}")

        # Step 1: Collect text entities to find Plot IDs, Land Uses, GFA, and Heights
        text_entities: List[Dict[str, Any]] = []
        for text in msp.query("TEXT MTEXT"):
            try:
                val = ""
                if text.dxftype() == "TEXT":
                    val = text.dxf.text
                    pos = text.dxf.insert
                else:
                    val = text.plain_text()
                    pos = text.dxf.insert

                val = (val or "").strip()
                if val and pos:
                    text_entities.append({
                        "text": val,
                        "x": float(pos.x),
                        "y": float(pos.y),
                        "layer": text.dxf.layer or ""
                    })
            except Exception:
                continue

        # Step 2: Extract candidate boundary polygons
        raw_polygons: List[Tuple[List[List[float]], str]] = []

        # 2a. Direct modelspace polylines (now including exploded block geometry)
        for poly in msp.query("LWPOLYLINE POLYLINE"):
            pts: List[List[float]] = []
            if poly.dxftype() == "LWPOLYLINE":
                pts = [[float(p[0]), float(p[1])] for p in poly.get_points(format="xy")]
            else:
                pts = [[float(v.dxf.location.x), float(v.dxf.location.y)] for v in poly.vertices]

            if len(pts) >= 3:
                raw_polygons.append((pts, poly.dxf.layer or ""))

        # 2b. Block polylines fallback (for any un-exploded definition blocks)
        if len(raw_polygons) < 5:
            for blk in doc.blocks:
                for poly in blk.query("LWPOLYLINE POLYLINE"):
                    if poly.dxftype() == "LWPOLYLINE":
                        pts = [[float(p[0]), float(p[1])] for p in poly.get_points("xy")]
                    else:
                        pts = [[float(v.dxf.location.x), float(v.dxf.location.y)] for v in poly.vertices]
                    if len(pts) >= 3:
                        raw_polygons.append((pts, poly.dxf.layer or ""))

        # Step 3: Determine drawing unit scale (detect GIS/UTM meters vs architectural millimeters)
        all_coords = [pt for pts, _ in raw_polygons for pt in pts]
        scale_factor = 1.0
        if all_coords:
            xs = [p[0] for p in all_coords]
            ys = [p[1] for p in all_coords]
            min_x_raw, max_x_raw = min(xs), max(xs)
            min_y_raw, max_y_raw = min(ys), max(ys)
            width_raw = max_x_raw - min_x_raw
            height_raw = max_y_raw - min_y_raw

            is_utm = (min_x_raw > 10000 or min_y_raw > 10000) and (width_raw < 100000 and height_raw < 100000)
            if is_utm:
                scale_factor = 1.0
                logger.info(f"Detected GIS / UTM survey coordinates in meters ({width_raw:.1f}x{height_raw:.1f}m span). Scale factor 1.0.")
            elif width_raw > 20000 or height_raw > 20000:
                scale_factor = 0.001
                logger.info(f"Detected millimeter CAD coordinates ({width_raw:.1f}x{height_raw:.1f}mm span). Applying scale factor 0.001 to meters.")
            else:
                scale_factor = 1.0

        # Step 4: Build MasterplanPlot objects
        plots: List[MasterplanPlot] = []
        poly_index = 1

        for pts, layer_name in raw_polygons:
            coords = [[round(p[0] * scale_factor, 3), round(p[1] * scale_factor, 3)] for p in pts]
            if coords[0] != coords[-1]:
                coords.append(coords[0])

            # Coordinate-offset Shoelace formula to prevent precision loss on large UTM survey coordinates
            x0, y0 = coords[0]
            area = 0.5 * abs(sum((coords[i][0] - x0) * (coords[i+1][1] - y0) - (coords[i+1][0] - x0) * (coords[i][1] - y0) for i in range(len(coords) - 1)))

            # Filter trivial drafting artifacts (<30 sqm) or whole-site boundary envelopes (>2,000,000 sqm)
            if area < 30.0 or area > 2000000.0:
                continue

            # Skip layer '0' if it is a giant framing box
            if layer_name == "0" and area > 100000.0:
                continue

            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)

            cx = round((min_x + max_x) / 2.0, 2)
            cy = round((min_y + max_y) / 2.0, 2)

            sh_poly = None
            if HAS_SHAPELY:
                try:
                    sh_poly = Polygon(coords)
                    if not sh_poly.is_valid:
                        sh_poly = sh_poly.buffer(0)
                    cx = round(sh_poly.centroid.x, 2)
                    cy = round(sh_poly.centroid.y, 2)
                except Exception:
                    sh_poly = None

            # Determine land use primarily from CAD Layer
            layer_upper = layer_name.upper()
            matched_land_use = "Residential"
            if "MIX" in layer_upper:
                matched_land_use = "Mixed Use"
            elif "RES" in layer_upper:
                matched_land_use = "Residential"
            elif "COM" in layer_upper:
                matched_land_use = "Commercial"
            elif "HOSP" in layer_upper:
                matched_land_use = "Hospitality"
            elif any(k in layer_upper for k in ("PARK", "OPEN", "GREEN", "PLAZA", "PROMENADE", "GARDEN")):
                matched_land_use = "Open Space / Park"
            elif "CIV" in layer_upper or "PUBLIC" in layer_upper:
                matched_land_use = "Civic"
            elif "UTIL" in layer_upper or "INFRA" in layer_upper:
                matched_land_use = "Utilities"
            elif "SIKKA" in layer_upper:
                matched_land_use = "Sikka"
            elif "ROAD" in layer_upper or "ROW" in layer_upper:
                matched_land_use = "Roads / ROW"
            elif "PARK" in layer_upper or "PRKG" in layer_upper:
                matched_land_use = "Parking"

            # Find enclosed text entities
            enclosed_texts: List[Dict[str, Any]] = []
            for t in text_entities:
                tx = t["x"] * scale_factor
                ty = t["y"] * scale_factor
                if min_x <= tx <= max_x and min_y <= ty <= max_y:
                    if sh_poly is not None:
                        try:
                            if sh_poly.contains(Point(tx, ty)):
                                enclosed_texts.append(t)
                        except Exception:
                            enclosed_texts.append(t)
                    else:
                        enclosed_texts.append(t)

            matched_plot_id = None
            extracted_gfa = None
            extracted_height = None

            # 1. Search for Plot ID: prioritize MP-Plot_ID layer, then 5-8 digit IDs, P-xxx, or sector codes
            id_candidates = [t for t in enclosed_texts if "PLOT" in t["layer"].upper()] + [t for t in enclosed_texts if "PLOT" not in t["layer"].upper()]
            for t in id_candidates:
                txt = t["text"].strip()
                if re.match(r"^\d{5,8}$", txt):
                    matched_plot_id = f"P-{txt}"
                    break
                id_match = re.match(r"^(?:P|PLOT)[-_ ]*([A-Za-z0-9]+)$", txt, re.IGNORECASE)
                if id_match:
                    matched_plot_id = f"P-{id_match.group(1).upper()}"
                    break
                code_match = re.match(r"^[A-Z]{2}\.\d+\.[A-Z]\.\d+$", txt)
                if code_match and not matched_plot_id:
                    matched_plot_id = f"P-{txt}"

            # 2. Extract GFA, height, and land use hints from enclosed texts
            for t in enclosed_texts:
                txt = t["text"].strip()
                txt_up = txt.upper()
                if "GFA:" in txt_up:
                    gfa_m = re.search(r"GFA:\s*([\d,]+)", txt, re.IGNORECASE)
                    if gfa_m:
                        try:
                            val = float(gfa_m.group(1).replace(",", ""))
                            if val > 0 or extracted_gfa is None:
                                extracted_gfa = val
                        except Exception:
                            pass
                elif re.search(r"\b[1-4]?B\+G\+\d+\b", txt, re.IGNORECASE) or re.search(r"\bG\+\d+\b", txt, re.IGNORECASE):
                    extracted_height = txt
                elif "APARTMENT" in txt_up or "RETAIL" in txt_up:
                    matched_land_use = "Mixed Use"
                elif "RESIDENTIAL" in txt_up or "VILLA" in txt_up:
                    matched_land_use = "Residential"
                elif "COMMERCIAL" in txt_up or "OFFICE" in txt_up:
                    matched_land_use = "Commercial"

            if not matched_plot_id:
                matched_plot_id = f"P-CAD-{poly_index:03d}"

            max_far = 3.0 if matched_land_use in ("Commercial", "Mixed Use") else (2.0 if matched_land_use == "Residential" else 1.2)
            achieved_gfa = extracted_gfa or round(area * max_far * 0.95, 1)
            permitted_gfa = extracted_gfa or round(area * max_far, 1)
            achieved_far = round(achieved_gfa / area, 2) if area > 0 else 1.0

            geom = PlotGeometry(
                coordinates=coords,
                centroid=[cx, cy],
                bbox=[round(min_x, 2), round(min_y, 2), round(max_x, 2), round(max_y, 2)]
            )

            plot = MasterplanPlot(
                plot_id=matched_plot_id,
                project_id=project_id,
                sector="Expo Hills",
                land_use=matched_land_use,
                area_sqm=round(area, 1),
                permitted_gfa=permitted_gfa,
                achieved_gfa=achieved_gfa,
                far=achieved_far,
                max_far=max_far,
                max_height=extracted_height or ("G+8" if matched_land_use in ("Commercial", "Mixed Use") else "G+4"),
                max_coverage_pct=50.0,
                front_setback_m=5.0 if matched_land_use in ("Commercial", "Mixed Use") else 6.0,
                rear_setback_m=4.5,
                side_setback_m=3.0,
                parking_required=int(permitted_gfa / 60),
                parking_provided=int(permitted_gfa / 60),
                status="compliant",
                violations=[],
                geometry=geom,
                provenance=[{"filename":os.path.basename(file_path),"page":"CAD Model Space","kind":"cad","layer":layer_name}],
                notes=f"Parsed from CAD Layer: {layer_name}"
            )
            plots.append(plot)
            poly_index += 1

        # Deduplicate plots by ID, keeping named plots over P-CAD-xxx
        unique_plots: List[MasterplanPlot] = []
        seen_ids = set()
        for p in sorted(plots, key=lambda x: (0 if not x.plot_id.startswith("P-CAD-") else 1, -x.area_sqm)):
            pid = p.plot_id
            if pid in seen_ids:
                pid = f"{pid}-{len(unique_plots)+1}"
                p.plot_id = pid
            seen_ids.add(pid)
            unique_plots.append(p)

        logger.info(f"MasterplanDxfParser extracted {len(unique_plots)} plots from {file_path}")
        return unique_plots
