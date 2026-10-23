"""
FastAPI Router for MPD (Masterplan Processing Division).
Connects the Masterplan AI Interface with offline spatial reasoning,
parsers, graphics engine, audit logs, and Qwen 3.5 9B Copilot.
"""
import os
import shutil
import json
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger

import auth
from config import get_settings
from services.ingestion import contained_upload_path, save_upload_capped, UploadTooLargeError

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


def _revision_root():
    from config import get_settings
    return os.path.join(get_settings().data_dir, 'cad_revisions')


@mpd_router.post('/projects/{project_id}/cad-revisions')
async def edit_cad_revision(project_id: str, request: Request, payload: Dict[str, Any]):
    import auth
    from starlette.concurrency import run_in_threadpool
    from services.masterplan.cad_revisions import create_revision, read_revision, digest
    user=auth.require_project(request,project_id)
    auth.require_roles(request,'admin','lead','user')
    files=[f for f in db.get_file_records(project_id) if f['file_type']=='cad']
    source_id=payload.get('source_id')
    if source_id: files=[f for f in files if f['id']==source_id]
    if not files: raise HTTPException(404,'Selected CAD source not found')
    source=files[0]['file_path']
    expected=os.path.realpath(os.path.join(get_settings().data_dir,'projects',project_id,'masterplan'))
    from pathlib import Path
    if not Path(source).resolve().is_relative_to(Path(expected).resolve()):
        raise HTTPException(400,'Source is outside its project drawing folder')
    ids=payload.get('plot_ids')
    if payload.get('land_use'):
        ids=[p.plot_id for p in db.get_plots(project_id,land_use=payload['land_use'])]
    elif payload.get('filter_field'):
        field = payload['filter_field']
        op = payload.get('operator', '<')
        val = float(payload.get('value', 0))
        all_p = db.get_plots(project_id)
        import operator
        compare = {'<':operator.lt, '>':operator.gt, '<=':operator.le, '>=':operator.ge, '==':operator.eq}.get(op)
        attribute = {'gfa':'achieved_gfa', 'area':'area_sqm', 'far':'far'}.get(field)
        if compare is None or attribute is None:
            raise HTTPException(400,'Unsupported plot filter')
        ids = [p.plot_id for p in all_p if compare(getattr(p, attribute), val)]
    if not isinstance(ids,list) or not ids or len(ids)>1000 or any(not isinstance(p,str) for p in ids):
        raise HTTPException(400,'Specify 1–1000 matched plot IDs')
    import cad
    base_working=None
    previous=None
    if payload.get('base_revision'):
        try:
            base_folder,previous=read_revision(_revision_root(),project_id,payload['base_revision'])
            if previous['original_sha256']!=digest(source):
                raise ValueError('Source revision changed; start from original')
            base_working=base_folder/previous['working']
        except (ValueError,OSError) as exc:
            raise HTTPException(400,str(exc)) from exc
    def save(doc,path):
        if path.lower().endswith('.dwg'):
            from ezdxf.addons import odafc
            odafc.export_dwg(doc,path,replace=False)
        else: doc.saveas(path)
    try:
        manifest=await run_in_threadpool(create_revision,_revision_root(),project_id,source,ids,payload.get('color'),user['id'],cad.load_doc,save,base_working)
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(400,str(exc)) from exc
    return manifest


@mpd_router.get('/projects/{project_id}/cad-revisions/{revision}/{artifact}')
async def download_cad_revision(project_id: str, revision: str, artifact: str, request: Request):
    import auth
    from services.masterplan.cad_revisions import read_revision
    auth.require_project(request,project_id)
    if artifact not in ('working','original'): raise HTTPException(400,'Invalid artifact')
    if artifact=='original': auth.require_roles(request,'admin')
    try:
        folder,manifest=read_revision(_revision_root(),project_id,revision)
    except (ValueError,OSError) as exc:
        raise HTTPException(404,str(exc)) from exc
    return FileResponse(folder/manifest[artifact],filename=revision[:8]+'_'+artifact+manifest['format'])


