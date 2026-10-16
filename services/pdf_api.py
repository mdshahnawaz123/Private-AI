"""
PdfCraft API Router for Expo Design AI.
Exposes REST endpoints for the local-first offline PDF Workbench:
- Opening and inspecting PDFs (metadata, TOC, form fields, page sizes)
- High-resolution deep zoom rendering and thumbnail generation
- Reading-order search-as-you-type with exact bounding rectangles
- Card-based page organization (rotate, reorder, delete, duplicate, insert blank)
- Merging and splitting documents
- Vector markups, sticky notes, highlights, and watermarks
- AES-256 security encryption and permission locking
- Seamless integration with AI Design Studio and Project Documents
"""
import io
import os
import re
import uuid
import shutil
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from loguru import logger

import auth
import db
from services.pdf_service import PdfService

pdf_router = APIRouter(prefix="/api/v1/pdf", tags=["pdfcraft"])

_PDF_SESSION_CACHE: Dict[str, Dict[str, Any]] = {}
PDF_CACHE_DIR = os.path.join(db.DATA_DIR, "pdf_cache")
os.makedirs(PDF_CACHE_DIR, exist_ok=True)


def _get_doc_path(doc_id: str) -> str:
    """Resolves session doc_id to absolute path."""
    if doc_id in _PDF_SESSION_CACHE:
        return _PDF_SESSION_CACHE[doc_id]["path"]
    
    # Try looking in cache directory
    cand = os.path.join(PDF_CACHE_DIR, f"{doc_id}.pdf")
    if os.path.exists(cand):
        return cand
    cand2 = os.path.join(PDF_CACHE_DIR, doc_id)
    if os.path.exists(cand2):
        return cand2
        
    raise HTTPException(status_code=404, detail="PDF session expired or document not found. Please reopen the file.")


class OrganizeRequest(BaseModel):
    doc_id: str = Field(..., description="Active PDF session ID")
    reorder: Optional[List[int]] = Field(default=None, description="New sequence of 1-based page indices")
    rotate: Optional[List[Dict[str, int]]] = Field(default=None, description="Page rotations e.g. [{'page': 1, 'angle': 90}]")
    delete: Optional[List[int]] = Field(default=None, description="1-based page indices to delete")
    duplicate: Optional[List[int]] = Field(default=None, description="1-based page indices to duplicate")
    insert_blank: Optional[Dict[str, Any]] = Field(default=None, description="Blank page specs e.g. {'at_page': 2, 'width': 595, 'height': 842}")
    password: Optional[str] = Field(default=None, description="Document password if encrypted")


class AnnotateRequest(BaseModel):
    doc_id: str = Field(..., description="Active PDF session ID")
    annot_type: str = Field(..., description="highlight, rect, note, or text")
    page_number: int = Field(..., description="1-based page number")
    rect: List[float] = Field(..., description="Bounding box [x0, y0, x1, y1]")
    content: Optional[str] = Field(default="", description="Annotation text or comment content")
    color: Optional[List[float]] = Field(default=None, description="RGB normalized float list e.g. [1.0, 0.8, 0.2]")
    password: Optional[str] = Field(default=None, description="Document password if encrypted")


class WatermarkRequest(BaseModel):
    doc_id: str = Field(..., description="Active PDF session ID")
    text: str = Field(default="CONFIDENTIAL", description="Watermark text stamp")
    opacity: float = Field(default=0.25, description="Opacity 0.0 to 1.0")
    font_size: int = Field(default=52, description="Font size in points")
    color: Optional[List[float]] = Field(default=None, description="RGB normalized color")
    pages: Optional[List[int]] = Field(default=None, description="Target pages or None for all")


class SecurityRequest(BaseModel):
    doc_id: str = Field(..., description="Active PDF session ID")
    user_password: str = Field(..., description="Document open password")
    owner_password: Optional[str] = Field(default=None, description="Admin owner password")
    can_print: bool = Field(default=True, description="Allow printing")
    can_copy: bool = Field(default=True, description="Allow copying text")
    can_modify: bool = Field(default=False, description="Allow modifying contents")
    can_annotate: bool = Field(default=True, description="Allow annotations")


class MergeRequest(BaseModel):
    doc_ids: List[str] = Field(..., description="List of document IDs or filenames to merge")
    output_filename: str = Field(default="Merged_Document.pdf", description="Output filename")
    project: Optional[str] = Field(default=None, description="Target project to save into")


