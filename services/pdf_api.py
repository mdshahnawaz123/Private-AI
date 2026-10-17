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
import tempfile
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
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


class AskPdfRequest(BaseModel):
    doc_id: str = Field(..., description="Active PDF session ID")
    question: str = Field(..., description="User question about the active PDF")
    page_number: Optional[int] = Field(default=None, description="Optional focus page number (1-based)")
    model: Optional[str] = Field(default="qwen3.5:9b", description="Local Ollama model name")
    vision_mode: Optional[bool] = Field(default=False, description="Whether to analyze visually with local vision model")
    password: Optional[str] = Field(default=None, description="PDF password if encrypted")


class ApplyRedactionRequest(BaseModel):
    doc_id: str = Field(..., description="Active PDF session ID")
    redactions: List[Dict[str, Any]] = Field(..., description="List of redaction specs e.g. [{'page': 1, 'rect': [x0, y0, x1, y1]}]")
    password: Optional[str] = Field(default=None, description="Document password if encrypted")


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
    elif (project or filename or rel):
        clean_name = filename or (os.path.basename(rel) if rel else "")
        doc_title = clean_name
        target_path = None
        detected_folder = "Documents"

        # 1. Search in project docs directory
        if project:
            proj_dir = os.path.join(db.DATA_DIR, "docs", project)
            if rel:
                rel_clean = rel.replace("\\", "/").lstrip("/")
                candidate = os.path.join(proj_dir, rel_clean)
                if os.path.exists(candidate) and os.path.isfile(candidate):
                    target_path = candidate
                    detected_folder = os.path.dirname(rel_clean) or "Documents"
            if not target_path and clean_name and os.path.exists(proj_dir):
                for root, _, files in os.walk(proj_dir):
                    if clean_name in files:
                        target_path = os.path.join(root, clean_name)
                        rel_sub = os.path.relpath(target_path, proj_dir).replace("\\", "/")
                        detected_folder = os.path.dirname(rel_sub) or "Documents"
                        break

            # 2. Search in project reports directory
            if not target_path:
                rep_dir = os.path.join(db.DATA_DIR, "reports", project)
                if os.path.exists(rep_dir):
                    for root, _, files in os.walk(rep_dir):
                        if clean_name in files:
                            target_path = os.path.join(root, clean_name)
                            detected_folder = "Reports"
                            break

        # 3. Search in knowledge base (__knowledge_base__)
        if not target_path:
            kb_dir = os.path.join(db.DATA_DIR, "docs", "__knowledge_base__")
            if os.path.exists(kb_dir):
                for root, _, files in os.walk(kb_dir):
                    if clean_name in files:
                        target_path = os.path.join(root, clean_name)
                        detected_folder = "Codes & Standards"
                        break

        # 4. Fallback search across all docs folders
        if not target_path and clean_name:
            all_docs_dir = os.path.join(db.DATA_DIR, "docs")
            if os.path.exists(all_docs_dir):
                for root, _, files in os.walk(all_docs_dir):
                    if clean_name in files:
                        target_path = os.path.join(root, clean_name)
                        break

        if not target_path or not os.path.exists(target_path):
            raise HTTPException(
                status_code=404, 
                detail=f"PDF document '{clean_name or rel}' could not be located in project storage, reports, or knowledge base."
            )

        # Copy to cache for non-destructive local editing
        shutil.copyfile(target_path, cached_path)
    else:
        raise HTTPException(status_code=400, detail="Must provide either an uploaded PDF file or project and filename.")

    _PDF_SESSION_CACHE[session_id] = {
        "path": cached_path,
        "name": doc_title,
        "original_project": project,
        "original_filename": clean_name or doc_title,
        "detected_folder": detected_folder
    }

    info = PdfService.inspect_pdf(cached_path, password=password)
    return {
        "doc_id": session_id,
        "filename": doc_title,
        "project": project,
        "folder": detected_folder,
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
    query: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    password: Optional[str] = Query(None)
):
    """Searches document for query text, returning matches with bounding boxes."""
    search_term = query or q
    if not search_term:
        raise HTTPException(status_code=400, detail="Must provide 'query' or 'q' parameter.")
    path = _get_doc_path(doc_id)
    results = PdfService.search_text(path, search_term, password=password)
    return {"query": search_term, "total_matches": len(results), "matches": results}


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
    folder_name = req.folder or "Documents"
    proj_dir = os.path.join(db.DATA_DIR, "docs", req.project, folder_name)
    os.makedirs(proj_dir, exist_ok=True)

    dest_filename = os.path.basename(req.filename)
    if not dest_filename.lower().endswith(".pdf"):
        dest_filename += ".pdf"

    dest_path = os.path.join(proj_dir, dest_filename)
    shutil.copyfile(src_path, dest_path)

    # Resolve folder_id if exists
    folder_id = None
    try:
        folders = db.list_folders(req.project)
        for fld in folders:
            if fld.get("name", "").lower() == folder_name.lower():
                folder_id = fld.get("id")
                break
    except Exception:
        pass

    # Register in database using standard record_document
    try:
        db.record_document(
            project=req.project,
            filename=dest_filename,
            path=dest_path,
            chunks=1,
            discipline=None,
            status="ready",
            folder_id=folder_id
        )
    except Exception as exc:
        logger.warning(f"Failed to record document in db: {exc}")

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


