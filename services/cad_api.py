"""
CAD API router for Expo Design AI & CADCraft integration.
Exposes endpoints to:
- Open and parse DXF/DWG CAD files into JSON model space
- Save edited CAD models back to project DXF files
- Export DXF files for AutoCAD / CADCraft
- Generate raster/vector conditioning images for AI Design Studio
- Serve architectural and structural sample CAD drawings
"""
import io
import json
import hashlib
import math
import os
import re
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

MAX_CAD_ENTITIES = 200_000
MAX_CAD_UPLOAD_MB = 200


def _safe_name(name: str, default: str = "drawing.dxf") -> str:
    base = os.path.basename((name or "").replace("\\", "/")).strip()
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", base).strip(" .")
    return base or default


def _check_entities(entities):
    if len(entities) > MAX_CAD_ENTITIES:
        raise HTTPException(413, "Drawing too large (%d entities, limit %d)" % (len(entities), MAX_CAD_ENTITIES))
from pydantic import BaseModel, Field
from loguru import logger
from PIL import Image, ImageDraw

import auth
import db
from config import get_settings
from services.cad_service import CadService

cad_router = APIRouter(prefix="/api/v1/cad", tags=["cad"])


class SaveCadRequest(BaseModel):
    project: str = Field(..., description="Project name")
    filename: str = Field(..., description="DXF filename e.g. floor_plan.dxf")
    entities: List[Dict[str, Any]] = Field(default_factory=list, description="CAD model entities")
    layers: Optional[List[Dict[str, Any]]] = Field(default=None, description="CAD layer table")
    folder: Optional[str] = Field(default="Drawings", description="Target folder name")


class ExportCadRequest(BaseModel):
    filename: Optional[str] = Field(default="cadcraft_drawing.dxf", description="Export DXF filename")
    entities: List[Dict[str, Any]] = Field(default_factory=list, description="CAD model entities")
    layers: Optional[List[Dict[str, Any]]] = Field(default=None, description="CAD layer table")


class RenderCadForAiRequest(BaseModel):
    project: str = Field(..., description="Project name")
    entities: List[Dict[str, Any]] = Field(default_factory=list, description="CAD model entities")
    width: int = Field(default=1024, description="Render width")
    height: int = Field(default=1024, description="Render height")
    invert_colors: bool = Field(default=True, description="White background with dark lines for diffusion conditioning")


@cad_router.get("/samples")
async def list_cad_samples(request: Request):
    """List available pre-loaded CADCraft architectural and engineering samples."""
    return {"samples": CadService.get_architectural_samples()}


@cad_router.get("/sample/{sample_id}")
async def get_cad_sample(sample_id: str, request: Request):
    """Retrieve full entity graph for an architectural CAD sample."""
    sample_data = CadService.load_sample_drawing(sample_id)
    return sample_data


def _load_or_convert_dwg(cad_eng, dwg_path: str, filename: str) -> Dict[str, Any]:
    """
    Load DWG file using ODAFileConverter with disk caching for high performance.
    Subsequent loads take milliseconds instead of seconds.
    If ODA is not installed, gracefully returns extracted DWG metadata so the user
    can inspect drawing properties and view guidance.
    """
    settings = get_settings()
    cache_dir = os.path.join(settings.data_dir, "cad_cache")
    os.makedirs(cache_dir, exist_ok=True)
    import hashlib
    file_size = os.path.getsize(dwg_path) if os.path.exists(dwg_path) else 0
    try:
        with open(dwg_path, "rb") as f:
            chunk = f.read(512 * 1024)
            hash_key = hashlib.md5(chunk).hexdigest()[:12]
    except Exception:
        hash_key = str(int(os.path.getmtime(dwg_path))) if os.path.exists(dwg_path) else "0"
    safe_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', filename)
    cached_dxf = os.path.join(cache_dir, f"{safe_name}_{hash_key}_{file_size}.dxf")
    cached_json = os.path.join(cache_dir, f"{safe_name}_{hash_key}_{file_size}.json")

    if os.path.exists(cached_json) and os.path.getsize(cached_json) > 10:
        try:
            with open(cached_json, "r", encoding="utf-8") as f:
                res = json.load(f)
            res["filename"] = filename
            res["cached"] = True
            return res
        except Exception as e:
            logger.warning(f"Failed to load cached JSON: {e}")

    def _atomic_write_json(data_dict, target_path):
        try:
            tmp = target_path + f".tmp_{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data_dict, f)
            os.replace(tmp, target_path)
        except Exception as e:
            logger.warning(f"Failed to write cached JSON: {e}")

    if os.path.exists(cached_dxf):
        try:
            res = CadService.parse_dxf_stream(cached_dxf)
            res["filename"] = filename
            res["cached"] = True
            _atomic_write_json(res, cached_json)
            return res
        except Exception as e:
            logger.warning(f"Failed to load cached DXF: {e}")

    doc = cad_eng.load_doc(dwg_path)
    if doc:
        try:
            doc.saveas(cached_dxf)
        except Exception:
            pass
        res = CadService.parse_dxf_stream(doc)
        res["filename"] = filename
        _atomic_write_json(res, cached_json)
        return res

    meta = cad_eng.extract_dwg_fallback(dwg_path)
    return {
        "success": True,
        "dwg_fallback": True,
        "filename": filename,
        "entities": [],
        "layers": [{"name": "0", "color": "#808080", "visible": True, "locked": False, "linetype": "CONTINUOUS"}],
        "metadata": meta,
        "message": "DWG binary header and metadata parsed. For complete vector rendering, install ODA File Converter or save drawing as DXF.",
    }