@mpd_router.get('/projects/{project_id}/cad-revisions')
async def list_cad_revisions(project_id: str, request: Request):
    import auth
    from services.masterplan.cad_revisions import revision_folder, read_revision
    auth.require_project(request,project_id)
    root=revision_folder(_revision_root(),project_id,'0'*32).parent
    results=[]
    if root.exists():
        for folder in root.iterdir():
            try:
                _,manifest=read_revision(_revision_root(),project_id,folder.name)
                results.append({key:manifest.get(key) for key in ('revision','created_at','source_name','color','plot_ids','format')})
            except (ValueError,OSError):
                continue
    return {'revisions':sorted(results,key=lambda r:r['created_at'] or '',reverse=True)}


@mpd_router.get("/projects", response_model=List[Dict[str, Any]])
async def list_masterplan_projects(request: Request):
    """Returns available masterplan projects that the authenticated user is permitted to access."""
    user = auth.require_user(request)
    registered = db.list_projects()
    authorized = []
    for item in registered:
        pid = item.get("project_id")
        if pid and auth.user_has_project(user, pid):
            try:
                summary = db.get_project_summary(pid)
                authorized.append({
                    "project_id": summary.project_id,
                    "name": summary.name,
                    "total_plots": summary.total_plots,
                    "total_area_sqm": summary.total_area_sqm
                })
            except Exception:
                continue
    if user.get("role") != "admin" and not authorized:
        raise HTTPException(403, "You do not have access to any masterplan projects")
    return authorized


@mpd_router.get("/projects/{project_id}", response_model=MasterplanProject)
async def get_project_details(project_id: str, request: Request = None):
    """Returns overall project statistics, land use breakdown, and compliance KPIs."""
    if request is not None:
        auth.require_project(request, project_id)
    return db.get_project_summary(project_id)


@mpd_router.get("/projects/{project_id}/plots", response_model=List[MasterplanPlot])
async def list_plots(
    project_id: str,
    request: Request = None,
    land_use: Optional[str] = Query(None),
    sector: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None)
):
    """Retrieves plot records with optional filtering."""
    if request is not None:
        auth.require_project(request, project_id)
    return db.get_plots(project_id, land_use=land_use, sector=sector, status=status, search=search)


@mpd_router.get("/projects/{project_id}/plots/{plot_id}", response_model=MasterplanPlot)
async def get_plot(project_id: str, plot_id: str, request: Request = None):
    """Retrieves details of a single plot."""
    if request is not None:
        auth.require_project(request, project_id)
    p = db.get_plot(project_id, plot_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Plot {plot_id} not found")
    return p


@mpd_router.post("/projects/{project_id}/plots/{plot_id}", response_model=MasterplanPlot)
async def update_plot(project_id: str, plot_id: str, plot: MasterplanPlot, request: Request = None):
    """Updates plot parameters, recalculates spatial compliance, and logs audit trail."""
    if request is not None:
        auth.require_project(request, project_id)
        auth.require_roles(request, "admin", "lead")
    plot.plot_id = plot_id
    plot.project_id = project_id
    # Recalculate compliance
    st, viols = spatial_engine.validate_plot(plot)
    plot.status = st
    plot.violations = viols
    saved = db.save_plot(project_id, plot, author="Design Review Meeting")
    return saved


@mpd_router.post("/projects/{project_id}/audit")
async def run_spatial_audit(project_id: str, request: Request = None):
    """Executes full automated spatial and zoning audit."""
    if request is not None:
        auth.require_project(request, project_id)
    res = spatial_engine.run_project_audit(project_id)
    return res


@mpd_router.post("/projects/{project_id}/ai-query", response_model=MasterplanAIQueryResponse)
async def ai_query(project_id: str, req: MasterplanAIQueryRequest, request: Request = None):
    """Interacts with Local Agentic AI Qwen 3.5 9B for intent parsing and masterplan reasoning."""
    if request is not None:
        auth.require_project(request, project_id)
    req.project_id = project_id
    res = await agent.process_query(req)
    return res


@mpd_router.post("/projects/{project_id}/import-file")
async def import_file(project_id: str, file: UploadFile = File(...), request: Request = None):
    """
    Ingests DWG/DXF, Excel, or PDF masterplan files,
    stores them permanently under the project, records metadata,
    parses plot entities, runs correlation analysis, and updates spatial audit.
    """
    if request is not None:
        auth.require_project(request, project_id)
        auth.require_roles(request, "admin", "lead")

    clean_filename = os.path.basename(file.filename or "")
    if not clean_filename:
        raise HTTPException(status_code=400, detail="Filename required")

    ext = os.path.splitext(clean_filename)[1].lower()
    if ext not in (".dxf", ".dwg", ".xlsx", ".xls", ".pdf"):
        raise HTTPException(status_code=400, detail=f"Unsupported format: {ext}. Upload .dxf, .xlsx, or .pdf")

    data_root = get_settings().data_dir
    projects_root = os.path.join(data_root, "projects")
    try:
        saved_path = contained_upload_path(projects_root, project_id, "masterplan", clean_filename)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))

    os.makedirs(os.path.dirname(saved_path), exist_ok=True)
    max_bytes = get_settings().max_upload_size_mb * 1024 * 1024
    try:
        file_size = save_upload_capped(file.file, saved_path, max_bytes)
    except UploadTooLargeError as e:
        raise HTTPException(status_code=413, detail=str(e))

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

        # Save record in database
        db.save_file_record(
            project_id=project_id,
            filename=clean_filename,
            file_type=file_type,
            file_size=file_size,
            file_path=saved_path,
            plots_count=len(parsed_plots),
            status="uploaded"
        )

        if not parsed_plots:
            return {"status": "warning", "message": f"No plots extracted from {clean_filename}.", "count": 0}

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
            "message": f"Successfully imported {clean_filename} ({len(parsed_plots)} plots). File registered under MPD.",
            "count": len(parsed_plots),
            "filename": clean_filename,
            "file_type": file_type,
            "has_cad_and_excel": bool(cad_files and excel_files),
            "reconciliation": None
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to process masterplan file {clean_filename}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@mpd_router.get("/projects/{project_id}/files")
async def list_masterplan_files(project_id: str, request: Request = None):
    """Retrieves all uploaded masterplan source files and their linkage status."""
    if request is not None:
        auth.require_project(request, project_id)
    files = db.get_file_records(project_id)
    relation = db.get_latest_file_relation(project_id)
    return {
        "files": files,
        "relation": relation,
        "total_files": len(files)
    }


