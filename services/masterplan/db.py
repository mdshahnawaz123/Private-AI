"""
SQLite Database storage and persistence for MPD (Masterplan Processing Division).
Stores masterplan projects, plot registers, spatial geometries, and audit logs.
"""
import os
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from loguru import logger
from services.masterplan.models import MasterplanPlot, MasterplanProject, AuditLogEntry, PlotGeometry

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "masterplan.db")


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    conn = get_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mp_projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    boundary_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mp_plots (
                    plot_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    sector TEXT,
                    land_use TEXT,
                    area_sqm REAL DEFAULT 0,
                    permitted_gfa REAL DEFAULT 0,
                    achieved_gfa REAL DEFAULT 0,
                    far REAL DEFAULT 0,
                    max_far REAL DEFAULT 2.5,
                    max_height TEXT DEFAULT 'G+4',
                    max_coverage_pct REAL DEFAULT 50.0,
                    front_setback_m REAL DEFAULT 6.0,
                    rear_setback_m REAL DEFAULT 4.5,
                    side_setback_m REAL DEFAULT 3.0,
                    parking_required INTEGER DEFAULT 0,
                    parking_provided INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'compliant',
                    violations_json TEXT DEFAULT '[]',
                    geometry_json TEXT,
                    notes TEXT DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, plot_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mp_audit_log (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    plot_id TEXT,
                    description TEXT NOT NULL,
                    previous_state_json TEXT,
                    new_state_json TEXT,
                    author TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mp_files (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    file_size INTEGER DEFAULT 0,
                    file_path TEXT NOT NULL,
                    status TEXT DEFAULT 'uploaded',
                    plots_count INTEGER DEFAULT 0,
                    meta_json TEXT DEFAULT '{}',
                    uploaded_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mp_file_relations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    cad_file TEXT,
                    excel_file TEXT,
                    pdf_file TEXT,
                    status TEXT NOT NULL,
                    matched_plots INTEGER DEFAULT 0,
                    discrepancies_json TEXT DEFAULT '[]',
                    resolutions_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mp_plots_project ON mp_plots(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mp_audit_project ON mp_audit_log(project_id, timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mp_files_project ON mp_files(project_id, uploaded_at)")
    finally:
        conn.close()

# Initialize tables on import
init_db()


def row_to_plot(row: sqlite3.Row) -> MasterplanPlot:
    geom_data = None
    if row["geometry_json"]:
        try:
            g = json.loads(row["geometry_json"])
            geom_data = PlotGeometry(**g)
        except Exception:
            pass

    violations = []
    if row["violations_json"]:
        try:
            violations = json.loads(row["violations_json"])
        except Exception:
            pass

    return MasterplanPlot(
        plot_id=row["plot_id"],
        project_id=row["project_id"],
        sector=row["sector"] or "Sector 1",
        land_use=row["land_use"] or "Residential",
        area_sqm=float(row["area_sqm"] or 0),
        permitted_gfa=float(row["permitted_gfa"] or 0),
        achieved_gfa=float(row["achieved_gfa"] or 0),
        far=float(row["far"] or 0),
        max_far=float(row["max_far"] or 2.5),
        max_height=row["max_height"] or "G+4",
        max_coverage_pct=float(row["max_coverage_pct"] or 50.0),
        front_setback_m=float(row["front_setback_m"] or 6.0),
        rear_setback_m=float(row["rear_setback_m"] or 4.5),
        side_setback_m=float(row["side_setback_m"] or 3.0),
        parking_required=int(row["parking_required"] or 0),
        parking_provided=int(row["parking_provided"] or 0),
        status=row["status"] or "compliant",
        violations=violations,
        geometry=geom_data,
        notes=row["notes"] or "",
        updated_at=row["updated_at"]
    )


def get_plots(project_id: str, land_use: Optional[str] = None, sector: Optional[str] = None, status: Optional[str] = None, search: Optional[str] = None) -> List[MasterplanPlot]:
    init_db()
    conn = get_connection()
    try:
        query = "SELECT * FROM mp_plots WHERE project_id = ?"
        params: List[Any] = [project_id]

        if land_use and land_use != "All":
            query += " AND land_use = ?"
            params.append(land_use)
        if sector and sector != "All":
            query += " AND sector = ?"
            params.append(sector)
        if status and status != "All":
            query += " AND status = ?"
            params.append(status)
        if search:
            query += " AND (plot_id LIKE ? OR sector LIKE ? OR land_use LIKE ? OR notes LIKE ?)"
            s_param = f"%{search}%"
            params.extend([s_param, s_param, s_param, s_param])

        query += " ORDER BY plot_id ASC"
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        return [row_to_plot(r) for r in rows]
    finally:
        conn.close()


def get_plot(project_id: str, plot_id: str) -> Optional[MasterplanPlot]:
    init_db()
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT * FROM mp_plots WHERE project_id = ? AND plot_id = ?", (project_id, plot_id))
        row = cursor.fetchone()
        return row_to_plot(row) if row else None
    finally:
        conn.close()


def save_plot(project_id: str, plot: MasterplanPlot, author: str = "Design Review Meeting") -> MasterplanPlot:
    init_db()
    conn = get_connection()
    now_iso = datetime.now(timezone.utc).isoformat()
    plot.updated_at = now_iso
    prev = get_plot(project_id, plot.plot_id)

    geom_json = json.dumps(plot.geometry.dict()) if plot.geometry else None
    viol_json = json.dumps(plot.violations)

    try:
        with conn:
            conn.execute("""
                INSERT INTO mp_plots (
                    plot_id, project_id, sector, land_use, area_sqm, permitted_gfa, achieved_gfa,
                    far, max_far, max_height, max_coverage_pct, front_setback_m, rear_setback_m,
                    side_setback_m, parking_required, parking_provided, status, violations_json,
                    geometry_json, notes, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, plot_id) DO UPDATE SET
                    sector=excluded.sector, land_use=excluded.land_use, area_sqm=excluded.area_sqm,
                    permitted_gfa=excluded.permitted_gfa, achieved_gfa=excluded.achieved_gfa,
                    far=excluded.far, max_far=excluded.max_far, max_height=excluded.max_height,
                    max_coverage_pct=excluded.max_coverage_pct, front_setback_m=excluded.front_setback_m,
                    rear_setback_m=excluded.rear_setback_m, side_setback_m=excluded.side_setback_m,
                    parking_required=excluded.parking_required, parking_provided=excluded.parking_provided,
                    status=excluded.status, violations_json=excluded.violations_json,
                    geometry_json=COALESCE(excluded.geometry_json, mp_plots.geometry_json),
                    notes=excluded.notes, updated_at=excluded.updated_at
            """, (
                plot.plot_id, project_id, plot.sector, plot.land_use, plot.area_sqm, plot.permitted_gfa,
                plot.achieved_gfa, plot.far, plot.max_far, plot.max_height, plot.max_coverage_pct,
                plot.front_setback_m, plot.rear_setback_m, plot.side_setback_m, plot.parking_required,
                plot.parking_provided, plot.status, viol_json, geom_json, plot.notes or "", now_iso
            ))

        # Log audit entry
        log_audit(
            project_id=project_id,
            action_type="UPDATE_PLOT" if prev else "CREATE_PLOT",
            description=f"Updated parameters for Plot {plot.plot_id} ({plot.land_use}, FAR: {plot.far:.2f})",
            plot_id=plot.plot_id,
            previous_state=prev.dict() if prev else None,
            new_state=plot.dict(),
            author=author
        )
        return plot
    finally:
        conn.close()


def save_plots_bulk(project_id: str, plots: List[MasterplanPlot], author: str = "Batch Import"):
    init_db()
    conn = get_connection()
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        with conn:
            for plot in plots:
                plot.updated_at = now_iso
                geom_json = json.dumps(plot.geometry.dict()) if plot.geometry else None
                viol_json = json.dumps(plot.violations)
                conn.execute("""
                    INSERT INTO mp_plots (
                        plot_id, project_id, sector, land_use, area_sqm, permitted_gfa, achieved_gfa,
                        far, max_far, max_height, max_coverage_pct, front_setback_m, rear_setback_m,
                        side_setback_m, parking_required, parking_provided, status, violations_json,
                        geometry_json, notes, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_id, plot_id) DO UPDATE SET
                        sector=excluded.sector, land_use=excluded.land_use, area_sqm=excluded.area_sqm,
                        permitted_gfa=excluded.permitted_gfa, achieved_gfa=excluded.achieved_gfa,
                        far=excluded.far, max_far=excluded.max_far, max_height=excluded.max_height,
                        max_coverage_pct=excluded.max_coverage_pct, front_setback_m=excluded.front_setback_m,
                        rear_setback_m=excluded.rear_setback_m, side_setback_m=excluded.side_setback_m,
                        parking_required=excluded.parking_required, parking_provided=excluded.parking_provided,
                        status=excluded.status, violations_json=excluded.violations_json,
                        geometry_json=COALESCE(excluded.geometry_json, mp_plots.geometry_json),
                        notes=excluded.notes, updated_at=excluded.updated_at
                """, (
                    plot.plot_id, project_id, plot.sector, plot.land_use, plot.area_sqm, plot.permitted_gfa,
                    plot.achieved_gfa, plot.far, plot.max_far, plot.max_height, plot.max_coverage_pct,
                    plot.front_setback_m, plot.rear_setback_m, plot.side_setback_m, plot.parking_required,
                    plot.parking_provided, plot.status, viol_json, geom_json, plot.notes or "", now_iso
                ))
        log_audit(
            project_id=project_id,
            action_type="BULK_IMPORT",
            description=f"Batch synchronized {len(plots)} plots into Masterplan Register",
            author=author
        )
    finally:
        conn.close()


def get_project_summary(project_id: str) -> MasterplanProject:
    plots = get_plots(project_id)
    if not plots:
        seed_default_masterplan(project_id)
        plots = get_plots(project_id)

    total_area = sum(p.area_sqm for p in plots)
    total_gfa = sum(p.achieved_gfa for p in plots)
    avg_far = (total_gfa / total_area) if total_area > 0 else 0.0

    compliant = sum(1 for p in plots if p.status == "compliant")
    warning = sum(1 for p in plots if p.status == "warning")
    violation = sum(1 for p in plots if p.status == "violation")

    breakdown: Dict[str, Dict[str, Any]] = {}
    for p in plots:
        lu = p.land_use or "Unassigned"
        if lu not in breakdown:
            breakdown[lu] = {"plot_count": 0, "total_area_sqm": 0.0, "total_gfa_sqm": 0.0, "pct_area": 0.0}
        breakdown[lu]["plot_count"] += 1
        breakdown[lu]["total_area_sqm"] += p.area_sqm
        breakdown[lu]["total_gfa_sqm"] += p.achieved_gfa

    for lu, data in breakdown.items():
        data["pct_area"] = round((data["total_area_sqm"] / total_area * 100), 1) if total_area > 0 else 0.0
        data["total_area_sqm"] = round(data["total_area_sqm"], 1)
        data["total_gfa_sqm"] = round(data["total_gfa_sqm"], 1)

    return MasterplanProject(
        project_id=project_id,
        name=project_id,
        total_area_sqm=round(total_area, 1),
        total_plots=len(plots),
        total_gfa_sqm=round(total_gfa, 1),
        average_far=round(avg_far, 2),
        compliant_plots=compliant,
        warning_plots=warning,
        violation_plots=violation,
        land_use_breakdown=breakdown
    )


def log_audit(project_id: str, action_type: str, description: str, plot_id: Optional[str] = None,
              previous_state: Optional[Dict[str, Any]] = None, new_state: Optional[Dict[str, Any]] = None,
              author: str = "Design Review Meeting") -> AuditLogEntry:
    init_db()
    conn = get_connection()
    entry_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        with conn:
            conn.execute("""
                INSERT INTO mp_audit_log (id, project_id, timestamp, action_type, plot_id, description, previous_state_json, new_state_json, author)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry_id, project_id, now_iso, action_type, plot_id, description,
                json.dumps(previous_state) if previous_state else None,
                json.dumps(new_state) if new_state else None,
                author
            ))
        return AuditLogEntry(
            id=entry_id, project_id=project_id, timestamp=now_iso, action_type=action_type,
            plot_id=plot_id, description=description, previous_state=previous_state,
            new_state=new_state, author=author
        )
    finally:
        conn.close()


def get_audit_log(project_id: str, limit: int = 50) -> List[AuditLogEntry]:
    init_db()
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM mp_audit_log WHERE project_id = ? ORDER BY timestamp DESC LIMIT ?",
            (project_id, limit)
        )
        rows = cursor.fetchall()
        entries = []
        for r in rows:
            prev = json.loads(r["previous_state_json"]) if r["previous_state_json"] else None
            nxt = json.loads(r["new_state_json"]) if r["new_state_json"] else None
            entries.append(AuditLogEntry(
                id=r["id"], project_id=r["project_id"], timestamp=r["timestamp"],
                action_type=r["action_type"], plot_id=r["plot_id"], description=r["description"],
                previous_state=prev, new_state=nxt, author=r["author"]
            ))
        return entries
    finally:
        conn.close()


def undo_last_audit(project_id: str) -> Optional[Dict[str, Any]]:
    """Reverts the last action performed during review meeting."""
    init_db()
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM mp_audit_log WHERE project_id = ? AND previous_state_json IS NOT NULL ORDER BY timestamp DESC LIMIT 1",
            (project_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None

        entry_id = row["id"]
        plot_id = row["plot_id"]
        prev_data = json.loads(row["previous_state_json"])

        if plot_id and prev_data:
            # Revert plot to previous state
            plot = MasterplanPlot(**prev_data)
            save_plot(project_id, plot, author="Undo Action")
            # Delete the audit log entry so we don't repeat undo
            with conn:
                conn.execute("DELETE FROM mp_audit_log WHERE id = ?", (entry_id,))
            return {"status": "success", "message": f"Successfully reverted action: {row['description']}", "plot_id": plot_id}

        return None
    finally:
        conn.close()


def seed_default_masterplan(project_id: str = "C3085 - 3EH -Expo Hills"):
    """
    Seeds a rich, realistic urban masterplan for Expo Hills with 24 parcels,
    realistic street grid, park corridors, zoning standards, and sample audit flags.
    """
    init_db()
    conn = get_connection()
    try:
        with conn:
            conn.execute("DELETE FROM mp_plots WHERE project_id = ?", (project_id,))
    finally:
        conn.close()
    plots_data = []

    # Masterplan Grid Layout Definition (Centroid coords: X: 100 to 900, Y: 100 to 600)
    # Sector 1: Residential & Local Parks (North-West)
    # Sector 2: Commercial Boulevard & Mixed Use (Center-East)
    # Sector 3: Civic, Education & Infrastructure (South)

    specs = [
        # Sector 1 - Residential Haven
        ("P-101", "Sector 1 - North Ridge", "Residential", 2400.0, 4800.0, 4560.0, 1.9, 2.0, "G+4", 45.0, 6.0, 4.5, 3.0, 18, 20, "compliant", [], [100, 400, 220, 520]),
        ("P-102", "Sector 1 - North Ridge", "Residential", 2600.0, 5200.0, 5000.0, 1.92, 2.0, "G+4", 45.0, 6.0, 4.5, 3.0, 20, 22, "compliant", [], [240, 400, 360, 520]),
        ("P-103", "Sector 1 - North Ridge", "Residential", 2200.0, 4400.0, 4100.0, 1.86, 2.0, "G+4", 45.0, 6.0, 4.5, 3.0, 16, 18, "compliant", [], [380, 400, 500, 520]),
        ("P-104", "Sector 1 - Central Green", "Open Space / Park", 5800.0, 0.0, 0.0, 0.0, 0.05, "G+0", 5.0, 10.0, 10.0, 10.0, 4, 6, "compliant", [], [100, 260, 360, 380]),
        ("P-105", "Sector 1 - Park View", "Residential", 3100.0, 6200.0, 7440.0, 2.4, 2.0, "G+6", 55.0, 6.0, 4.5, 3.0, 24, 20, "violation", ["FAR 2.40 exceeds maximum permitted FAR 2.0", "Parking deficit: 20 provided vs 24 required"], [380, 260, 500, 380]),
        ("P-106", "Sector 1 - Boulevard", "Residential", 2800.0, 5600.0, 5500.0, 1.96, 2.0, "G+5", 48.0, 6.0, 4.5, 3.0, 22, 24, "compliant", [], [100, 120, 220, 240]),
        ("P-107", "Sector 1 - Boulevard", "Residential", 2800.0, 5600.0, 5600.0, 2.0, 2.0, "G+5", 50.0, 6.0, 4.5, 3.0, 22, 22, "compliant", [], [240, 120, 360, 240]),
        ("P-108", "Sector 1 - Boulevard", "Mixed Use", 3400.0, 8500.0, 8160.0, 2.4, 2.5, "G+7", 52.0, 5.0, 4.0, 3.0, 32, 35, "compliant", [], [380, 120, 500, 240]),

        # Sector 2 - Commercial Boulevard & Central District
        ("P-201", "Sector 2 - Expo Boulevard", "Commercial", 4200.0, 12600.0, 12180.0, 2.9, 3.0, "G+10", 55.0, 5.0, 5.0, 4.0, 60, 64, "compliant", [], [530, 400, 670, 520]),
        ("P-202", "Sector 2 - Expo Boulevard", "Commercial", 4500.0, 13500.0, 13050.0, 2.9, 3.0, "G+12", 55.0, 5.0, 5.0, 4.0, 65, 70, "compliant", [], [690, 400, 830, 520]),
        ("P-203", "Sector 2 - Expo Boulevard", "Commercial", 3800.0, 11400.0, 12540.0, 3.3, 3.0, "G+10", 62.0, 3.5, 4.0, 3.0, 55, 48, "violation", ["FAR 3.30 exceeds maximum permitted FAR 3.0", "Front setback 3.5m encroaches within required 5.0m buffer"], [530, 260, 670, 380]),
        ("P-204", "Sector 2 - Central Square", "Mixed Use", 5100.0, 15300.0, 14790.0, 2.9, 3.0, "G+10", 50.0, 6.0, 5.0, 4.0, 72, 75, "compliant", [], [690, 260, 830, 380]),
        ("P-205", "Sector 2 - Plaza East", "Mixed Use", 4000.0, 10000.0, 9600.0, 2.4, 2.5, "G+8", 48.0, 5.0, 4.0, 3.0, 40, 42, "compliant", [], [530, 120, 670, 240]),
        ("P-206", "Sector 2 - Plaza East", "Commercial", 4400.0, 13200.0, 12760.0, 2.9, 3.0, "G+10", 55.0, 5.0, 4.5, 4.0, 62, 60, "warning", ["Parking ratio tight: 60 provided vs 62 required (2 bay deficit)"], [690, 120, 830, 240]),
        ("P-207", "Sector 2 - Metro Plaza", "Civic", 6200.0, 6200.0, 4960.0, 0.8, 1.2, "G+3", 35.0, 8.0, 6.0, 5.0, 50, 55, "compliant", [], [850, 260, 970, 460]),

        # Sector 3 - Civic, Education, Infrastructure & Green Promenade
        ("P-301", "Sector 3 - Community Hub", "Civic", 7500.0, 11250.0, 9750.0, 1.3, 1.5, "G+3", 40.0, 8.0, 6.0, 5.0, 80, 85, "compliant", [], [100, 10, 260, 100]),
        ("P-302", "Sector 3 - Healthcare Center", "Civic", 5400.0, 10800.0, 9720.0, 1.8, 2.0, "G+4", 45.0, 6.0, 5.0, 4.0, 65, 70, "compliant", [], [280, 10, 440, 100]),
        ("P-303", "Sector 3 - Linear Park", "Open Space / Park", 12400.0, 0.0, 0.0, 0.0, 0.02, "G+0", 2.0, 10.0, 10.0, 10.0, 10, 12, "compliant", [], [460, 10, 720, 100]),
        ("P-304", "Sector 3 - Substation & Infra", "Utilities", 3600.0, 1800.0, 1440.0, 0.4, 0.5, "G+1", 30.0, 6.0, 6.0, 6.0, 12, 15, "compliant", [], [740, 10, 860, 100]),
        ("P-305", "Sector 3 - District Cooling", "Utilities", 3200.0, 3200.0, 2560.0, 0.8, 1.0, "G+2", 40.0, 6.0, 6.0, 5.0, 15, 18, "compliant", [], [880, 10, 970, 100]),
    ]

    for (pid, sec, lu, area, max_gfa, ach_gfa, far, m_far, h, cov, fs, rs, ss, prq, prv, st, viols, bbox) in specs:
        min_x, min_y, max_x, max_y = bbox
        coords = [
            [min_x, min_y],
            [max_x, min_y],
            [max_x, max_y],
            [min_x, max_y],
            [min_x, min_y]
        ]
        # Inner setback envelope calculation
        sb_coords = [
            [min_x + ss, min_y + fs],
            [max_x - ss, min_y + fs],
            [max_x - ss, max_y - rs],
            [min_x + ss, max_y - rs],
            [min_x + ss, min_y + fs]
        ]
        centroid = [(min_x + max_x) / 2.0, (min_y + max_y) / 2.0]

        geom = PlotGeometry(
            coordinates=coords,
            centroid=centroid,
            bbox=[float(min_x), float(min_y), float(max_x), float(max_y)],
            setback_envelope=sb_coords
        )

        plots_data.append(MasterplanPlot(
            plot_id=pid,
            project_id=project_id,
            sector=sec,
            land_use=lu,
            area_sqm=area,
            permitted_gfa=max_gfa,
            achieved_gfa=ach_gfa,
            far=far,
            max_far=m_far,
            max_height=h,
            max_coverage_pct=cov,
            front_setback_m=fs,
            rear_setback_m=rs,
            side_setback_m=ss,
            parking_required=prq,
            parking_provided=prv,
            status=st,
            violations=viols,
            geometry=geom,
            notes=f"Expo Hills Masterplan {sec} - {lu} Parcel"
        ))

    save_plots_bulk(project_id, plots_data, author="System Initialization")
    logger.info(f"Seeded default masterplan for {project_id} with {len(plots_data)} plots.")


def save_file_record(
    project_id: str,
    filename: str,
    file_type: str,
    file_size: int,
    file_path: str,
    plots_count: int = 0,
    meta: Optional[Dict[str, Any]] = None,
    status: str = "uploaded"
) -> Dict[str, Any]:
    init_db()
    now = datetime.now(timezone.utc).isoformat()
    meta_json = json.dumps(meta or {})
    conn = get_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM mp_files WHERE project_id = ? AND filename = ?", (project_id, filename))
            existing = cur.fetchone()
            if existing:
                file_id = existing["id"]
                conn.execute("""
                    UPDATE mp_files
                    SET file_type = ?, file_size = ?, file_path = ?, status = ?, plots_count = ?, meta_json = ?, uploaded_at = ?
                    WHERE id = ?
                """, (file_type, file_size, file_path, status, plots_count, meta_json, now, file_id))
            else:
                file_id = str(uuid.uuid4())
                conn.execute("""
                    INSERT INTO mp_files (id, project_id, filename, file_type, file_size, file_path, status, plots_count, meta_json, uploaded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (file_id, project_id, filename, file_type, file_size, file_path, status, plots_count, meta_json, now))
    finally:
        conn.close()
    return {
        "id": file_id,
        "project_id": project_id,
        "filename": filename,
        "file_type": file_type,
        "file_size": file_size,
        "file_path": file_path,
        "status": status,
        "plots_count": plots_count,
        "meta": meta or {},
        "uploaded_at": now
    }


def delete_file_record(project_id: str, file_id_or_name: str) -> bool:
    init_db()
    conn = get_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT file_path, filename FROM mp_files WHERE project_id = ? AND (id = ? OR filename = ?)", (project_id, file_id_or_name, file_id_or_name))
            row = cur.fetchone()
            if row:
                f_path = row["file_path"]
                f_name = row["filename"]
                conn.execute("DELETE FROM mp_files WHERE project_id = ? AND (id = ? OR filename = ?)", (project_id, file_id_or_name, file_id_or_name))
                conn.execute("DELETE FROM mp_file_relations WHERE project_id = ? AND (cad_file = ? OR excel_file = ?)", (project_id, f_name, f_name))
                if f_path and os.path.exists(f_path):
                    try:
                        os.remove(f_path)
                    except Exception:
                        pass
                return True
            return False
    finally:
        conn.close()


def get_file_records(project_id: str) -> List[Dict[str, Any]]:
    init_db()
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM mp_files WHERE project_id = ? ORDER BY uploaded_at DESC", (project_id,))
        rows = cur.fetchall()
        files = []
        for r in rows:
            meta = {}
            if r["meta_json"]:
                try:
                    meta = json.loads(r["meta_json"])
                except Exception:
                    pass
            files.append({
                "id": r["id"],
                "project_id": r["project_id"],
                "filename": r["filename"],
                "file_type": r["file_type"],
                "file_size": r["file_size"],
                "file_path": r["file_path"],
                "status": r["status"],
                "plots_count": r["plots_count"],
                "meta": meta,
                "uploaded_at": r["uploaded_at"]
            })
        return files
    finally:
        conn.close()


def update_file_status(file_id: str, status: str):
    conn = get_connection()
    try:
        with conn:
            conn.execute("UPDATE mp_files SET status = ? WHERE id = ?", (status, file_id))
    finally:
        conn.close()


def save_file_relation(
    project_id: str,
    cad_file: str,
    excel_file: str,
    pdf_file: Optional[str] = None,
    status: str = "stabilized_linked",
    matched_plots: int = 0,
    discrepancies: Optional[List[Dict[str, Any]]] = None,
    resolutions: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    init_db()
    rel_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    disc_json = json.dumps(discrepancies or [])
    res_json = json.dumps(resolutions or {})
    conn = get_connection()
    try:
        with conn:
            conn.execute("""
                INSERT INTO mp_file_relations (id, project_id, cad_file, excel_file, pdf_file, status, matched_plots, discrepancies_json, resolutions_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (rel_id, project_id, cad_file, excel_file, pdf_file or "", status, matched_plots, disc_json, res_json, now, now))
    finally:
        conn.close()
    return {
        "id": rel_id,
        "project_id": project_id,
        "cad_file": cad_file,
        "excel_file": excel_file,
        "status": status,
        "matched_plots": matched_plots,
        "discrepancies": discrepancies or [],
        "resolutions": resolutions or {},
        "updated_at": now
    }


def get_latest_file_relation(project_id: str) -> Optional[Dict[str, Any]]:
    init_db()
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM mp_file_relations WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1", (project_id,))
        row = cur.fetchone()
        if not row:
            return None
        discrepancies = []
        resolutions = {}
        if row["discrepancies_json"]:
            try:
                discrepancies = json.loads(row["discrepancies_json"])
            except Exception:
                pass
        if row["resolutions_json"]:
            try:
                resolutions = json.loads(row["resolutions_json"])
            except Exception:
                pass
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "cad_file": row["cad_file"],
            "excel_file": row["excel_file"],
            "pdf_file": row["pdf_file"],
            "status": row["status"],
            "matched_plots": row["matched_plots"],
            "discrepancies": discrepancies,
            "resolutions": resolutions,
            "updated_at": row["updated_at"]
        }
    finally:
        conn.close()