@cad_router.post("/parse")
async def parse_cad_file(
    request: Request,
    file: Optional[UploadFile] = File(None),
    project: Optional[str] = Form(None),
    filename: Optional[str] = Form(None),
):
    """
    Parse an uploaded DXF file or an existing project drawing into CADCraft JSON entities.
    """
    settings = get_settings()
    auth.require_user(request)
    if project:
        auth.require_project(request, project)

    # 1. From direct upload
    if file:
        content_bytes = await file.read(MAX_CAD_UPLOAD_MB * 1024 * 1024 + 1)
        if len(content_bytes) > MAX_CAD_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(413, "CAD file larger than %d MB" % MAX_CAD_UPLOAD_MB)
        ext = os.path.splitext(file.filename or "")[-1].lower()
        if ext == ".dxf":
            try:
                res = await run_in_threadpool(CadService.parse_dxf_stream, io.BytesIO(content_bytes))
                res["filename"] = _safe_name(file.filename)
                return res
            except Exception as e:
                raise HTTPException(400, f"Error parsing DXF: {e}")
        elif ext == ".dwg":
            from engines.cad_engine import CadIntelligenceEngine
            cad_eng = CadIntelligenceEngine()
            import uuid as _uuid
            fname = _safe_name(file.filename, "drawing.dwg")
            tmp_dir = os.path.join(settings.data_dir, "tmp")
            os.makedirs(tmp_dir, exist_ok=True)
            tmp_path = os.path.join(tmp_dir, "%s_%s" % (_uuid.uuid4().hex[:8], fname))
            with open(tmp_path, "wb") as f:
                f.write(content_bytes)
            try:
                return await run_in_threadpool(_load_or_convert_dwg, cad_eng, tmp_path, fname)
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        else:
            raise HTTPException(400, "Only .dxf and .dwg files are supported")

    # 2. From project document path
    if project and filename:
        docs_dir = os.path.join(settings.data_dir, "docs")
        doc_dir = os.path.join(docs_dir, project)
        # Search for file in project folders
        target_path = None
        for root, _, files in os.walk(doc_dir):
            if filename in files:
                target_path = os.path.join(root, filename)
                break

        if not target_path or not os.path.exists(target_path):
            raise HTTPException(404, f"Drawing '{filename}' not found in project '{project}'")

        ext = os.path.splitext(filename)[-1].lower()
        if ext == ".dxf":
            try:
                res = await run_in_threadpool(CadService.parse_dxf_stream, target_path)
                res["filename"] = filename
                return res
            except Exception as e:
                raise HTTPException(400, f"Error parsing project DXF: {e}")
        elif ext == ".dwg":
            from engines.cad_engine import CadIntelligenceEngine
            cad_eng = CadIntelligenceEngine()
            return await run_in_threadpool(_load_or_convert_dwg, cad_eng, target_path, filename)

    raise HTTPException(400, "Provide either a file upload or project and filename.")