class SaveToProjectRequest(BaseModel):
    doc_id: str = Field(..., description="Active PDF session ID")
    project: str = Field(..., description="Target project name")
    filename: str = Field(..., description="Destination PDF filename e.g. Final_Submission.pdf")
    folder: Optional[str] = Field(default="Documents", description="Target folder name")


class RenderForAiRequest(BaseModel):
    doc_id: str = Field(..., description="Active PDF session ID")
    page_number: int = Field(default=1, description="1-based page number")
    project: str = Field(..., description="Project name")
    width: int = Field(default=1024, description="Target width")
    height: int = Field(default=1024, description="Target height")


# --- Endpoints ---

@pdf_router.get("/samples")
async def list_samples():
    """Returns list of built-in architectural and masterplan PDF samples."""
    return {"samples": PdfService.get_sample_documents()}


@pdf_router.get("/sample/{sample_id}")
async def load_sample(sample_id: str):
    """Loads or creates a built-in sample document and opens an active PdfCraft session."""
    samples = {s["id"]: s for s in PdfService.get_sample_documents()}
    if sample_id not in samples:
        raise HTTPException(status_code=404, detail="Sample document not found.")

    path = PdfService.load_or_create_sample(sample_id, PDF_CACHE_DIR)
    session_id = f"sample_{sample_id}_{uuid.uuid4().hex[:6]}"
    _PDF_SESSION_CACHE[session_id] = {
        "path": path,
        "name": f"{sample_id}.pdf",
        "title": samples[sample_id]["title"]
    }

    doc_info = PdfService.inspect_pdf(path)
    return {
        "doc_id": session_id,
        "filename": f"{sample_id}.pdf",
        "title": samples[sample_id]["title"],
        "info": doc_info
    }


@pdf_router.get("/project-files")
async def list_project_pdfs(project: str = Query(...)):
    """Lists all available PDF files in the specified project."""
    docs = db.list_documents(project)
    pdf_docs = []
    for d in docs:
        fname = d.get("filename", "")
        if fname.lower().endswith(".pdf"):
            pdf_docs.append({
                "filename": fname,
                "folder": d.get("folder", "Documents"),
                "size": d.get("size", 0),
                "chunks": d.get("chunks", 0),
                "rel": d.get("rel", "")
            })
    return {"project": project, "files": pdf_docs}


@pdf_router.post("/open")
async def open_pdf(
    file: Optional[UploadFile] = File(None),
    project: Optional[str] = Form(None),
    filename: Optional[str] = Form(None),
    rel: Optional[str] = Form(None),
    password: Optional[str] = Form(None)
):
    """
    Opens a PDF document from an upload or from project storage.
    Initializes a session and returns the complete PdfCraft inspection model.
    """
    session_id = f"pdf_{uuid.uuid4().hex[:10]}"
    cached_path = os.path.join(PDF_CACHE_DIR, f"{session_id}.pdf")
    doc_title = ""

    if file:
        doc_title = file.filename
        with open(cached_path, "wb") as f_out:
            shutil.copyfileobj(file.file, f_out)
    elif project and (filename or rel):
        doc_title = filename or os.path.basename(rel)
        proj_dir = os.path.join(db.DATA_DIR, "docs", project)
        target_path = None
        if rel:
            rel_clean = rel.replace("\\", "/").lstrip("/")
            candidate = os.path.join(proj_dir, rel_clean)
            if os.path.exists(candidate) and os.path.isfile(candidate):
                target_path = candidate
        if not target_path and filename:
            for root, _, files in os.walk(proj_dir):
                if filename in files:
                    target_path = os.path.join(root, filename)
                    break
        if not target_path or not os.path.exists(target_path):
            raise HTTPException(status_code=404, detail=f"File '{filename or rel}' not found in project '{project}'.")
        # Copy to cache for non-destructive incremental editing
        shutil.copyfile(target_path, cached_path)
    else:
        raise HTTPException(status_code=400, detail="Must provide either an uploaded PDF file or project and filename.")

    _PDF_SESSION_CACHE[session_id] = {
        "path": cached_path,
        "name": doc_title,
        "original_project": project,
        "original_filename": filename
    }

    info = PdfService.inspect_pdf(cached_path, password=password)
    return {
        "doc_id": session_id,
        "filename": doc_title,
        "info": info
    }