@mpd_router.delete("/projects/{project_id}/files/{file_id}")
async def delete_masterplan_file(project_id: str, file_id: str, request: Request = None):
    """Deletes an uploaded masterplan source file."""
    if request is not None:
        auth.require_project(request, project_id)
        auth.require_roles(request, "admin", "lead")
    deleted = db.delete_file_record(project_id, file_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="File not found")
    for key in list(_CAD_DRAWING_CACHE):
        if key[0] == project_id:
            _CAD_DRAWING_CACHE.pop(key, None)
    return {"status": "success", "message": "File deleted successfully"}


_CAD_DRAWING_CACHE = {}

@mpd_router.get("/projects/{project_id}/cad-drawing")
async def get_project_cad_drawing(project_id: str, request: Request = None, file_id: Optional[str] = Query(None)):
    """
    Returns full CAD vector drawing linework (lines, polylines, arcs, circles, texts, layers)
    for rendering the full architectural CAD background in the MPD canvas.
    """
    if request is not None:
        auth.require_project(request, project_id)
    all_files = db.get_file_records(project_id)
    cad_files = [f for f in all_files if f.get("file_type") == "cad"]
    if not cad_files:
        return {"has_cad": False, "entities": [], "layers": [], "extents": None}

    if file_id:
        cad_files = [f for f in cad_files if f['id'] == file_id]
        if not cad_files:
            raise HTTPException(404, 'CAD source not found in this project')
    latest = cad_files[0]
    cad_path = latest.get("file_path")
    if not cad_path or not os.path.exists(cad_path):
        return {"has_cad": False, "entities": [], "layers": [], "extents": None}

    mtime = os.path.getmtime(cad_path)
    cache_key = (project_id, cad_path, mtime)
    if cache_key in _CAD_DRAWING_CACHE:
        return _CAD_DRAWING_CACHE[cache_key]

    cache_path = f"{cad_path}.scaled_cache.json"
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100 and os.path.getmtime(cache_path) >= mtime:
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                _CAD_DRAWING_CACHE[cache_key] = data
                return data
        except Exception:
            pass

    try:
        from services.cad_service import CadService
        import cad
        doc = cad.load_doc(cad_path)
        res = CadService.parse_dxf_stream(doc)

        entities = res.get("entities", [])
        layers = res.get("layers", [])
        extents = res.get("extents", {})

        # Compute coordinate scale: mm vs meters
        w_raw = extents.get("width") or (extents.get("max_x", 0) - extents.get("min_x", 0))
        h_raw = extents.get("height") or (extents.get("max_y", 0) - extents.get("min_y", 0))
        min_x_raw = extents.get("min_x", 0)
        min_y_raw = extents.get("min_y", 0)

        # Check if coordinates are in GIS / UTM survey units (e.g. Dubai Grid > 10,000m)
        is_utm = (min_x_raw > 10000 or min_y_raw > 10000) and (w_raw < 100000 and h_raw < 100000)
        if is_utm:
            scale = 1.0
        elif w_raw > 20000 or h_raw > 20000:
            scale = 0.001
        else:
            scale = 1.0

        scaled_entities = []
        for e in entities:
            t = e.get("type")
            if t == "LINE":
                scaled_entities.append({
                    "type": "LINE",
                    "layer": e.get("layer"),
                    "color": e.get("color", "#ffffff"),
                    "x1": round(e["x1"] * scale, 3),
                    "y1": round(e["y1"] * scale, 3),
                    "x2": round(e["x2"] * scale, 3),
                    "y2": round(e["y2"] * scale, 3)
                })
            elif t == "POLYLINE":
                pts = [[round(p[0] * scale, 3), round(p[1] * scale, 3)] for p in e.get("points", [])]
                scaled_entities.append({
                    "type": "POLYLINE",
                    "layer": e.get("layer"),
                    "color": e.get("color", "#ffffff"),
                    "points": pts,
                    "closed": e.get("closed", False)
                })
            elif t == "ARC":
                scaled_entities.append({
                    "type": "ARC",
                    "layer": e.get("layer"),
                    "color": e.get("color", "#ffffff"),
                    "cx": round(e["cx"] * scale, 3),
                    "cy": round(e["cy"] * scale, 3),
                    "radius": round(e["radius"] * scale, 3),
                    "start_angle": e.get("start_angle", 0),
                    "end_angle": e.get("end_angle", 360)
                })
            elif t == "CIRCLE":
                scaled_entities.append({
                    "type": "CIRCLE",
                    "layer": e.get("layer"),
                    "color": e.get("color", "#ffffff"),
                    "cx": round(e["cx"] * scale, 3),
                    "cy": round(e["cy"] * scale, 3),
                    "radius": round(e["radius"] * scale, 3)
                })
            elif t == "TEXT":
                raw_h = e.get("height") or 2.5
                scaled_entities.append({
                    "type": "TEXT",
                    "layer": e.get("layer"),
                    "color": e.get("color", "#ffffff"),
                    "x": round(e["x"] * scale, 3),
                    "y": round(e["y"] * scale, 3),
                    "text": e.get("text", ""),
                    "height": round(raw_h * scale, 2)
                })

        # Calculate tight real bounding box across all scaled entities
        xs, ys = [], []
        for e in scaled_entities:
            t = e.get("type")
            if t == "LINE":
                xs.extend([e["x1"], e["x2"]])
                ys.extend([e["y1"], e["y2"]])
            elif t == "POLYLINE":
                for p in e.get("points", []):
                    xs.append(p[0])
                    ys.append(p[1])
            elif t in ("ARC", "CIRCLE"):
                r = e.get("radius", 0)
                xs.extend([e["cx"] - r, e["cx"] + r])
                ys.extend([e["cy"] - r, e["cy"] + r])
            elif t == "TEXT":
                xs.append(e["x"])
                ys.append(e["y"])

        if xs and ys:
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            scaled_extents = {
                "min_x": round(min_x, 3),
                "min_y": round(min_y, 3),
                "max_x": round(max_x, 3),
                "max_y": round(max_y, 3),
                "width": round(max_x - min_x, 3),
                "height": round(max_y - min_y, 3)
            }
        else:
            scaled_extents = {
                "min_x": round(extents.get("min_x", 0) * scale, 3),
                "min_y": round(extents.get("min_y", 0) * scale, 3),
                "max_x": round(extents.get("max_x", 0) * scale, 3),
                "max_y": round(extents.get("max_y", 0) * scale, 3),
                "width": round((extents.get("max_x", 0) - extents.get("min_x", 0)) * scale, 3),
                "height": round((extents.get("max_y", 0) - extents.get("min_y", 0)) * scale, 3)
            }

        result = {
            "has_cad": True,
            "filename": latest.get("filename"),
            "total_entities": len(scaled_entities),
            "extents": scaled_extents,
            "layers": layers,
            "entities": scaled_entities
        }
        try:
            tmp_path = f"{cache_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(result, f)
            os.replace(tmp_path, cache_path)
        except Exception:
            pass
        _CAD_DRAWING_CACHE[cache_key] = result
        return result
    except Exception as exc:
        logger.error(f"Failed to extract CAD vector drawing for {project_id}: {exc}")
        return {"has_cad": False, "error": str(exc), "entities": [], "layers": []}