@cad_router.post("/save")
async def save_cad_to_project(request: Request, payload: SaveCadRequest):
    """
    Save edited CAD model entities directly into the project's Drawings folder.
    The saved DXF immediately appears in the project's Drawings workspace.
    """
    user = auth.require_roles(request, "admin", "lead", "user")
    auth.require_project(request, payload.project)
    _check_entities(payload.entities)
    settings = get_settings()

    filename = _safe_name(payload.filename)
    if not filename.lower().endswith(".dxf"):
        filename += ".dxf"

    # Sanitize filename
    clean_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)

    # Resolve target folder (default to Drawings)
    folder_name = payload.folder or "Drawings"
    folders = db.list_folders(payload.project)
    target_folder = next((f for f in folders if f["name"].lower() == folder_name.lower()), None)
    if not target_folder:
        # Create folder if it doesn't exist
        f_res = db.create_folder(payload.project, folder_name)
        fid = f_res["id"] if isinstance(f_res, dict) else int(f_res)
    else:
        fid = target_folder["id"] if isinstance(target_folder, dict) else int(target_folder)

    docs_dir = os.path.join(settings.data_dir, "docs")
    fsafe = re.sub(r"[^A-Za-z0-9._-]+", "_", folder_name).strip("_")
    proj_doc_dir = os.path.join(docs_dir, payload.project, fsafe)
    os.makedirs(proj_doc_dir, exist_ok=True)
    out_path = os.path.join(proj_doc_dir, clean_name)

    # Generate DXF string
    try:
        dxf_content = await run_in_threadpool(CadService.generate_dxf, payload.entities, payload.layers, clean_name)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"Invalid drawing data: {e}")

    existed = os.path.exists(out_path)
    tmp_out = out_path + ".tmp"
    with open(tmp_out, "w", encoding="utf-8") as f:
        f.write(dxf_content)
    os.replace(tmp_out, out_path)

    # Record in database
    file_size = os.path.getsize(out_path)
    client_ip = request.client.host if request.client else "127.0.0.1"
    if not existed:
      db.record_document(
        project=payload.project,
        filename=clean_name,
        path=out_path,
        chunks=0,
        discipline="Architectural",
        status="ready",
        folder_id=fid,
        user=user,
        ip=client_ip,
    )

    logger.info(f"Saved CAD drawing '{clean_name}' ({len(payload.entities)} entities) to project '{payload.project}'")

    return {
        "success": True,
        "filename": clean_name,
        "folder": folder_name,
        "entity_count": len(payload.entities),
        "file_size": file_size,
        "rel_path": f"{fsafe}/{clean_name}",
    }


