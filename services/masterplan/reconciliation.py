"""
Multi-Source Masterplan Cross-Reconciliation Engine for MPD.
Correlates CAD/DWG vector geometry, Excel development schedules/registers, and PDF zoning regulations.
Detects discrepancies (area mismatches, FAR conflicts, missing entities) and generates structured
clarification questions for the user to stabilize and link the ground-truth relationship.
"""
import re
from typing import List, Dict, Any, Tuple, Optional
from loguru import logger

from services.masterplan.models import MasterplanPlot, PlotGeometry
from services.masterplan import db
from services.masterplan.spatial_engine import SpatialReasoningEngine

spatial_engine = SpatialReasoningEngine()


def normalize_plot_id(raw_id: str) -> str:
    """Normalizes various plot string formats ('p-101', 'PLOT 101', 'P101', '5211024') -> 'P-101'."""
    s = (raw_id or "").strip().upper()
    m = re.match(r"^P?[-_ ]*0*(\d+)$", s)
    if m:
        num = int(m.group(1))
        if num < 1000:
            return f"P-{num:03d}"
        return f"P-{num}"
    if not s.startswith("P-"):
        return f"P-{s}"
    return s


class MasterplanReconciliationEngine:
    """
    Engine to reconcile CAD geometry with Excel tabular registers and PDF zoning rules.
    """

    def analyze_correlation(
        self,
        cad_plots: List[MasterplanPlot],
        excel_plots: List[MasterplanPlot],
        cad_filename: str = "CAD Drawing",
        excel_filename: str = "Excel Schedule"
    ) -> Dict[str, Any]:
        """
        Cross-checks CAD polygons against Excel registers.
        Detects exact matches, area differences, FAR conflicts, and missing parcels.
        """
        cad_map: Dict[str, MasterplanPlot] = {normalize_plot_id(p.plot_id): p for p in cad_plots}
        excel_map: Dict[str, MasterplanPlot] = {normalize_plot_id(p.plot_id): p for p in excel_plots}

        all_ids = sorted(list(set(cad_map.keys()) | set(excel_map.keys())))
        matched_ids = [pid for pid in all_ids if pid in cad_map and pid in excel_map]
        cad_only_ids = [pid for pid in all_ids if pid in cad_map and pid not in excel_map]
        excel_only_ids = [pid for pid in all_ids if pid in excel_map and pid not in cad_map]

        discrepancies: List[Dict[str, Any]] = []

        for pid in matched_ids:
            cad_p = cad_map[pid]
            exc_p = excel_map[pid]

            # 1. Area discrepancy check (> 3% difference)
            c_area = cad_p.area_sqm or 0.0
            e_area = exc_p.area_sqm or 0.0

            if c_area > 0 and e_area > 0:
                diff_pct = abs(c_area - e_area) / c_area * 100.0
                if diff_pct > 3.0:
                    discrepancies.append({
                        "plot_id": pid,
                        "type": "area_mismatch",
                        "field": "area_sqm",
                        "title": f"Plot {pid} Area Mismatch",
                        "cad_val": round(c_area),
                        "excel_val": round(e_area),
                        "diff_pct": round(diff_pct, 1),
                        "question": (
                            f"Plot **{pid}** footprint boundary in CAD measures **{round(c_area):,} m²**, "
                            f"while the Excel development register records **{round(e_area):,} m²** (diff: {round(diff_pct, 1)}%). "
                            f"Which source should be stabilized as the masterplan ground truth?"
                        ),
                        "options": [
                            {"label": f"Adopt CAD Geometry ({round(c_area):,} m²)", "value": "cad"},
                            {"label": f"Adopt Excel Schedule ({round(e_area):,} m²)", "value": "excel"}
                        ],
                        "recommended": "cad"
                    })

            # 2. FAR Limit Compliance Check
            max_far = exc_p.max_far or 2.5
            ach_gfa = exc_p.achieved_gfa or (exc_p.permitted_gfa or 0.0)
            if c_area > 0 and ach_gfa > 0:
                calc_far = round(ach_gfa / c_area, 2)
                if calc_far > max_far:
                    excess_gfa = round(ach_gfa - (c_area * max_far))
                    discrepancies.append({
                        "plot_id": pid,
                        "type": "far_conflict",
                        "field": "far",
                        "title": f"Plot {pid} Exceeds Permitted FAR",
                        "cad_val": f"FAR {calc_far:.2f}",
                        "excel_val": f"Max FAR {max_far:.2f}",
                        "question": (
                            f"Based on CAD parcel area (**{round(c_area):,} m²**), achieved GFA (**{round(ach_gfa):,} m²**) "
                            f"results in **FAR {calc_far:.2f}**, which exceeds the maximum allowable **FAR {max_far:.2f}** by +{excess_gfa:,} m² GFA."
                        ),
                        "options": [
                            {"label": f"Cap GFA to Max FAR {max_far} ({round(c_area * max_far):,} m²)", "value": "cap_gfa"},
                            {"label": f"Retain Proposed GFA ({round(ach_gfa):,} m²) and Flag Violation", "value": "retain_violation"}
                        ],
                        "recommended": "retain_violation"
                    })

        # 3. Missing in CAD check (capped at 3 items to avoid overwhelming chat)
        max_missing_to_show = 3 if len(excel_only_ids) > 5 else len(excel_only_ids)
        for pid in excel_only_ids[:max_missing_to_show]:
            exc_p = excel_map[pid]
            discrepancies.append({
                "plot_id": pid,
                "type": "missing_geometry",
                "field": "geometry",
                "title": f"Plot {pid} Missing in CAD Drawing",
                "cad_val": "Not Drawn",
                "excel_val": f"{round(exc_p.area_sqm):,} m²",
                "question": f"Plot **{pid}** is recorded in the Excel schedule with GFA {round(exc_p.achieved_gfa):,} m², but no closed boundary polygon was found in the CAD drawing.",
                "options": [
                    {"label": "Flag Missing Boundary for CAD Drafter", "value": "flag_missing"},
                    {"label": "Exclude from Vector Map", "value": "exclude"}
                ],
                "recommended": "flag_missing"
            })

        status = "requires_clarification" if discrepancies else "ready_to_link"

        return {
            "status": status,
            "cad_file": cad_filename,
            "excel_file": excel_filename,
            "total_plots": len(all_ids),
            "matched_plots": len(matched_ids),
            "cad_only_plots": len(cad_only_ids),
            "excel_only_plots": len(excel_only_ids),
            "discrepancies": discrepancies,
            "is_aligned": len(discrepancies) == 0,
            "summary_text": (
                f"Reconciliation correlated {len(matched_ids)}/{len(all_ids)} plots between '{cad_filename}' "
                f"and '{excel_filename}'. "
                + (f"Detected {len(discrepancies)} discrepancy/clarification items." if discrepancies else "All parcels and parameters perfectly aligned!")
            )
        }

    def stabilize_and_merge(
        self,
        project_id: str,
        cad_plots: List[MasterplanPlot],
        excel_plots: List[MasterplanPlot],
        resolutions: Dict[str, str],
        author: str = "Admin"
    ) -> List[MasterplanPlot]:
        """
        Fuses CAD geometries with Excel registers based on user-confirmed resolutions.
        Persists the stabilized masterplan ground truth into the SQLite database.
        """
        cad_map: Dict[str, MasterplanPlot] = {normalize_plot_id(p.plot_id): p for p in cad_plots}
        excel_map: Dict[str, MasterplanPlot] = {normalize_plot_id(p.plot_id): p for p in excel_plots}
        all_ids = sorted(list(set(cad_map.keys()) | set(excel_map.keys())))

        merged_plots: List[MasterplanPlot] = []

        for pid in all_ids:
            cad_p = cad_map.get(pid)
            exc_p = excel_map.get(pid)

            if cad_p and exc_p:
                # Merge: CAD geometry + Excel attributes
                res_choice = resolutions.get(pid, "cad")

                # Area decision
                if res_choice == "excel":
                    final_area = exc_p.area_sqm or cad_p.area_sqm
                else:
                    final_area = cad_p.area_sqm or exc_p.area_sqm

                # GFA decision
                ach_gfa = exc_p.achieved_gfa or cad_p.achieved_gfa or (exc_p.permitted_gfa or 0.0)
                max_far = exc_p.max_far or cad_p.max_far or 2.5

                if resolutions.get(f"{pid}_far") == "cap_gfa" or resolutions.get(pid) == "cap_gfa":
                    ach_gfa = round(final_area * max_far, 0)

                calc_far = round(ach_gfa / final_area, 2) if final_area > 0 else 0.0

                plot = MasterplanPlot(
                    plot_id=pid,
                    project_id=project_id,
                    sector=exc_p.sector or cad_p.sector or "Sector 1",
                    land_use=exc_p.land_use or cad_p.land_use or "Residential",
                    area_sqm=final_area,
                    permitted_gfa=exc_p.permitted_gfa or (final_area * max_far),
                    achieved_gfa=ach_gfa,
                    far=calc_far,
                    max_far=max_far,
                    max_height=exc_p.max_height or "G+4",
                    max_coverage_pct=exc_p.max_coverage_pct or 50.0,
                    front_setback_m=exc_p.front_setback_m or cad_p.front_setback_m or 6.0,
                    rear_setback_m=exc_p.rear_setback_m or cad_p.rear_setback_m or 4.5,
                    side_setback_m=exc_p.side_setback_m or cad_p.side_setback_m or 3.0,
                    parking_required=exc_p.parking_required or int(ach_gfa / 100),
                    parking_provided=exc_p.parking_provided or int(ach_gfa / 100),
                    geometry=cad_p.geometry,
                    notes=f"Reconciled from CAD geometry & Excel register ({author})"
                )

                # Validate spatial and zoning rules
                st, viols = spatial_engine.validate_plot(plot)
                plot.status = st
                plot.violations = viols
                merged_plots.append(plot)

            elif cad_p and not exc_p:
                # CAD only
                plot = cad_p.copy()
                plot.project_id = project_id
                plot.plot_id = pid
                st, viols = spatial_engine.validate_plot(plot)
                plot.status = st
                plot.violations = viols
                merged_plots.append(plot)

            elif exc_p and not cad_p:
                if resolutions.get(pid) != "exclude":
                    plot = exc_p.copy()
                    plot.project_id = project_id
                    plot.plot_id = pid
                    plot.status = "warning"
                    plot.violations = ["Missing boundary geometry in CAD drawing"]
                    merged_plots.append(plot)

        # Save to database
        db.save_plots_bulk(project_id, merged_plots, author=f"Relation Stabilization ({author})")
        spatial_engine.run_project_audit(project_id)
        logger.info(f"Successfully stabilized relationship for {len(merged_plots)} plots in project '{project_id}'.")
        return merged_plots
