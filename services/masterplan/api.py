"""
FastAPI Router for MPD (Masterplan Processing Division).
Connects the Masterplan AI Interface with offline spatial reasoning,
parsers, graphics engine, audit logs, and Qwen 3.5 9B Copilot.
"""
import os
import shutil
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger

from services.masterplan.models import (
    MasterplanPlot, MasterplanProject, AuditLogEntry,
    MasterplanAIQueryRequest, MasterplanAIQueryResponse
)
from services.masterplan import db
from services.masterplan.spatial_engine import SpatialReasoningEngine
from services.masterplan.cad_graphics import MasterplanGraphicsEngine
from services.masterplan.agent import MasterplanAIAgent
from services.masterplan.parsers.dxf_parser import MasterplanDxfParser
from services.masterplan.parsers.excel_parser import MasterplanExcelParser
from services.masterplan.parsers.pdf_parser import MasterplanPdfParser

from services.masterplan.reconciliation import MasterplanReconciliationEngine

mpd_router = APIRouter(prefix="/api/v1/masterplan", tags=["masterplan"])

agent = MasterplanAIAgent()
spatial_engine = SpatialReasoningEngine()
graphics_engine = MasterplanGraphicsEngine()
dxf_parser = MasterplanDxfParser()
excel_parser = MasterplanExcelParser()
pdf_parser = MasterplanPdfParser()
reconciliation_engine = MasterplanReconciliationEngine()


@mpd_router.get("/projects", response_model=List[Dict[str, Any]])
async def list_masterplan_projects():
    """Returns available masterplan projects."""
    summary = db.get_project_summary("C3085 - 3EH -Expo Hills")
    return [{"project_id": summary.project_id, "name": summary.name, "total_plots": summary.total_plots, "total_area_sqm": summary.total_area_sqm}]


@mpd_router.get("/projects/{project_id}", response_model=MasterplanProject)
async def get_project_details(project_id: str):
    """Returns overall project statistics, land use breakdown, and compliance KPIs."""
    return db.get_project_summary(project_id)


@mpd_router.get("/projects/{project_id}/plots", response_model=List[MasterplanPlot])
async def list_plots(
    project_id: str,
    land_use: Optional[str] = Query(None),
    sector: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None)
):
    """Retrieves plot records with optional filtering."""
    return db.get_plots(project_id, land_use=land_use, sector=sector, status=status, search=search)