@cad_router.post("/export-dxf")
async def export_dxf_file(request: Request, payload: ExportCadRequest):
    """Generate and return a downloadable AutoCAD DXF file."""
    auth.require_user(request)
    _check_entities(payload.entities)
    filename = _safe_name(payload.filename or "cadcraft_drawing.dxf", "cadcraft_drawing.dxf")
    if not filename.lower().endswith(".dxf"):
        filename += ".dxf"

    try:
        dxf_content = await run_in_threadpool(CadService.generate_dxf, payload.entities, payload.layers, filename)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"Invalid drawing data: {e}")

    return Response(
        content=dxf_content,
        media_type="application/dxf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@cad_router.post("/render-for-ai")
async def render_cad_for_ai(request: Request, payload: RenderCadForAiRequest):
    """
    Render CAD model entities into a clean architectural line drawing image
    and register it for instant conditioning in the AI Design Studio (Sketch to Render).
    """
    auth.require_project(request, payload.project)
    settings = get_settings()

    entities = payload.entities
    if not entities:
        raise HTTPException(400, "Cannot render empty drawing")
    _check_entities(entities)
    try:
        return await run_in_threadpool(_render_for_ai, payload, entities)
    except (ValueError, TypeError, KeyError, IndexError) as e:
        raise HTTPException(400, f"Invalid drawing data: {e}")


def _render_for_ai(payload, entities):

    w = max(512, min(payload.width, 2048))
    h = max(512, min(payload.height, 2048))

    # Calculate bounding box
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for e in entities:
        if "x1" in e and "y1" in e and "x2" in e and "y2" in e:
            min_x = min(min_x, e["x1"], e["x2"])
            max_x = max(max_x, e["x1"], e["x2"])
            min_y = min(min_y, e["y1"], e["y2"])
            max_y = max(max_y, e["y1"], e["y2"])
        elif "points" in e and e["points"]:
            for pt in e["points"]:
                min_x = min(min_x, pt[0])
                max_x = max(max_x, pt[0])
                min_y = min(min_y, pt[1])
                max_y = max(max_y, pt[1])
        elif "cx" in e and "cy" in e and "radius" in e:
            r = e["radius"]
            min_x = min(min_x, e["cx"] - r)
            max_x = max(max_x, e["cx"] + r)
            min_y = min(min_y, e["cy"] - r)
            max_y = max(max_y, e["cy"] + r)

    if min_x == float("inf"):
        min_x, min_y, max_x, max_y = 0, 0, 100, 100

    dx = max(max_x - min_x, 1.0)
    dy = max(max_y - min_y, 1.0)
    padding = 40  # pixels

    scale_x = (w - 2 * padding) / dx
    scale_y = (h - 2 * padding) / dy
    scale = min(scale_x, scale_y)

    def to_screen(x, y):
        # Y is inverted (CAD Y is up, Canvas Y is down)
        sx = padding + (x - min_x) * scale
        sy = h - (padding + (y - min_y) * scale)
        return int(sx), int(sy)

    # Background color and line color
    bg_color = (255, 255, 255) if payload.invert_colors else (20, 24, 30)
    line_color = (15, 20, 25) if payload.invert_colors else (230, 235, 245)
    wall_color = (0, 0, 0) if payload.invert_colors else (255, 255, 255)

    img = Image.new("RGB", (w, h), bg_color)
    draw = ImageDraw.Draw(img)

    for ent in entities:
        etype = ent.get("type", "").upper()
        layer = ent.get("layer", "").upper()
        col = wall_color if "WALL" in layer else line_color
        lw = 3 if "WALL" in layer else 2

        if etype == "LINE":
            p1 = to_screen(ent.get("x1", 0), ent.get("y1", 0))
            p2 = to_screen(ent.get("x2", 0), ent.get("y2", 0))
            draw.line([p1, p2], fill=col, width=lw)

        elif etype in ("POLYLINE", "RECTANGLE"):
            pts = ent.get("points")
            if not pts and etype == "RECTANGLE":
                rx, ry = ent.get("x", 0), ent.get("y", 0)
                rw_val, rh_val = ent.get("width", 10), ent.get("height", 10)
                pts = [[rx, ry], [rx + rw_val, ry], [rx + rw_val, ry + rh_val], [rx, ry + rh_val]]
            if pts and len(pts) >= 2:
                scr_pts = [to_screen(p[0], p[1]) for p in pts]
                if ent.get("closed", False):
                    scr_pts.append(scr_pts[0])
                draw.line(scr_pts, fill=col, width=lw)

        elif etype == "CIRCLE":
            cx, cy = ent.get("cx", 0), ent.get("cy", 0)
            r = ent.get("radius", 5)
            scx, scy = to_screen(cx, cy)
            sr = int(r * scale)
            draw.ellipse([scx - sr, scy - sr, scx + sr, scy + sr], outline=col, width=lw)

    # Save rendered image in image storage
    import base64
    import uuid
    from services.image_engine.image_storage import ImageStorage

    storage = ImageStorage()
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    img_bytes = img_byte_arr.getvalue()

    temp_id = f"cad-{uuid.uuid4().hex[:8]}"
    saved_path = storage.save_input_image(
        project=payload.project,
        job_id=temp_id,
        image_bytes=img_bytes,
        original_filename="cadcraft_render_conditioning.png",
    )

    b64_str = base64.b64encode(img_bytes).decode("ascii")
    data_url = f"data:image/png;base64,{b64_str}"

    logger.info(f"Rendered CAD drawing to AI conditioning image: {saved_path.name}")

    return {
        "success": True,
        "input_image_path": str(saved_path),
        "input_image_url": data_url,
        "filename": saved_path.name,
        "message": "CAD linework successfully rendered. Ready for AI architectural concept generation.",
    }