@pdf_router.get("/render-page")
async def render_page(
    doc_id: str = Query(...),
    page: int = Query(1),
    zoom: float = Query(1.5),
    password: Optional[str] = Query(None),
    format_type: str = Query("png")
):
    """
    Renders a single page with crisp subpixel typography at any deep zoom level.
    """
    path = _get_doc_path(doc_id)
    try:
        img_bytes, w, h = PdfService.render_page(
            path,
            page_number=page,
            zoom=zoom,
            password=password,
            format_type=format_type
        )
        media_type = f"image/{format_type.lower()}"
        return Response(
            content=img_bytes,
            media_type=media_type,
            headers={
                "X-Page-Width": str(w),
                "X-Page-Height": str(h),
                "Cache-Control": "public, max-age=3600"
            }
        )
    except Exception as exc:
        logger.error(f"Failed to render page {page} for doc {doc_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@pdf_router.get("/thumbnail")
async def get_thumbnail(
    doc_id: str = Query(...),
    page: int = Query(1),
    width: int = Query(220),
    password: Optional[str] = Query(None)
):
    """Returns lightweight thumbnail image for card-based organizer."""
    path = _get_doc_path(doc_id)
    try:
        img_bytes = PdfService.render_thumbnail(path, page_number=page, max_width=width, password=password)
        return Response(content=img_bytes, media_type="image/jpeg")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@pdf_router.get("/search")
async def search_document(
    doc_id: str = Query(...),
    query: str = Query(...),
    password: Optional[str] = Query(None)
):
    """Searches document for query text, returning matches with bounding boxes."""
    path = _get_doc_path(doc_id)
    results = PdfService.search_text(path, query, password=password)
    return {"query": query, "total_matches": len(results), "matches": results}


@pdf_router.post("/organize")
async def organize_pages(req: OrganizeRequest):
    """
    Executes card-based page reorganization (rotate, reorder, delete, duplicate, insert blank).
    Updates document in-place atomically.
    """
    path = _get_doc_path(req.doc_id)
    ops = {}
    if req.reorder:
        ops["reorder"] = req.reorder
    if req.rotate:
        ops["rotate"] = req.rotate
    if req.delete:
        ops["delete"] = req.delete
    if req.duplicate:
        ops["duplicate"] = req.duplicate
    if req.insert_blank:
        ops["insert_blank"] = req.insert_blank

    try:
        res = PdfService.organize_pages(path, path, ops, password=req.password)
        updated_info = PdfService.inspect_pdf(path, password=req.password)
        return {
            "status": "success",
            "message": res["message"],
            "page_count": res["page_count"],
            "info": updated_info
        }
    except Exception as exc:
        logger.error(f"Failed to organize pages: {exc}")
        raise HTTPException(status_code=400, detail=str(exc))


@pdf_router.post("/merge")
async def merge_documents(req: MergeRequest):
    """Merges multiple PDF documents into a new unified master document."""
    paths = []
    for item in req.doc_ids:
        if item in _PDF_SESSION_CACHE:
            paths.append(_PDF_SESSION_CACHE[item]["path"])
        else:
            # Check if it's a project document
            if req.project:
                proj_dir = os.path.join(db.DATA_DIR, "docs", req.project)
                for root, _, files in os.walk(proj_dir):
                    if item in files:
                        paths.append(os.path.join(root, item))
                        break

    if not paths:
        raise HTTPException(status_code=400, detail="No valid PDF documents found to merge.")

    new_id = f"merged_{uuid.uuid4().hex[:10]}"
    out_path = os.path.join(PDF_CACHE_DIR, f"{new_id}.pdf")

    res = PdfService.merge_pdfs(paths, out_path)
    _PDF_SESSION_CACHE[new_id] = {
        "path": out_path,
        "name": req.output_filename,
        "original_project": req.project
    }

    info = PdfService.inspect_pdf(out_path)
    return {
        "doc_id": new_id,
        "filename": req.output_filename,
        "message": res["message"],
        "info": info
    }


@pdf_router.post("/split")
async def split_document(
    doc_id: str = Form(...),
    ranges: Optional[str] = Form(None)
):
    """Splits PDF by page ranges (e.g. '1-2, 3-5') or into individual page files."""
    path = _get_doc_path(doc_id)
    split_dir = os.path.join(PDF_CACHE_DIR, f"split_{uuid.uuid4().hex[:8]}")
    range_list = [r.strip() for r in ranges.split(",")] if ranges else None

    files = PdfService.split_pdf(path, split_dir, range_list)
    result_files = []
    for f in files:
        sub_id = f"split_{uuid.uuid4().hex[:8]}"
        _PDF_SESSION_CACHE[sub_id] = {"path": f, "name": os.path.basename(f)}
        result_files.append({
            "doc_id": sub_id,
            "filename": os.path.basename(f),
            "size": os.path.getsize(f)
        })

    return {
        "status": "success",
        "total_parts": len(result_files),
        "files": result_files
    }


@pdf_router.post("/annotate")
async def add_annotation(req: AnnotateRequest):
    """Adds a vector markup or comment note onto a page."""
    path = _get_doc_path(req.doc_id)
    col = tuple(req.color) if req.color else None
    res = PdfService.add_annotation(
        input_path=path,
        output_path=path,
        annot_type=req.annot_type,
        page_number=req.page_number,
        rect=req.rect,
        content=req.content,
        color=col
    )
    return res


@pdf_router.post("/watermark")
async def add_watermark(req: WatermarkRequest):
    """Stamps semi-transparent watermark across pages."""
    path = _get_doc_path(req.doc_id)
    col = tuple(req.color) if req.color else (0.7, 0.2, 0.2)
    res = PdfService.add_watermark(
        input_path=path,
        output_path=path,
        text=req.text,
        opacity=req.opacity,
        font_size=req.font_size,
        color=col,
        pages=req.pages
    )
    return res


@pdf_router.post("/security")
async def set_security(req: SecurityRequest):
    """Encrypts document with AES-256 standard security and permission flags."""
    path = _get_doc_path(req.doc_id)
    res = PdfService.set_security(
        input_path=path,
        output_path=path,
        user_password=req.user_password,
        owner_password=req.owner_password,
        can_print=req.can_print,
        can_copy=req.can_copy,
        can_modify=req.can_modify,
        can_annotate=req.can_annotate
    )
    return res


@pdf_router.post("/remove-security")
async def remove_security(doc_id: str = Form(...), password: str = Form(...)):
    """Decrypts document and removes password protection."""
    path = _get_doc_path(doc_id)
    res = PdfService.remove_security(path, path, password=password)
    return res


@pdf_router.post("/save-to-project")
async def save_to_project(req: SaveToProjectRequest):
    """Atomically saves modified PDF back to project documents folder."""
    src_path = _get_doc_path(req.doc_id)
    proj_dir = os.path.join(db.DATA_DIR, "docs", req.project, req.folder or "Documents")
    os.makedirs(proj_dir, exist_ok=True)

    dest_filename = os.path.basename(req.filename)
    if not dest_filename.lower().endswith(".pdf"):
        dest_filename += ".pdf"

    dest_path = os.path.join(proj_dir, dest_filename)
    shutil.copyfile(src_path, dest_path)

    # Register in database
    db.upsert_document(
        project_name=req.project,
        filename=dest_filename,
        folder=req.folder or "Documents",
        size_bytes=os.path.getsize(dest_path),
        chunks=1
    )

    return {
        "status": "success",
        "message": f"Successfully saved '{dest_filename}' to project '{req.project}'.",
        "saved_path": dest_path
    }


@pdf_router.get("/export")
async def export_pdf(doc_id: str = Query(...), filename: Optional[str] = Query(None)):
    """Downloads the active PDF document."""
    path = _get_doc_path(doc_id)
    out_name = filename or _PDF_SESSION_CACHE.get(doc_id, {}).get("name") or "PdfCraft_Document.pdf"
    if not out_name.lower().endswith(".pdf"):
        out_name += ".pdf"
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=out_name
    )


@pdf_router.post("/render-for-ai")
async def render_for_ai(req: RenderForAiRequest):
    """
    Renders high-res page image ready for AI Design Studio conditioning.
    Stores image under project generated_images and returns image path and web URL.
    """
    src_path = _get_doc_path(req.doc_id)
    img = PdfService.render_for_ai(src_path, page_number=req.page_number, width=req.width, height=req.height)

    img_dir = os.path.join(db.DATA_DIR, "projects", req.project, "generated_images")
    os.makedirs(img_dir, exist_ok=True)
    img_name = f"pdf_cond_{uuid.uuid4().hex[:8]}.png"
    out_path = os.path.join(img_dir, img_name)
    img.save(out_path, format="PNG")

    rel_url = f"/api/projects/{req.project}/images/{img_name}"
    return {
        "status": "success",
        "image_path": out_path,
        "image_url": rel_url,
        "message": f"Page {req.page_number} rendered for AI Design Studio conditioning."
    }
