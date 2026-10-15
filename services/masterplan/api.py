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

mpd_router = APIRouter(prefix="/api/v1/masterplan", tags=["masterplan"])

agent = MasterplanAIAgent()
spatial_engine = SpatialReasoningEngine()
graphics_engine = MasterplanGraphicsEngine()
dxf_parser = MasterplanDxfParser()
excel_parser = MasterplanExcelParser()
pdf_parser = MasterplanPdfParser()


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
    parses plot entities, updates the database, and performs spatial audit.
    """
    ext = os.path.splitext(file.filename)[1].lower()
    temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "tmp")
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, file.filename)

    with open(temp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    parsed_plots: List[MasterplanPlot] = []
    parser_type = ""

    try:
        if ext in (".dxf", ".dwg"):
            parser_type = "DWG / DXF Parser"
            parsed_plots = dxf_parser.parse_dxf(temp_path, project_id)
        elif ext in (".xlsx", ".xls"):
            parser_type = "Excel Parser"
            parsed_plots = excel_parser.parse_excel(temp_path, project_id)
        elif ext == ".pdf":
            parser_type = "PDF Parser"
            parsed_plots = pdf_parser.parse_pdf(temp_path, project_id)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported format: {ext}. Upload .dxf, .xlsx, or .pdf")

        if not parsed_plots:
            return {"status": "warning", "message": f"No plots extracted from {file.filename}.", "count": 0}

        db.save_plots_bulk(project_id, parsed_plots, author=f"Import ({parser_type})")
        # Run spatial audit on freshly imported plots
        spatial_engine.run_project_audit(project_id)

        return {
            "status": "success",
            "message": f"Successfully imported {len(parsed_plots)} plots via {parser_type} from {file.filename}",
            "count": len(parsed_plots)
        }
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


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