@mpd_router.post("/projects/{project_id}/reconcile")
async def reconcile_files(project_id: str, request: Request = None):
    """
    Correlates uploaded CAD drawing geometry with Excel development schedules,
    identifying exact parcel matches and discrepancies requiring confirmation.
    """
    if request is not None:
        auth.require_project(request, project_id)
        auth.require_roles(request, "admin", "lead")
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
async def stabilize_relation(project_id: str, payload: Dict[str, Any], request: Request = None):
    """
    Stabilizes the relation between CAD geometry and Excel development schedules
    based on user-confirmed resolutions, and updates the AI reasoning ground truth.
    """
    if request is not None:
        auth.require_project(request, project_id)
        auth.require_roles(request, "admin", "lead")
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
async def export_cad(project_id: str, request: Request = None, highlights: Optional[str] = Query(None)):
    """Generates and serves a highlighted CAD copy (DXF)."""
    if request is not None:
        auth.require_project(request, project_id)
    hl_list = [h.strip().upper() for h in highlights.split(",") if h.strip()] if highlights else None
    dxf_path = graphics_engine.generate_highlighted_dxf(project_id, hl_list)
    return FileResponse(
        dxf_path,
        media_type="application/dxf",
        filename=os.path.basename(dxf_path)
    )


@mpd_router.get("/projects/{project_id}/export-excel")
async def export_excel(
    project_id: str,
    request: Request = None,
    land_use: Optional[str] = Query(None),
    sector: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    plots: Optional[str] = Query(None),
):
    """Generates and serves a formatted Excel (.xlsx) workbook of masterplan parcels."""
    if request is not None:
        auth.require_project(request, project_id)
    import re as _re
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    records = db.get_plots(project_id, land_use=land_use, sector=sector, status=status)
    if plots:
        hl_set = {h.strip().upper() for h in plots.split(",") if h.strip()}
        if hl_set:
            records = [p for p in records if p.plot_id.upper() in hl_set]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Masterplan Schedule"

    title_font = Font(name="Calibri", size=13, bold=True, color="FFFFFF")
    title_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    sub_font = Font(name="Calibri", size=10, bold=True, color="1E293B")
    sub_fill = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
    hdr_font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    hdr_fill = PatternFill(start_color="1D4ED8", end_color="1D4ED8", fill_type="solid")
    tot_font = Font(name="Calibri", size=10, bold=True, color="0F172A")
    tot_fill = PatternFill(start_color="DBEAFE", end_color="DBEAFE", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1"),
    )

    scope_label = land_use or sector or ("Filtered Selection" if plots else "All Masterplan Parcels")
    total_area = sum(p.area_sqm for p in records)
    total_perm_gfa = sum(p.permitted_gfa for p in records)
    total_ach_gfa = sum(p.achieved_gfa for p in records)
    eff_far = (total_ach_gfa / total_area) if total_area > 0 else 0.0

    ws.merge_cells("A1:P1")
    ws["A1"] = f"{project_id} — Masterplan Development Schedule ({scope_label})"
    ws["A1"].font = title_font
    ws["A1"].fill = title_fill
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 26

    ws.merge_cells("A2:P2")
    ws["A2"] = (
        f"Total Parcels: {len(records)}   |   Total Footprint Area: {total_area:,.1f} m²   |   "
        f"Total Achieved GFA: {total_ach_gfa:,.1f} m²   |   Effective FAR: {eff_far:.2f}"
    )
    ws["A2"].font = sub_font
    ws["A2"].fill = sub_fill
    ws["A2"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[2].height = 20

    headers = [
        "Plot ID", "Sector", "Land Use", "Footprint Area (m²)",
        "Permitted GFA (m²)", "Achieved GFA (m²)", "Achieved FAR", "Max FAR",
        "Max Height", "Coverage (%)", "Front Setback (m)", "Side Setback (m)",
        "Rear Setback (m)", "Parking Req.", "Parking Prov.", "Compliance Status",
    ]
    ws.append([])
    ws.append(headers)
    hdr_row = 4
    ws.row_dimensions[hdr_row].height = 22
    for col_idx in range(1, len(headers) + 1):
        c = ws.cell(row=hdr_row, column=col_idx)
        c.font = hdr_font
        c.fill = hdr_fill
        c.alignment = Alignment(horizontal="center" if col_idx > 3 else "left", vertical="center")
        c.border = thin_border

    for p in records:
        row_vals = [
            p.plot_id,
            p.sector,
            p.land_use,
            round(p.area_sqm, 2),
            round(p.permitted_gfa, 2),
            round(p.achieved_gfa, 2),
            round(p.far, 2),
            round(p.max_far, 2),
            p.max_height,
            round(p.max_coverage_pct, 1),
            round(p.front_setback_m, 2),
            round(p.side_setback_m, 2),
            round(p.rear_setback_m, 2),
            int(p.parking_required or 0),
            int(p.parking_provided or 0),
            (p.status or "compliant").upper(),
        ]
        ws.append(row_vals)
        r_idx = ws.max_row
        for c_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=r_idx, column=c_idx)
            cell.border = thin_border
            if c_idx in (4, 5, 6):
                cell.number_format = "#,##0.00"
            elif c_idx in (7, 8):
                cell.number_format = "0.00"

    # Summary Totals Row
    tot_row_vals = [
        "TOTAL / EFFECTIVE",
        f"{len(records)} Plots",
        scope_label,
        round(total_area, 2),
        round(total_perm_gfa, 2),
        round(total_ach_gfa, 2),
        round(eff_far, 2),
        "",
        "",
        "",
        "",
        "",
        "",
        sum(int(p.parking_required or 0) for p in records),
        sum(int(p.parking_provided or 0) for p in records),
        "100% COMPLIANT" if all(p.status == "compliant" for p in records) else "REVIEW",
    ]
    ws.append(tot_row_vals)
    tot_r = ws.max_row
    ws.row_dimensions[tot_r].height = 22
    for c_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=tot_r, column=c_idx)
        cell.font = tot_font
        cell.fill = tot_fill
        cell.border = thin_border
        if c_idx in (4, 5, 6):
            cell.number_format = "#,##0.00"
        elif c_idx == 7:
            cell.number_format = "0.00"

    col_widths = [14, 18, 20, 18, 18, 18, 13, 12, 13, 13, 16, 16, 16, 14, 14, 18]
    for idx, w in enumerate(col_widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(idx)].width = w

    # Sheet 2: Land Use Summary
    ws2 = wb.create_sheet(title="Land Use Summary")
    ws2.append(["Land Use Category", "Plot Count", "Total Footprint Area (m²)", "% of Area", "Total Achieved GFA (m²)", "Effective FAR"])
    for c_idx in range(1, 7):
        c = ws2.cell(row=1, column=c_idx)
        c.font = hdr_font
        c.fill = hdr_fill
        c.border = thin_border

    lu_groups: Dict[str, List[MasterplanPlot]] = {}
    for p in records:
        lu_groups.setdefault(p.land_use or "Other", []).append(p)
    for lu_name, plist in sorted(lu_groups.items(), key=lambda kv: sum(x.area_sqm for x in kv[1]), reverse=True):
        a_sum = sum(x.area_sqm for x in plist)
        g_sum = sum(x.achieved_gfa for x in plist)
        f_avg = (g_sum / a_sum) if a_sum > 0 else 0.0
        pct = (a_sum / total_area * 100.0) if total_area > 0 else 0.0
        ws2.append([lu_name, len(plist), round(a_sum, 2), round(pct, 2), round(g_sum, 2), round(f_avg, 2)])
        r_i = ws2.max_row
        for c_i in range(1, 7):
            ws2.cell(row=r_i, column=c_i).border = thin_border
    for idx, w in enumerate([24, 14, 24, 14, 24, 15], 1):
        ws2.column_dimensions[openpyxl.utils.get_column_letter(idx)].width = w

    export_dir = os.path.join(get_settings().data_dir, "exports")
    os.makedirs(export_dir, exist_ok=True)
    safe_proj = _re.sub(r"[^A-Za-z0-9_-]+", "_", project_id).strip("_")
    safe_scope = _re.sub(r"[^A-Za-z0-9_-]+", "_", scope_label).strip("_")
    fname = f"{safe_proj}_{safe_scope}_Schedule.xlsx"
    out_path = os.path.join(export_dir, fname)
    wb.save(out_path)

    return FileResponse(
        out_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=fname,
    )


