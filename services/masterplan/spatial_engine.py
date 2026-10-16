"""
Spatial Reasoning Engine for MPD (Masterplan Processing Division).
Performs geometric calculations, boundary containment checks, setback compliance,
overlap detection, and zoning regulation audits using Shapely.
"""
from typing import List, Dict, Any, Tuple
from loguru import logger
from shapely.geometry import Polygon, MultiPolygon, Point, box

from services.masterplan.models import MasterplanPlot, PlotGeometry
from services.masterplan import db


class SpatialReasoningEngine:
    """
    Evaluates urban masterplans for spatial and zoning compliance.
    """

    def validate_plot(self, plot: MasterplanPlot) -> Tuple[str, List[str]]:
        """
        Runs comprehensive regulatory checks on a single plot:
        1. FAR Compliance: Achieved GFA vs Permitted FAR * Area
        2. Setback Thresholds: Front, Rear, Side setback minimums
        3. Parking Adequacy: Provided vs Required
        4. Building Height: Story limit vs land use zone
        """
        import json
        try:
            evidence = json.loads(plot.notes or '{}')
        except (ValueError, TypeError):
            evidence = {}
        if isinstance(evidence, dict) and evidence.get('method') == 'hatch_label_containment':
            return 'under_review', ['Hatch/label association only; approved zoning and engineering limits are not established']
        violations: List[str] = []
        status = "compliant"

        # Check FAR
        calculated_far = round(plot.achieved_gfa / plot.area_sqm, 2) if plot.area_sqm > 0 else 0.0
        if calculated_far > plot.max_far:
            diff = calculated_far - plot.max_far
            violations.append(f"FAR {calculated_far:.2f} exceeds maximum permitted FAR {plot.max_far:.2f} (+{diff:.2f})")
            status = "violation"

        # Check Setbacks against typical masterplan minimums
        min_front = 5.0 if plot.land_use in ("Commercial", "Mixed Use") else 6.0
        min_rear = 4.0 if plot.land_use in ("Commercial", "Mixed Use") else 4.5
        min_side = 3.0

        if plot.land_use not in ("Open Space / Park", "Utilities"):
            if plot.front_setback_m < min_front:
                violations.append(f"Front setback {plot.front_setback_m:.1f}m is below required buffer of {min_front:.1f}m")
                status = "violation"
            if plot.rear_setback_m < min_rear:
                violations.append(f"Rear setback {plot.rear_setback_m:.1f}m is below required buffer of {min_rear:.1f}m")
                status = "violation"
            if plot.side_setback_m < min_side:
                violations.append(f"Side setback {plot.side_setback_m:.1f}m is below minimum {min_side:.1f}m")
                status = "violation"

        # Check Parking Deficit
        if plot.parking_required > 0:
            if plot.parking_provided < plot.parking_required:
                deficit = plot.parking_required - plot.parking_provided
                if deficit > 3:
                    violations.append(f"Parking deficit: {plot.parking_provided} provided vs {plot.parking_required} required ({deficit} bay shortfall)")
                    status = "violation"
                else:
                    violations.append(f"Minor parking shortfall: {plot.parking_provided} provided vs {plot.parking_required} required ({deficit} bay shortfall)")
                    if status != "violation":
                        status = "warning"

        # Check Height vs Zone
        if "G+" in plot.max_height:
            try:
                stories = int(plot.max_height.replace("G+", "").strip())
                if plot.land_use == "Residential" and stories > 6:
                    violations.append(f"Building height {plot.max_height} exceeds typical low-rise residential density envelope (G+6)")
                    if status != "violation":
                        status = "warning"
            except Exception:
                pass

        return status, violations

    def check_boundary_overlaps(self, plots: List[MasterplanPlot]) -> List[Dict[str, Any]]:
        """
        Checks for any spatial boundary intersections or encroachments among plots.
        """
        overlap_issues = []
        plot_polys: List[Tuple[str, Polygon]] = []

        for p in plots:
            if p.geometry and p.geometry.coordinates and len(p.geometry.coordinates) >= 3:
                try:
                    poly = Polygon(p.geometry.coordinates)
                    if poly.is_valid:
                        plot_polys.append((p.plot_id, poly))
                except Exception:
                    pass

        # Pairwise intersection
        n = len(plot_polys)
        for i in range(n):
            for j in range(i + 1, n):
                pid1, poly1 = plot_polys[i]
                pid2, poly2 = plot_polys[j]
                if poly1.intersects(poly2):
                    intersection = poly1.intersection(poly2)
                    if intersection.area > 1.0:  # Ignore microscopic line contact
                        overlap_issues.append({
                            "plot_1": pid1,
                            "plot_2": pid2,
                            "overlap_area_sqm": round(intersection.area, 2),
                            "description": f"Boundary encroachment between Plot {pid1} and Plot {pid2} ({intersection.area:.1f} m²)"
                        })

        return overlap_issues

    def calculate_setback_polygon(self, coords: List[List[float]], front_m: float, rear_m: float, side_m: float) -> List[List[float]]:
        """
        Computes the inner buildable envelope polygon by applying setback offsets.
        """
        try:
            poly = Polygon(coords)
            if not poly.is_valid:
                return coords
            avg_setback = (front_m + rear_m + 2 * side_m) / 4.0
            # Inner buffer offset
            inner = poly.buffer(-avg_setback)
            if inner.is_empty:
                return coords
            if isinstance(inner, Polygon):
                return [[round(x, 2), round(y, 2)] for x, y in inner.exterior.coords]
            elif isinstance(inner, MultiPolygon):
                largest = max(inner.geoms, key=lambda p: p.area)
                return [[round(x, 2), round(y, 2)] for x, y in largest.exterior.coords]
        except Exception as exc:
            logger.warning(f"Error computing setback polygon: {exc}")
        return coords

    def run_project_audit(self, project_id: str) -> Dict[str, Any]:
        """
        Executes a complete spatial and zoning audit on the masterplan database.
        Updates each plot's compliance state and logs the review audit.
        """
        plots = db.get_plots(project_id)
        violations_count = 0
        warnings_count = 0
        compliant_count = 0

        for plot in plots:
            st, viols = self.validate_plot(plot)
            plot.status = st
            plot.violations = viols
            if st == "violation":
                violations_count += 1
            elif st == "warning":
                warnings_count += 1
            else:
                compliant_count += 1

        # Check spatial boundary overlaps
        overlap_clashes = self.check_boundary_overlaps(plots)
        for clash in overlap_clashes:
            p1 = next((p for p in plots if p.plot_id == clash["plot_1"]), None)
            p2 = next((p for p in plots if p.plot_id == clash["plot_2"]), None)
            if p1 and clash["description"] not in p1.violations:
                p1.violations.append(clash["description"])
                p1.status = "violation"
            if p2 and clash["description"] not in p2.violations:
                p2.violations.append(clash["description"])
                p2.status = "violation"

        # Persist updated plots
        db.save_plots_bulk(project_id, plots, author="Spatial Reasoning Engine")

        # Log audit entry
        db.log_audit(
            project_id=project_id,
            action_type="SPATIAL_AUDIT",
            description=f"Completed automated spatial audit: {compliant_count} compliant, {warnings_count} warnings, {violations_count} violations, {len(overlap_clashes)} boundary clashes detected",
            author="Spatial Reasoning Engine"
        )

        return {
            "project_id": project_id,
            "total_plots": len(plots),
            "compliant": compliant_count,
            "warnings": warnings_count,
            "violations": violations_count,
            "overlap_clashes": overlap_clashes,
            "audit_status": "COMPLETED"
        }