@mpd_router.get("/projects/{project_id}/plots/{plot_id}", response_model=MasterplanPlot)
async def get_plot(project_id: str, plot_id: str):
    """Retrieves details of a single plot."""
    p = db.get_plot(project_id, plot_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Plot {plot_id} not found")
    return p


@mpd_router.post("/projects/{project_id}/plots/{plot_id}", response_model=MasterplanPlot)
async def update_plot(project_id: str, plot_id: str, plot: MasterplanPlot):
    """Updates plot parameters, recalculates spatial compliance, and logs audit trail."""
    plot.plot_id = plot_id
    plot.project_id = project_id
    # Recalculate compliance
    st, viols = spatial_engine.validate_plot(plot)
    plot.status = st
    plot.violations = viols
    saved = db.save_plot(project_id, plot, author="Design Review Meeting")
    return saved


@mpd_router.post("/projects/{project_id}/audit")
async def run_spatial_audit(project_id: str):
    """Executes full automated spatial and zoning audit."""
    res = spatial_engine.run_project_audit(project_id)
    return res


@mpd_router.post("/projects/{project_id}/ai-query", response_model=MasterplanAIQueryResponse)
async def ai_query(project_id: str, req: MasterplanAIQueryRequest):
    """Interacts with Local Agentic AI Qwen 3.5 9B for intent parsing and masterplan reasoning."""
    req.project_id = project_id
    res = await agent.process_query(req)
    return res


@mpd_router.post("/projects/{project_id}/import-file")
async def import_file(project_id: str, file: UploadFile = File(...)):
    """
    Ingests DWG/DXF, Excel, or PDF masterplan files,
    stores them permanently under the project, records metadata,
    parses plot entities, runs correlation analysis, and updates spatial audit.
    """
    ext = os.path.splitext(file.filename)[1].lower()
    proj_mp_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "projects", project_id, "masterplan"
    )
    os.makedirs(proj_mp_dir, exist_ok=True)
    saved_path = os.path.join(proj_mp_dir, file.filename)

    with open(saved_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_size = os.path.getsize(saved_path)
    parsed_plots: List[MasterplanPlot] = []
    parser_type = ""
    file_type = "cad" if ext in (".dxf", ".dwg") else ("excel" if ext in (".xlsx", ".xls") else "pdf")

    try:
        if ext in (".dxf", ".dwg"):
            parser_type = "DWG / DXF Parser"
            parsed_plots = dxf_parser.parse_dxf(saved_path, project_id)
        elif ext in (".xlsx", ".xls"):
            parser_type = "Excel Parser"
            parsed_plots = excel_parser.parse_excel(saved_path, project_id)
        elif ext == ".pdf":
            parser_type = "PDF Parser"
            parsed_plots = pdf_parser.parse_pdf(saved_path, project_id)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported format: {ext}. Upload .dxf, .xlsx, or .pdf")

        # Save record in database
        db.save_file_record(
            project_id=project_id,
            filename=file.filename,
            file_type=file_type,
            file_size=file_size,
            file_path=saved_path,
            plots_count=len(parsed_plots),
            status="uploaded"
        )

        if not parsed_plots:
            return {"status": "warning", "message": f"No plots extracted from {file.filename}.", "count": 0}

        # Check existing files to see if both CAD and Excel are now present
        all_files = db.get_file_records(project_id)
        cad_files = [f for f in all_files if f["file_type"] == "cad"]
        excel_files = [f for f in all_files if f["file_type"] == "excel"]

        # If it's a CAD geometry file, populate geometry or update DB
        if ext in (".dxf", ".dwg") or not excel_files:
            db.save_plots_bulk(project_id, parsed_plots, author=f"Import ({parser_type})")
            spatial_engine.run_project_audit(project_id)

        return {
            "status": "success",
            "message": f"Successfully imported {file.filename} ({len(parsed_plots)} plots). File registered under MPD.",
            "count": len(parsed_plots),
            "filename": file.filename,
            "file_type": file_type,
            "has_cad_and_excel": bool(cad_files and excel_files),
            "reconciliation": None
        }
    except Exception as exc:
        logger.error(f"Failed to process masterplan file {file.filename}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@mpd_router.get("/projects/{project_id}/files")
async def list_masterplan_files(project_id: str):
    """Retrieves all uploaded masterplan source files and their linkage status."""
    files = db.get_file_records(project_id)
    relation = db.get_latest_file_relation(project_id)
    return {
        "files": files,
        "relation": relation,
        "total_files": len(files)
    }


@mpd_router.delete("/projects/{project_id}/files/{file_id}")
async def delete_masterplan_file(project_id: str, file_id: str):
    """Deletes an uploaded masterplan source file."""
    deleted = db.delete_file_record(project_id, file_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="File not found")
    return {"status": "success", "message": "File deleted successfully"}


@mpd_router.post("/projects/{project_id}/reconcile")
async def reconcile_files(project_id: str):
    """
    Correlates uploaded CAD drawing geometry with Excel development schedules,
    identifying exact parcel matches and discrepancies requiring confirmation.
    """
    all_files = db.get_file_records(project_id)
    cad_files = [f for f in all_files if f["file_type"] == "cad"]
    excel_files = [f for f in all_files if f["file_type"] == "excel"]

    if not cad_files or not excel_files:
        return {
            "status": "warning",
            "message": "Both a CAD drawing (.dxf/.dwg) and an Excel register (.xlsx) are required for cross-reconciliation.",
            "has_cad": bool(cad_files),
            "has_excel": bool(excel_files),
            "total_plots": 0,
            "matched_plots": 0,
            "discrepancies": []
        }

    latest_cad = cad_files[0]
    latest_excel = excel_files[0]
    c_plots = dxf_parser.parse_dxf(latest_cad["file_path"], project_id)
    e_plots = excel_parser.parse_excel(latest_excel["file_path"], project_id)

    res = reconciliation_engine.analyze_correlation(
        cad_plots=c_plots,
        excel_plots=e_plots,
        cad_filename=latest_cad["filename"],
        excel_filename=latest_excel["filename"]
    )
    return res


@mpd_router.post("/projects/{project_id}/stabilize-relation")
async def stabilize_relation(project_id: str, payload: Dict[str, Any]):
    """
    Stabilizes the relation between CAD geometry and Excel development schedules
    based on user-confirmed resolutions, and updates the AI reasoning ground truth.
    """
    resolutions = payload.get("resolutions", {})
    author = payload.get("author", "Design Review Admin")

    all_files = db.get_file_records(project_id)
    cad_files = [f for f in all_files if f["file_type"] == "cad"]
    excel_files = [f for f in all_files if f["file_type"] == "excel"]

    if not cad_files or not excel_files:
        # Fallback: apply resolutions directly to existing masterplan plots in DB
        current_plots = db.get_plots(project_id)
        updated = False
        for p in current_plots:
            if p.plot_id in resolutions:
                choice = resolutions[p.plot_id]
                if choice == "excel" and "excel_area" in payload:
                    p.area_sqm = float(payload["excel_area"])
                    p.far = round(p.achieved_gfa / p.area_sqm, 2)
                    updated = True
                elif choice == "cad":
                    updated = True
        if updated:
            db.save_plots_bulk(project_id, current_plots, author=f"Relation Stabilization ({author})")
            spatial_engine.run_project_audit(project_id)

        existing_rel = db.get_latest_file_relation(project_id) or {}
        combined_res = dict(existing_rel.get("resolutions", {}))
        combined_res.update(resolutions)
        db.save_file_relation(
            project_id=project_id,
            cad_file=cad_files[0]["filename"] if cad_files else "CAD Geometry",
            excel_file=excel_files[0]["filename"] if excel_files else "Excel Schedule",
            status="stabilized_linked",
            matched_plots=len(current_plots),
            resolutions=combined_res
        )

        return {
            "status": "success",
            "message": f"Stabilized relations for {len(current_plots)} plots.",
            "plots_count": len(current_plots)
        }

    latest_cad = cad_files[0]
    latest_excel = excel_files[0]
    c_plots = dxf_parser.parse_dxf(latest_cad["file_path"], project_id)
    e_plots = excel_parser.parse_excel(latest_excel["file_path"], project_id)

    existing_rel = db.get_latest_file_relation(project_id) or {}
    combined_res = dict(existing_rel.get("resolutions", {}))
    combined_res.update(resolutions)

    merged = reconciliation_engine.stabilize_and_merge(
        project_id=project_id,
        cad_plots=c_plots,
        excel_plots=e_plots,
        resolutions=combined_res,
        author=author
    )

    db.save_file_relation(
        project_id=project_id,
        cad_file=latest_cad["filename"],
        excel_file=latest_excel["filename"],
        status="stabilized_linked",
        matched_plots=len(merged),
        resolutions=combined_res
    )

    db.update_file_status(latest_cad["id"], "linked")
    db.update_file_status(latest_excel["id"], "linked")

    return {
        "status": "success",
        "message": f"Successfully stabilized and linked {len(merged)} plots between '{latest_cad['filename']}' and '{latest_excel['filename']}'!",
        "plots_count": len(merged)
    }


@mpd_router.get("/projects/{project_id}/export-cad")
async def export_cad(project_id: str, highlights: Optional[str] = Query(None)):
    """Generates and serves a highlighted CAD copy (DXF)."""
    hl_list = [h.strip().upper() for h in highlights.split(",") if h.strip()] if highlights else None
    dxf_path = graphics_engine.generate_highlighted_dxf(project_id, hl_list)
    return FileResponse(
        dxf_path,
        media_type="application/dxf",
        filename=os.path.basename(dxf_path)
    )


@mpd_router.get("/projects/{project_id}/audit-log", response_model=List[AuditLogEntry])
async def get_audit_log(project_id: str, limit: int = Query(50)):
    """Retrieves design review audit log."""
    return db.get_audit_log(project_id, limit=limit)


@mpd_router.post("/projects/{project_id}/undo")
async def undo_action(project_id: str):
    """Reverts the last action performed in the review meeting."""
    res = db.undo_last_audit(project_id)
    if not res:
        raise HTTPException(status_code=400, detail="No prior state found to undo")
    return res


@mpd_router.post("/projects/{project_id}/reset-sample")
async def reset_sample(project_id: str):
    """Resets the project back to the reference Expo Hills masterplan."""
    db.seed_default_masterplan(project_id)
    spatial_engine.run_project_audit(project_id)
    return {"status": "success", "message": f"Reset {project_id} to reference masterplan"}