@mpd_router.get("/projects/{project_id}/audit-log", response_model=List[AuditLogEntry])
async def get_audit_log(project_id: str, request: Request = None, limit: int = Query(50)):
    """Retrieves design review audit log."""
    if request is not None:
        auth.require_project(request, project_id)
    return db.get_audit_log(project_id, limit=limit)


@mpd_router.post("/projects/{project_id}/undo")
async def undo_action(project_id: str, request: Request = None):
    """Reverts the last action performed in the review meeting."""
    if request is not None:
        auth.require_project(request, project_id)
        auth.require_roles(request, "admin", "lead")
    res = db.undo_last_audit(project_id)
    if not res:
        raise HTTPException(status_code=400, detail="No prior state found to undo")
    return res


@mpd_router.post("/projects/{project_id}/reset-sample")
async def reset_sample(project_id: str, request: Request = None):
    """Clears all masterplan plots for this project."""
    if request is not None:
        auth.require_project(request, project_id)
        auth.require_roles(request, "admin")
    conn = db.get_connection()
    try:
        with conn:
            conn.execute("DELETE FROM mp_plots WHERE project_id = ?", (project_id,))
    finally:
        conn.close()
    return {"status": "success", "message": f"Cleared plots for {project_id}"}


@mpd_router.post("/projects/{project_id}/resolve-clashes")
async def resolve_clashes(
    project_id: str,
    request: Request = None,
    far_strategy: str = Query("smart_urban", description="smart_urban, harmonize_zoning, or cap_gfa")
):
    """
    Automated Local AI resolution of 90 masterplan clashes:
    - Prunes duplicate CAD polyline layers
    - Carves utility kiosks and substations from host polygons using Shapely seam buffers
    - Clips perimeter slivers with infrastructure priority
    - Harmonizes or caps FAR density violations
    - Re-audits the project and guarantees 100% compliance
    """
    if request is not None:
        auth.require_project(request, project_id)
        auth.require_roles(request, "admin", "lead")
    from services.masterplan.clash_resolver import MasterplanClashResolver
    resolver = MasterplanClashResolver()
    res = resolver.resolve_all_clashes(project_id, far_strategy=far_strategy)
    return res


@mpd_router.get("/projects/{project_id}/snapshots")
async def list_snapshots(project_id: str, request: Request = None):
    """Lists available database snapshots for this project."""
    if request is not None:
        auth.require_project(request, project_id)
    from services.masterplan.clash_resolver import MasterplanClashResolver
    resolver = MasterplanClashResolver()
    return resolver.list_snapshots(project_id)


@mpd_router.post("/projects/{project_id}/snapshots/restore")
async def restore_snapshot(
    project_id: str,
    snapshot_name: str = Query("baseline"),
    request: Request = None
):
    """Restores the masterplan to a named snapshot."""
    if request is not None:
        auth.require_project(request, project_id)
        auth.require_roles(request, "admin", "lead")
    from services.masterplan.clash_resolver import MasterplanClashResolver
    resolver = MasterplanClashResolver()
    ok = resolver.restore_snapshot(project_id, snapshot_name=snapshot_name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Snapshot '{snapshot_name}' not found")
    return {"status": "success", "message": f"Restored project to snapshot '{snapshot_name}'"}