@pdf_router.post("/ask")
async def ask_pdf(req: AskPdfRequest):
    """
    Asks the local AI model (qwen3.5:9b or qwen2.5vl:7b) questions grounded strictly
    on the content, tables, and geometry of the active PDF document.
    """
    path = _get_doc_path(req.doc_id)
    try:
        result = await run_in_threadpool(
            PdfService.ask_document,
            path,
            question=req.question,
            page_number=req.page_number,
            model=req.model or "qwen3.5:9b",
            vision_mode=bool(req.vision_mode),
            password=req.password
        )
        return result
    except Exception as exc:
        logger.error(f"Failed to answer question on PDF {req.doc_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@pdf_router.get("/audit")
async def audit_pdf_redactions(doc_id: str = Query(..., description="Active PDF session ID")):
    """
    Runs the clean-room faux-redaction and unapplied mark audit (storytold/pdfcraft crates/audit).
    Detects opaque covers over extractable text and unapplied /Redact annotations.
    """
    path = _get_doc_path(doc_id)
    try:
        result = await run_in_threadpool(PdfService.audit_redactions, path)
        return result
    except Exception as exc:
        logger.error(f"Failed to audit PDF redactions {doc_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@pdf_router.post("/redact-apply")
async def apply_pdf_redactions(req: ApplyRedactionRequest):
    """
    Permanently burns and applies redactions into the document, stripping underlying characters
    and raster image pixels so they can never be extracted or recovered.
    """
    path = _get_doc_path(req.doc_id)
    try:
        temp_out = os.path.join(tempfile.gettempdir(), f"redacted_{req.doc_id}_{int(time.time())}.pdf")
        result = await run_in_threadpool(
            PdfService.apply_permanent_redactions,
            path,
            temp_out,
            req.redactions
        )
        _PDF_SESSION_CACHE[req.doc_id] = temp_out
        new_info = await run_in_threadpool(PdfService.inspect_pdf, temp_out)
        return {
            "success": True,
            "applied_count": result.get("applied_count", 0),
            "doc_id": req.doc_id,
            "info": new_info
        }
    except Exception as exc:
        logger.error(f"Failed to apply redactions on PDF {req.doc_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@pdf_router.get("/stats")
async def get_pdf_statistics(doc_id: str = Query(..., description="Active PDF session ID")):
    """
    Computes comprehensive document statistics (storytold/pdfcraft text_word_count).
    Reports total words, character count, page count, images, and embedded fonts.
    """
    path = _get_doc_path(doc_id)
    try:
        result = await run_in_threadpool(PdfService.get_document_statistics, path)
        return result
    except Exception as exc:
        logger.error(f"Failed to get PDF statistics {doc_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Bluebeam Revu Features: Overlay Pages & Markups AI ─────────────────────
@pdf_router.get("/overlay")
async def overlay_revisions(
    doc_a: Optional[str] = Query(None),
    doc_b: Optional[str] = Query(None),
    doc1: Optional[str] = Query(None),
    doc2: Optional[str] = Query(None),
    page_a: Optional[int] = Query(None),
    page_b: Optional[int] = Query(None),
    page1: Optional[int] = Query(None),
    page2: Optional[int] = Query(None),
    zoom: float = Query(1.5),
    password_a: Optional[str] = Query(None),
    password_b: Optional[str] = Query(None),
):
    """
    Bluebeam Revu standard Overlay Pages comparison.
    Renders Page A in Red and Page B in Green.
    Unchanged lines appear Black; additions appear Green; deletions appear Red.
    """
    target_doc_a = doc_a or doc1
    target_doc_b = doc_b or doc2
    if not target_doc_a or not target_doc_b:
        raise HTTPException(status_code=400, detail="Missing document IDs for comparison (doc1/doc2 or doc_a/doc_b required)")

    target_page_a = page_a or page1 or 1
    target_page_b = page_b or page2 or 1

    path_a = _get_doc_path(target_doc_a)
    path_b = _get_doc_path(target_doc_b)
    try:
        img_bytes, w, h = await run_in_threadpool(
            PdfService.compare_revisions_overlay,
            path_a, path_b, page_a=target_page_a, page_b=target_page_b, zoom=zoom,
            password_a=password_a, password_b=password_b
        )
        return Response(
            content=img_bytes,
            media_type="image/png",
            headers={"X-Page-Width": str(w), "X-Page-Height": str(h), "Cache-Control": "public, max-age=600"}
        )
    except Exception as exc:
        logger.error(f"Failed to overlay revisions {target_doc_a} and {target_doc_b}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


class MarkupsSummarizeRequest(BaseModel):
    doc_id: Optional[str] = None
    doc_name: Optional[str] = None
    document_name: Optional[str] = None
    markups: List[Dict[str, Any]] = Field(default_factory=list)


@pdf_router.post("/summarize-markups")
async def summarize_markups(req: MarkupsSummarizeRequest):
    """
    Bluebeam Markups List AI Review:
    Summarizes all markups, open issues, and action items using local LLM.
    """
    try:
        doc_title = req.document_name or req.doc_name or "Active Document"
        res = await run_in_threadpool(
            PdfService.summarize_markups_ai,
            req.markups,
            doc_name=doc_title
        )
        if isinstance(res, dict):
            return {"summary": res, **res}
        return {"summary": res}
    except Exception as exc:
        logger.error(f"Failed to summarize markups: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


