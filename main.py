try:
    from dotenv import load_dotenv
    load_dotenv()  # read .env before anything reads os.getenv
except Exception:
    pass
import os, shutil, json, time, re, threading
import mimetypes as _mimetypes
# Static .mjs/.wasm files (vendored for the Fragments 3D engine migration, served
# under /ui/vendor_fragments/) need correct MIME types for strict ES-module loading
# in the browser -- Python's mimetypes DB doesn't know either extension by default,
# which makes StaticFiles fall back to text/plain and the browser refuses to execute
# the module. Registered globally, once, at process start; affects only how these
# two extensions are served, nothing else.
_mimetypes.add_type("application/javascript", ".mjs")
_mimetypes.add_type("application/wasm", ".wasm")

_FRAGMENTS_POC_MARKER = "poc-marker-20261002-A"
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, RedirectResponse, FileResponse, PlainTextResponse
from pydantic import BaseModel
from typing import List, Optional
import traceback
from fastapi.concurrency import run_in_threadpool
from loguru import logger
import db
import disciplines
import vision
import cad
import auth
import extract
import meta_parse
import response_schema

from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, UnstructuredExcelLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import ChatOllama
import local_embed
import local_chat
from langchain_community.vectorstores import FAISS
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

PORT = int(os.getenv("EXPO_PORT", "8090"))
HOST = os.getenv("EXPO_HOST", "127.0.0.1")

app = FastAPI(title="Expo Design AI")
# CORS restricted to the local served origin(s). Override with EXPO_CORS_ORIGINS
# (comma-separated) when deploying to a company server.
_default_origins = [f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"]
CORS_ORIGINS = [o.strip() for o in os.getenv("EXPO_CORS_ORIGINS", ",".join(_default_origins)).split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def _auth_mw(request, call_next):
    try:
        request.state.user = auth.user_from_request(request)
    except Exception:
        request.state.user = None
    path = request.url.path
    # /docs, /openapi.json and /redoc deliberately require login (any role) --
    # publicly exposing the full API schema (all endpoints, params, shapes)
    # makes reconnaissance trivial for anyone with network access to this
    # machine, with no benefit for a private internal tool.
    public = (path == "/" or path.startswith("/ui") or path.startswith("/auth/login")
              or path.startswith("/health") or path.startswith("/favicon"))
    if request.method == "OPTIONS" or public:
        return await call_next(request)
    if request.state.user is None:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Login required"}, status_code=401)
    return await call_next(request)

DATA_DIR = "data"
DOCS_DIR = os.path.join(DATA_DIR, "docs")
PROJECTS_DIR = os.path.join(DATA_DIR, "projects")
INDEX_DIR = os.path.join(DATA_DIR, "faiss_index")
WORKSPACE_DIR = os.path.join(DATA_DIR, "workspace")
# Private AI-chat attachments (the "+" button in the Copilot). Deliberately
# OUTSIDE DOCS_DIR so no project document listing / folder scan can ever
# surface a user's private upload.
PRIVATE_UPLOADS_DIR = os.path.join(DATA_DIR, "private_uploads")
KB_COLLECTION = "__codes__"   # shared DBC/IBC code knowledge base

CATEGORY_MAP = {
    "Drawings": {".dwg", ".dxf"},
    "3D Models": {".rvt", ".rfa", ".nwd", ".nwc", ".nwf", ".ifc", ".skp", ".fbx", ".obj", ".glb", ".gltf", ".step", ".stp", ".iges", ".igs", ".3ds", ".dae"},
    "Schedules": {".xlsx", ".xls", ".csv"},
    "Reports": {".pdf", ".docx", ".doc", ".txt", ".rtf"},
    "Images": {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"},
}
INDEXABLE_EXTS = {".pdf", ".docx", ".xlsx", ".xls", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".dwg", ".dxf"}
BLOCK_EXTS = {".exe", ".bat", ".cmd", ".com", ".msi", ".dll", ".sh", ".ps1", ".vbs", ".js", ".jar", ".scr"}

def _save_upload_capped(file, save_path):
    """Stream an UploadFile to disk, enforcing config.max_upload_size_mb.
    Thin FastAPI-facing wrapper around services.ingestion.save_upload_capped
    (kept framework-free there so it's directly unit-testable -- see
    tests/test_security.py)."""
    from config import get_settings
    from services.ingestion import save_upload_capped, UploadTooLargeError
    max_bytes = get_settings().max_upload_size_mb * 1024 * 1024
    try:
        save_upload_capped(file.file, save_path, max_bytes)
    except UploadTooLargeError as e:
        raise HTTPException(413, str(e))


def categorize(filename):
    e = os.path.splitext(filename or "")[-1].lower()
    for cat, exts in CATEGORY_MAP.items():
        if e in exts:
            return cat
    return "Other"

def category_subdir(cat):
    return cat.replace(" ", "-")
os.makedirs(DOCS_DIR, exist_ok=True)
os.makedirs(PROJECTS_DIR, exist_ok=True)
os.makedirs(INDEX_DIR, exist_ok=True)
os.makedirs(WORKSPACE_DIR, exist_ok=True)

db.init_db()
auth.ensure_admin()

# Phase 0: Initialize model registry and orchestrator
from core.model_registry import get_registry
from core.orchestrator import get_orchestrator

model_registry = get_registry()
orchestrator = get_orchestrator()

# Phase 2: Initialize Knowledge Hub
from knowledge.hub import get_hub
from knowledge.graph import get_graph
from knowledge.provenance import get_tracker
from knowledge.precedence import get_precedence

knowledge_hub = get_hub()
knowledge_graph = get_graph()
provenance_tracker = get_tracker()
source_precedence = get_precedence()

# Phase 1: Initialize Ingestion Pipeline
from services.ingestion import get_pipeline, DocumentState

ingestion_pipeline = get_pipeline()

# Phase 3: Initialize Hybrid Retrieval
from intelligence.retrieval import get_retriever

hybrid_retriever = get_retriever()

# Phase 4: Initialize Compliance + Validation engines
from intelligence.compliance import get_engine, ComplianceStatus, Severity
from intelligence.validation import get_validation_engine, FindingState

compliance_engine = get_engine()
validation_engine = get_validation_engine()

# Phase 5: Initialize specialized engines
from engines.ocr_engine import get_ocr_engine
from engines.layout_engine import get_layout_engine
from engines.drawing_engine import get_drawing_engine

ocr_engine = get_ocr_engine()
layout_engine = get_layout_engine()
drawing_engine = get_drawing_engine()

# Phase 6: Initialize Agent Runtime
from agents.runtime import get_runtime
from agents.tools import get_registry

agent_runtime = get_runtime()
tool_registry = get_registry()

# Phase 7: Initialize BIM Service
from engines.ifc_engine import get_ifc_engine
from services.bim_service import get_bim_service

ifc_engine = get_ifc_engine()
bim_service = get_bim_service()

# Phase 8: Initialize Report Engine
from intelligence.reports import get_report_engine

report_engine = get_report_engine()

# Phase 9: Initialize Observability
from core.observability import get_observability

observability = get_observability()

# Phase 10: Initialize Evaluation Framework
from tests.evaluation.eval_framework import get_eval_framework

eval_framework = get_eval_framework()

def _client_ip(request):
    try:
        return request.client.host if request and request.client else None
    except Exception:
        return None

# Explicit route for the vendored Fragments engine files (3D engine migration PoC).
# Registered BEFORE the generic /ui StaticFiles mount below so it takes precedence for
# this one subpath. Needed because strict ES-module loading requires an exact
# application/javascript (.mjs) / application/wasm (.wasm) Content-Type, and relying on
# the process-global `mimetypes` module proved fragile (something imported elsewhere in
# this app appears to reset its type map after our own mimetypes.add_type() calls ran,
# so StaticFiles' default guess_type() kept falling back to text/plain). This route sets
# the Content-Type explicitly per-extension instead of depending on that global state.
_VENDOR_FRAGMENTS_MIME = {".mjs": "application/javascript", ".wasm": "application/wasm",
                           ".js": "application/javascript"}
@app.get("/ui/vendor_fragments/{rel_path:path}")
async def _vendor_fragments_file(rel_path: str):
    base = os.path.abspath(os.path.join("ui", "vendor_fragments"))
    target = os.path.abspath(os.path.join(base, rel_path))
    if target != base and not target.startswith(base + os.sep):
        raise HTTPException(400, "Invalid path")
    if not os.path.isfile(target):
        raise HTTPException(404, "Not found")
    ext = os.path.splitext(target)[1].lower()
    media_type = _VENDOR_FRAGMENTS_MIME.get(ext)
    return FileResponse(target, media_type=media_type, headers={"X-Poc-Route": "hit", "X-Poc-Ext": ext, "X-Poc-Media": str(media_type)})

if os.path.isdir("ui"):
    app.mount("/ui", StaticFiles(directory="ui", html=True), name="ui")

@app.get("/")
async def root():
    # V2 UI is opt-in and reversible: when enable_ui_v2 is True, land on the new
    # Design Workspace shell (ui/app.html); otherwise keep the current ui/index.html.
    # Both files stay directly reachable under /ui/ regardless of the flag.
    try:
        from config import get_settings as _gs_ui
        if _gs_ui().enable_ui_v2:
            return RedirectResponse(url="/ui/app.html")
    except Exception:
        pass
    return RedirectResponse(url="/ui/")


# ============================================================
# Phase 0: Health endpoints
# ============================================================

@app.get("/_poc_whoami")
async def _poc_whoami():
    return {"marker": _FRAGMENTS_POC_MARKER, "mjs_mime": __import__("mimetypes").guess_type("x.mjs")[0]}

@app.get("/health")
async def health_check():
    """Basic health check — always responds."""
    return {"status": "ok", "service": "expo-design-ai"}


@app.get("/health/full")
async def health_full():
    """Comprehensive health check including all services."""
    return observability.health_check()


@app.get("/health/models")
async def health_models():
    """Check health of all registered AI models."""
    return model_registry.health_check()


@app.get("/health/db")
async def health_db():
    """Check database connectivity."""
    try:
        with db.SessionLocal() as s:
            s.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": str(e)}


@app.get("/diagnostics/ifc")
async def diagnostics_ifc(request: Request, project: str = "", limit: int = 100):
    """Recent IFC upload/convert pipeline events (newest last) plus a quick
    environment self-check. Admin/lead only. Use this after uploading an IFC to
    see what happened and what (if anything) went wrong with .frag conversion."""
    auth.require_roles(request, "admin", "lead")
    events = []
    try:
        if os.path.exists(IFC_DIAG_PATH):
            with open(IFC_DIAG_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for ln in lines:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    evt = json.loads(ln)
                except Exception:
                    continue
                if project and evt.get("project") != project:
                    continue
                events.append(evt)
    except Exception as e:
        return {"events": [], "error": str(e)}
    if limit and limit > 0:
        events = events[-limit:]
    app_dir = os.path.dirname(os.path.abspath(__file__))
    env = {
        "converter_enabled": os.getenv("EXPO_FRAGMENTS_CONVERT", "1").lower() in ("1", "true", "yes", "on"),
        "converter_script_present": os.path.exists(os.path.join(app_dir, "tools", "fragments", "convert_ifc_to_frag.mjs")),
        "deps_installed": os.path.isdir(os.path.join(app_dir, "tools", "fragments", "node_modules")),
        "node_bin": os.getenv("EXPO_NODE_BIN", "node"),
        "timeout_s": os.getenv("EXPO_FRAGMENTS_TIMEOUT", "900"),
        "log_path": IFC_DIAG_PATH,
    }
    return {"count": len(events), "env": env, "events": events}


@app.get("/diagnostics/ifc/raw", response_class=PlainTextResponse)
async def diagnostics_ifc_raw(request: Request):
    """Raw JSONL of the IFC pipeline log -- easy to copy/paste back to share.
    Admin/lead only."""
    auth.require_roles(request, "admin", "lead")
    try:
        if os.path.exists(IFC_DIAG_PATH):
            with open(IFC_DIAG_PATH, "r", encoding="utf-8") as f:
                return f.read()
    except Exception as e:
        return "error: " + str(e)
    return ""


VIEWER_DIAG_PATH = os.path.join(DATA_DIR, "diagnostics", "viewer.jsonl")

@app.post("/diagnostics/viewer")
async def diagnostics_viewer_post(request: Request):
    """Receive a client-side diagnostics event from the Fragments beta viewer
    (boot steps + errors, including module-import failures). Best-effort append;
    always returns ok. Admin/lead only."""
    auth.require_roles(request, "admin", "lead")
    try:
        body = await request.json()
    except Exception:
        body = {}
    evt = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if isinstance(body, dict):
        for k in ("project", "stage", "status", "error", "detail", "stack"):
            v = body.get(k)
            if v is not None:
                if isinstance(v, str) and len(v) > 1200:
                    v = v[:1200] + "…"
                evt[k] = v
    try:
        os.makedirs(os.path.dirname(VIEWER_DIAG_PATH), exist_ok=True)
        with _IFC_DIAG_LOCK:
            with open(VIEWER_DIAG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(evt, ensure_ascii=False) + "\n")
            try:
                with open(VIEWER_DIAG_PATH, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                if len(lines) > IFC_DIAG_MAX_LINES:
                    with open(VIEWER_DIAG_PATH, "w", encoding="utf-8") as f:
                        f.writelines(lines[-IFC_DIAG_MAX_LINES:])
            except Exception:
                pass
    except Exception:
        pass
    return {"ok": True}

@app.get("/diagnostics/viewer")
async def diagnostics_viewer_get(request: Request, limit: int = 200):
    """Recent Fragments beta-viewer diagnostics events. Admin/lead only."""
    auth.require_roles(request, "admin", "lead")
    events = []
    try:
        if os.path.exists(VIEWER_DIAG_PATH):
            with open(VIEWER_DIAG_PATH, "r", encoding="utf-8") as f:
                for ln in f.readlines():
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        events.append(json.loads(ln))
                    except Exception:
                        pass
    except Exception as e:
        return {"events": [], "error": str(e)}
    if limit and limit > 0:
        events = events[-limit:]
    return {"count": len(events), "events": events}


# ── Phase 9: Observability endpoints ───────────────────────

@app.get("/metrics")
async def metrics():
    """Get system metrics."""
    return observability.get_system_metrics()


@app.get("/metrics/summary")
async def metrics_summary():
    """Get summary of recorded metrics."""
    return observability.get_metrics_summary()


# ── Phase 10: Evaluation endpoints ─────────────────────────

@app.get("/evaluation/datasets")
async def evaluation_datasets():
    """List evaluation datasets."""
    return {"datasets": list(eval_framework._datasets.keys())}


@app.post("/evaluation/run")
async def evaluation_run(request: Request):
    """Run an evaluation."""
    user = auth.require_user(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    dataset_id = body.get("dataset_id", "")
    eval_type = body.get("type", "")
    if not dataset_id or not eval_type:
        raise HTTPException(400, "dataset_id and type required")
    if eval_type == "ocr":
        from engines.ocr_engine import get_ocr_engine
        result = eval_framework.evaluate_ocr(dataset_id, get_ocr_engine())
    elif eval_type == "retrieval":
        result = eval_framework.evaluate_retrieval(dataset_id, hybrid_retriever)
    elif eval_type == "compliance":
        result = eval_framework.evaluate_compliance(dataset_id, compliance_engine)
    else:
        raise HTTPException(400, f"Unknown evaluation type: {eval_type}")
    return {
        "dataset": result.dataset_name,
        "total": result.total_examples,
        "passed": result.passed,
        "failed": result.failed,
        "accuracy": result.accuracy,
        "latency_ms": result.latency_ms,
    }


@app.get("/evaluation/summary")
async def evaluation_summary():
    """Get evaluation summary."""
    return eval_framework.get_summary()


# ============================================================
# Phase 0: API versioning — /api/v1/ structure
# ============================================================

from fastapi import APIRouter
from sqlalchemy import text  # for health-check SELECT 1 (SQLAlchemy 2.x)

api_v1 = APIRouter(prefix="/api/v1")


@api_v1.get("/models")
async def list_models():
    """List all registered AI models."""
    return {"models": model_registry.list_models()}


@api_v1.get("/models/health")
async def models_health():
    """Check health of all AI models."""
    return model_registry.health_check()


# ── Knowledge Hub endpoints ─────────────────────────────────

@api_v1.get("/knowledge/stats")
async def knowledge_stats(project: str = "default"):
    """Get Knowledge Hub statistics."""
    return knowledge_hub.get_stats()


@api_v1.get("/knowledge/entities")
async def knowledge_entities(project: str = "default", entity_type: str = ""):
    """List entities in the Knowledge Hub."""
    from knowledge.entities import EntityType
    et = None
    if entity_type:
        try:
            et = EntityType(entity_type)
        except ValueError:
            raise HTTPException(400, f"Unknown entity type: {entity_type}")
    entities = knowledge_hub.find_entities(entity_type=et, project_id=project)
    return {
        "entities": [
            {
                "id": e.entity_id,
                "type": e.entity_type.value,
                "name": e.name,
                "project": e.project_id,
                "status": e.status,
            }
            for e in entities
        ],
        "count": len(entities),
    }


@api_v1.get("/knowledge/entities/{entity_id}")
async def knowledge_entity_detail(entity_id: str):
    """Get detailed information about an entity."""
    entity = knowledge_hub.get_entity(entity_id)
    if not entity:
        raise HTTPException(404, "Entity not found")
    return {
        "id": entity.entity_id,
        "type": entity.entity_type.value,
        "name": entity.name,
        "description": entity.description,
        "properties": entity.properties,
        "provenance": {
            "source_doc": entity.provenance.source_doc,
            "source_page": entity.provenance.source_page,
            "source_clause": entity.provenance.source_clause,
            "confidence": entity.provenance.confidence.value if hasattr(entity.provenance.confidence, 'value') else entity.provenance.confidence,
            "verified_by": entity.provenance.verified_by,
        },
        "status": entity.status,
        "version": entity.version,
    }


@api_v1.get("/knowledge/requirements")
async def knowledge_requirements(project: str = "default", discipline: str = ""):
    """List requirements in the Knowledge Hub."""
    reqs = knowledge_hub.get_requirements(project_id=project, discipline=discipline)
    return {
        "requirements": [
            {
                "id": r.entity_id,
                "name": r.name,
                "value": r.value,
                "unit": r.unit,
                "operator": r.operator,
                "discipline": r.discipline,
                "code_reference": r.code_reference,
            }
            for r in reqs
        ],
        "count": len(reqs),
    }


@api_v1.get("/knowledge/drawings")
async def knowledge_drawings(project: str = "default", discipline: str = ""):
    """List drawings in the Knowledge Hub."""
    drawings = knowledge_hub.get_drawings(project_id=project, discipline=discipline)
    return {
        "drawings": [
            {
                "id": d.entity_id,
                "name": d.name,
                "drawing_number": d.drawing_number,
                "revision": d.revision,
                "discipline": d.discipline,
            }
            for d in drawings
        ],
        "count": len(drawings),
    }


@api_v1.get("/knowledge/bim-elements")
async def knowledge_bim_elements(project: str = "default", ifc_class: str = "", level: str = ""):
    """List BIM elements in the Knowledge Hub."""
    elements = knowledge_hub.get_bim_elements(project_id=project, ifc_class=ifc_class, level=level)
    return {
        "elements": [
            {
                "id": e.entity_id,
                "name": e.name,
                "guid": e.guid,
                "ifc_class": e.ifc_class,
                "level": e.level,
            }
            for e in elements
        ],
        "count": len(elements),
    }


@api_v1.get("/knowledge/graph/{entity_id}")
async def knowledge_graph_nav(entity_id: str, relation: str = "", direction: str = "out"):
    """Navigate the knowledge graph from an entity."""
    entity = knowledge_hub.get_entity(entity_id)
    if not entity:
        raise HTTPException(404, "Entity not found")
    rels = knowledge_hub.get_relationships(entity_id, relation=relation, direction=direction)
    return {
        "entity_id": entity_id,
        "relationships": rels,
    }


# ── Phase 1: Document state management ──────────────────────

@api_v1.get("/projects/{project}/documents/state")
async def documents_state(project: str, request: Request):
    """Get all documents with their current state in the pipeline."""
    user = auth.require_project(request, project)
    docs = db.list_documents(project, user)
    return {
        "project": project,
        "documents": [
            {
                "filename": d["filename"],
                "status": d.get("status", "unknown"),
                "folder": d.get("folder"),
                "uploaded_at": d.get("uploaded_at"),
                "chunks": d.get("chunks", 0),
            }
            for d in docs
        ],
    }


@api_v1.post("/projects/{project}/documents/{filename}/verify")
async def verify_document(project: str, filename: str, request: Request):
    """Mark a document as verified (human review complete)."""
    user = auth.require_project(request, project)
    if not auth.can_manage_project(user, project):
        raise HTTPException(403, "Not permitted")
    db.update_document_status(project, filename, 0, DocumentState.VERIFIED)
    db.audit("document.verify", project=project, target=filename, user=user)
    return {"status": "verified", "filename": filename}


@api_v1.post("/projects/{project}/documents/{filename}/publish")
async def publish_document(project: str, filename: str, request: Request):
    """Publish a document — makes it available for user queries."""
    user = auth.require_project(request, project)
    if not auth.can_manage_project(user, project):
        raise HTTPException(403, "Not permitted")
    doc = next((d for d in db.list_documents(project) if d["filename"] == filename), None)
    if not doc:
        raise HTTPException(404, "Document not found")
    # Only verified documents can be published
    if doc.get("status") not in (DocumentState.VERIFIED, DocumentState.PUBLISHED, DocumentState.READY):
        raise HTTPException(400, f"Document must be verified before publishing (current: {doc.get('status')})")
    db.update_document_status(project, filename, doc.get("chunks", 0), DocumentState.PUBLISHED)
    db.audit("document.publish", project=project, target=filename, user=user)
    return {"status": "published", "filename": filename}


@api_v1.post("/projects/{project}/documents/{filename}/archive")
async def archive_document(project: str, filename: str, request: Request):
    """Archive a document — removes from active use but keeps for reference."""
    user = auth.require_project(request, project)
    if not auth.can_manage_project(user, project):
        raise HTTPException(403, "Not permitted")
    db.update_document_status(project, filename, 0, DocumentState.ARCHIVED)
    db.audit("document.archive", project=project, target=filename, user=user)
    return {"status": "archived", "filename": filename}


@api_v1.post("/projects/{project}/documents/{filename}/reject")
async def reject_document(project: str, filename: str, request: Request):
    """Reject a document — marks it as failed or invalid."""
    user = auth.require_project(request, project)
    if not auth.can_manage_project(user, project):
        raise HTTPException(403, "Not permitted")
    db.update_document_status(project, filename, 0, DocumentState.FAILED)
    db.audit("document.reject", project=project, target=filename, user=user)
    return {"status": "rejected", "filename": filename}


# ── Phase 3: Hybrid Retrieval endpoints ─────────────────────

@api_v1.get("/retrieval/stats")
async def retrieval_stats():
    """Get retrieval engine statistics."""
    return {
        "bm25_indexed_docs": len(hybrid_retriever._documents),
        "reranker_enabled": get_reranker().is_enabled(),
        "vector_stores_cached": len(vectorstores),
    }


@api_v1.post("/retrieval/search")
async def retrieval_search(request: Request, project: str = "default",
                           query: str = "", k: int = 8):
    """Search using hybrid retrieval (BM25 + Vector + RRF + Reranker)."""
    user = auth.require_project(request, project)
    if not query:
        raise HTTPException(400, "Query required")
    vs = get_vectorstore(project)
    result = hybrid_retriever.retrieve_from_faiss(query, project, k=k, user=user, vectorstore=vs)
    return {
        "query": query,
        "results": [
            {
                "source": r.source,
                "page": r.page,
                "score": r.score,
                "content_preview": r.content[:200],
            }
            for r in result.results
        ],
        "total": len(result.results),
    }


# ── Phase 4: Compliance endpoints ───────────────────────────

@api_v1.get("/compliance/rules")
async def compliance_rules():
    """List all compliance rules."""
    return {"rules": compliance_engine.list_rules()}


@api_v1.post("/compliance/check")
async def compliance_check(request: Request):
    """Run a deterministic compliance check."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    rule_id = body.get("rule_id", "")
    actual_value = body.get("actual_value")
    project_id = body.get("project", "default")
    source_doc = body.get("source_doc", "")
    source_page = body.get("source_page")
    context = body.get("context", {})

    if not rule_id:
        raise HTTPException(400, "rule_id required")

    finding = compliance_engine.evaluate(
        rule_id=rule_id,
        actual_value=actual_value,
        context=context,
        project_id=project_id,
        source_doc=source_doc,
        source_page=source_page,
    )

    # Store finding
    validation_engine._findings[finding.finding_id] = finding

    return {
        "finding_id": finding.finding_id,
        "status": finding.status.value,
        "severity": finding.severity.value,
        "title": finding.title,
        "calculation": finding.calculation,
        "actual_value": finding.actual_value,
        "expected_value": finding.expected_value,
        "difference": finding.difference,
        "recommendation": finding.recommendation,
        "confidence": finding.confidence,
    }


@api_v1.post("/compliance/check-batch")
async def compliance_check_batch(request: Request):
    """Run multiple compliance checks in batch."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    checks = body.get("checks", [])
    project_id = body.get("project", "default")

    if not checks:
        raise HTTPException(400, "checks array required")

    findings = compliance_engine.evaluate_batch(checks, project_id)

    # Store findings
    for f in findings:
        validation_engine._findings[f.finding_id] = f

    return {
        "findings": [
            {
                "finding_id": f.finding_id,
                "status": f.status.value,
                "severity": f.severity.value,
                "title": f.title,
                "calculation": f.calculation,
            }
            for f in findings
        ],
        "total": len(findings),
        "passed": sum(1 for f in findings if f.status == ComplianceStatus.PASS),
        "failed": sum(1 for f in findings if f.status == ComplianceStatus.FAIL),
        "review": sum(1 for f in findings if f.status == ComplianceStatus.REVIEW),
    }


# ── Phase 4: Validation endpoints ───────────────────────────

@api_v1.get("/qa/findings")
async def qa_findings(project: str = "default", status: str = "",
                      severity: str = "", discipline: str = ""):
    """List QA findings."""
    findings = validation_engine.list_findings(
        project_id=project, status=status, severity=severity, discipline=discipline
    )
    return {
        "findings": [
            {
                "finding_id": f.finding_id,
                "status": f.status.value,
                "severity": f.severity.value,
                "title": f.title,
                "discipline": f.discipline,
                "source_doc": f.source_doc,
                "source_page": f.source_page,
                "lifecycle_state": f.lifecycle_state,
                "ai_generated": f.ai_generated,
                "human_reviewed": f.human_reviewed,
                "created_at": f.created_at,
            }
            for f in findings
        ],
        "count": len(findings),
    }


@api_v1.get("/qa/findings/{finding_id}")
async def qa_finding_detail(finding_id: str):
    """Get detailed information about a finding."""
    finding = validation_engine.get_finding(finding_id)
    if not finding:
        raise HTTPException(404, "Finding not found")
    return {
        "finding_id": finding.finding_id,
        "status": finding.status.value,
        "severity": finding.severity.value,
        "title": finding.title,
        "description": finding.description,
        "requirement": finding.requirement,
        "actual_value": finding.actual_value,
        "expected_value": finding.expected_value,
        "difference": finding.difference,
        "calculation": finding.calculation,
        "rule_id": finding.rule_id,
        "evidence": finding.evidence,
        "source_doc": finding.source_doc,
        "source_page": finding.source_page,
        "confidence": finding.confidence,
        "recommendation": finding.recommendation,
        "lifecycle_state": finding.lifecycle_state,
        "ai_generated": finding.ai_generated,
        "human_reviewed": finding.human_reviewed,
        "verified_by": finding.verified_by,
        "comments": finding.comments,
        "created_at": finding.created_at,
        "updated_at": finding.updated_at,
    }


@api_v1.put("/qa/findings/{finding_id}/verify")
async def qa_finding_verify(finding_id: str, request: Request):
    """Verify a finding (human review)."""
    user = auth.require_user(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    comment = body.get("comment", "")
    success = validation_engine.verify_finding(finding_id, user["username"], comment)
    if not success:
        raise HTTPException(404, "Finding not found")
    db.audit("finding.verify", target=finding_id, user=user)
    return {"status": "verified", "finding_id": finding_id}


@api_v1.put("/qa/findings/{finding_id}/reject")
async def qa_finding_reject(finding_id: str, request: Request):
    """Reject a finding."""
    user = auth.require_user(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    comment = body.get("comment", "")
    success = validation_engine.reject_finding(finding_id, user["username"], comment)
    if not success:
        raise HTTPException(404, "Finding not found")
    db.audit("finding.reject", target=finding_id, user=user)
    return {"status": "rejected", "finding_id": finding_id}


@api_v1.put("/qa/findings/{finding_id}/resolve")
async def qa_finding_resolve(finding_id: str, request: Request):
    """Mark a finding as resolved."""
    user = auth.require_user(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    comment = body.get("comment", "")
    success = validation_engine.resolve_finding(finding_id, user["username"], comment)
    if not success:
        raise HTTPException(404, "Finding not found")
    db.audit("finding.resolve", target=finding_id, user=user)
    return {"status": "resolved", "finding_id": finding_id}


@api_v1.post("/qa/findings/{finding_id}/comment")
async def qa_finding_comment(finding_id: str, request: Request):
    """Add a comment to a finding."""
    user = auth.require_user(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    comment = body.get("comment", "")
    if not comment:
        raise HTTPException(400, "comment required")
    success = validation_engine.add_comment(finding_id, user["username"], comment)
    if not success:
        raise HTTPException(404, "Finding not found")
    return {"status": "comment_added", "finding_id": finding_id}


@api_v1.get("/qa/stats")
async def qa_stats(project: str = "default"):
    """Get QA finding statistics."""
    return validation_engine.get_stats(project)


# ── Phase 5: OCR endpoints ──────────────────────────────────

@api_v1.get("/ocr/status")
async def ocr_status():
    """Get OCR engine status and available backends."""
    return {
        "available": ocr_engine.is_available(),
        "backend": ocr_engine.get_backend(),
        "paddle_available": ocr_engine._paddle_available,
        "tesseract_available": ocr_engine._tesseract_available,
        "vision_available": ocr_engine._vision_available,
    }


@api_v1.post("/ocr/recognize")
async def ocr_recognize(request: Request, project: str = "default"):
    """Recognize text in an uploaded image."""
    user = auth.require_project(request, project)
    try:
        body = await request.json()
    except Exception:
        body = {}
    image_path = body.get("image_path", "")
    if not image_path or not os.path.exists(image_path):
        raise HTTPException(400, "Valid image_path required")
    result = ocr_engine.recognize(image_path, source_doc=body.get("source_doc", ""))
    return {
        "text": result.full_text,
        "confidence": result.average_confidence,
        "results": [
            {
                "text": r.text,
                "confidence": r.confidence,
                "bounding_box": r.bounding_box,
            }
            for r in result.results
        ],
    }


# ── Phase 5: Layout endpoints ───────────────────────────────

@api_v1.get("/layout/status")
async def layout_status():
    """Get layout engine status and available backends."""
    return {
        "available": layout_engine.is_available(),
        "backend": layout_engine.get_backend(),
        "pp_available": layout_engine._pp_available,
        "vision_available": layout_engine._vision_available,
    }


@api_v1.post("/layout/detect")
async def layout_detect(request: Request, project: str = "default"):
    """Detect layout in an uploaded image."""
    user = auth.require_project(request, project)
    try:
        body = await request.json()
    except Exception:
        body = {}
    image_path = body.get("image_path", "")
    if not image_path or not os.path.exists(image_path):
        raise HTTPException(400, "Valid image_path required")
    result = layout_engine.detect(image_path)
    return {
        "page": result.page_number,
        "has_table": result.has_table,
        "has_figure": result.has_figure,
        "has_image": result.has_image,
        "blocks": [
            {
                "type": b.block_type.value,
                "bounding_box": b.bounding_box,
                "content": b.content[:200],
                "confidence": b.confidence,
            }
            for b in result.blocks
        ],
    }


# ── Phase 5: Drawing Intelligence endpoints ─────────────────

@api_v1.get("/drawings/status")
async def drawings_status():
    """Get drawing intelligence engine status."""
    return {
        "ocr_available": drawing_engine.ocr_engine.is_available(),
        "layout_available": drawing_engine.layout_engine.is_available(),
        "ocr_backend": drawing_engine.ocr_engine.get_backend(),
        "layout_backend": drawing_engine.layout_engine.get_backend(),
    }


@api_v1.post("/drawings/analyze")
async def drawings_analyze(request: Request, project: str = "default"):
    """Analyze a drawing image for dimensions, elements, and layout."""
    user = auth.require_project(request, project)
    try:
        body = await request.json()
    except Exception:
        body = {}
    image_path = body.get("image_path", "")
    ocr_text = body.get("ocr_text", "")
    if not image_path or not os.path.exists(image_path):
        raise HTTPException(400, "Valid image_path required")
    result = drawing_engine.analyze_drawing(image_path, ocr_text)
    return result


@api_v1.post("/drawings/compare")
async def drawings_compare(request: Request, project: str = "default"):
    """Compare two drawing revisions."""
    user = auth.require_project(request, project)
    try:
        body = await request.json()
    except Exception:
        body = {}
    text_a = body.get("text_a", "")
    text_b = body.get("text_b", "")
    revision_a = body.get("revision_a", "A")
    revision_b = body.get("revision_b", "B")
    if not text_a or not text_b:
        raise HTTPException(400, "text_a and text_b required")
    result = drawing_engine.compare_drawings(text_a, text_b, revision_a, revision_b)
    return {
        "revision_a": result.revision_a,
        "revision_b": result.revision_b,
        "total_changes": result.total_changes,
        "summary": result.summary,
        "changes": result.changes,
    }


@api_v1.post("/drawings/extract-dimensions")
async def drawings_extract_dimensions(request: Request, project: str = "default"):
    """Extract dimensions from drawing text."""
    user = auth.require_project(request, project)
    try:
        body = await request.json()
    except Exception:
        body = {}
    text = body.get("text", "")
    if not text:
        raise HTTPException(400, "text required")
    dimensions = drawing_engine.extract_dimensions(text)
    return {
        "dimensions": [
            {
                "value": d.value,
                "unit": d.unit,
                "type": d.dimension_type,
                "text": d.text,
                "confidence": d.confidence,
            }
            for d in dimensions
        ],
        "count": len(dimensions),
    }


# ── Phase 6: Agent endpoints ────────────────────────────────

@api_v1.get("/agents")
async def list_agents():
    """List all registered agents."""
    return {"agents": agent_runtime.list_agents()}


@api_v1.get("/agents/tools")
async def list_agent_tools(permission: str = ""):
    """List all available agent tools."""
    from agents.tools import ToolPermission
    perm = None
    if permission:
        try:
            perm = ToolPermission(permission)
        except ValueError:
            raise HTTPException(400, f"Unknown permission: {permission}")
    return {"tools": tool_registry.list_tools(permission=perm)}


@api_v1.post("/agents/{agent_name}/execute")
async def execute_agent(agent_name: str, request: Request, project: str = "default"):
    """Execute an agent run."""
    user = auth.require_project(request, project)
    try:
        body = await request.json()
    except Exception:
        body = {}
    query = body.get("query", "")
    if not query:
        raise HTTPException(400, "query required")
    context = body.get("context", {})
    run = agent_runtime.execute(agent_name, query, project_id=project, user=user, context=context)
    return {
        "run_id": run.run_id,
        "agent_name": run.agent_name,
        "state": run.state.value,
        "success": run.success,
        "steps": [
            {
                "step": s.step_number,
                "action": s.action,
                "description": s.description,
                "tool_name": s.tool_name,
                "duration_ms": s.duration_ms,
            }
            for s in run.steps
        ],
        "final_response": run.final_response,
        "total_duration_ms": run.total_duration_ms,
        "error": run.error,
    }


@api_v1.get("/agents/runs")
async def list_agent_runs(project: str = "default"):
    """List agent runs."""
    runs = agent_runtime.list_runs(project_id=project)
    return {
        "runs": [
            {
                "run_id": r.run_id,
                "agent_name": r.agent_name,
                "state": r.state.value,
                "success": r.success,
                "created_at": r.created_at,
                "total_duration_ms": r.total_duration_ms,
            }
            for r in runs
        ],
    }


@api_v1.get("/agents/runs/{run_id}")
async def get_agent_run(run_id: str):
    """Get detailed information about an agent run."""
    run = agent_runtime.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return {
        "run_id": run.run_id,
        "agent_name": run.agent_name,
        "state": run.state.value,
        "success": run.success,
        "query": run.query,
        "steps": [
            {
                "step": s.step_number,
                "action": s.action,
                "description": s.description,
                "tool_name": s.tool_name,
                "tool_params": s.tool_params,
                "tool_result": {
                    "success": s.tool_result.success if s.tool_result else None,
                    "data": s.tool_result.data if s.tool_result else None,
                    "error": s.tool_result.error if s.tool_result else None,
                } if s.tool_result else None,
                "duration_ms": s.duration_ms,
                "timestamp": s.timestamp,
            }
            for s in run.steps
        ],
        "final_response": run.final_response,
        "total_duration_ms": run.total_duration_ms,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "error": run.error,
    }


# ── Phase 7: BIM endpoints ──────────────────────────────────

@api_v1.get("/bim/status")
async def bim_status():
    """Get BIM engine status."""
    return {
        "ifc_engine_available": ifc_engine.is_available(),
        "ifc_backend": ifc_engine.get_backend(),
        "models_registered": len(bim_service._models),
    }


@api_v1.post("/bim/ingest")
async def bim_ingest(request: Request, project: str = "default"):
    """
    Ingest BIM data extracted by the browser (web-ifc).
    The viewer sends typed element data to this endpoint.
    """
    user = auth.require_project(request, project)
    try:
        body = await request.json()
    except Exception:
        body = {}

    model_data = body.get("model_data", {})
    if not model_data:
        raise HTTPException(400, "model_data required")

    model_id = bim_service.ingest_from_browser(model_data, project_id=project)
    db.audit("bim.ingest", project=project, detail={"model_id": model_id}, user=user)
    return {"status": "ingested", "model_id": model_id}


@api_v1.get("/bim/models")
async def bim_models(project: str = "default"):
    """List all registered BIM models."""
    return {"models": bim_service.list_models(project_id=project)}


@api_v1.get("/bim/elements")
async def bim_elements(project: str = "default", ifc_class: str = "",
                        level: str = "", guid: str = ""):
    """Query BIM elements."""
    elements = bim_service.query_elements(
        project_id=project, ifc_class=ifc_class, level=level, guid=guid
    )
    return {"elements": elements, "count": len(elements)}


@api_v1.get("/bim/elements/{guid}")
async def bim_element_detail(guid: str, project: str = "default"):
    """Get a single BIM element by GUID."""
    element = bim_service.get_element_by_guid(guid, project_id=project)
    if not element:
        raise HTTPException(404, "Element not found")
    return element


@api_v1.get("/bim/stats")
async def bim_stats(project: str = "default"):
    """Get BIM statistics."""
    return bim_service.get_stats(project_id=project)


# ── Phase 8: Report endpoints ───────────────────────────────

@api_v1.post("/reports/generate")
async def reports_generate(request: Request, project: str = "default"):
    """Generate a report."""
    user = auth.require_project(request, project)
    try:
        body = await request.json()
    except Exception:
        body = {}

    report_type = body.get("report_type", "compliance")
    format = body.get("format", "pdf")
    discipline = body.get("discipline", "")

    # Gather data based on report type
    if report_type == "compliance":
        findings = list(validation_engine._findings.values())
        findings = [f.__dict__ if hasattr(f, '__dict__') else f for f in findings]
        report = report_engine.generate_compliance_report(
            project_id=project,
            findings=findings,
            discipline=discipline,
            created_by=user["username"],
        )
    elif report_type == "bim_qa":
        bim_stats = bim_service.get_stats(project_id=project)
        findings = list(validation_engine._findings.values())
        findings = [f.__dict__ if hasattr(f, '__dict__') else f for f in findings]
        report = report_engine.generate_bim_qa_report(
            project_id=project,
            bim_stats=bim_stats,
            findings=findings,
            created_by=user["username"],
        )
    elif report_type == "issue_register":
        findings = list(validation_engine._findings.values())
        findings = [f.__dict__ if hasattr(f, '__dict__') else f for f in findings]
        report = report_engine.generate_issue_register(
            project_id=project,
            findings=findings,
            created_by=user["username"],
        )
    else:
        raise HTTPException(400, f"Unknown report type: {report_type}")

    # Export to file
    output_dir = os.path.join(DATA_DIR, "reports", project)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{report.report_id}.{format}")

    try:
        report_engine.export(report, output_path, format)
    except Exception as e:
        raise HTTPException(500, f"Report generation failed: {str(e)}")

    db.audit("report.generate", project=project,
             detail={"report_type": report_type, "format": format, "report_id": report.report_id},
             user=user)

    return {
        "status": "generated",
        "report_id": report.report_id,
        "report_type": report_type,
        "format": format,
        "file_path": output_path,
        "download_url": f"/api/v1/reports/{report.report_id}/download",
    }


@api_v1.get("/reports/{report_id}/download")
async def reports_download(report_id: str, request: Request):
    """Download a generated report."""
    user = auth.require_user(request)
    # Find the report file
    reports_dir = os.path.join(DATA_DIR, "reports")
    for root, dirs, files in os.walk(reports_dir):
        for f in files:
            if report_id in f:
                file_path = os.path.join(root, f)
                return FileResponse(file_path, filename=f)
    raise HTTPException(404, "Report not found")


@api_v1.get("/reports/list")
async def reports_list(project: str = "default"):
    """List all generated reports for a project."""
    reports_dir = os.path.join(DATA_DIR, "reports", project)
    if not os.path.exists(reports_dir):
        return {"reports": []}
    reports = []
    for f in os.listdir(reports_dir):
        file_path = os.path.join(reports_dir, f)
        reports.append({
            "filename": f,
            "size": os.path.getsize(file_path),
            "created": datetime.datetime.fromtimestamp(os.path.getctime(file_path)).isoformat(),
        })
    return {"reports": reports}


# ── Phase 8: Dashboard endpoints ────────────────────────────

@api_v1.get("/dashboard/stats")
async def dashboard_stats(project: str = "default"):
    """Get dashboard statistics for a project."""
    # Document stats
    docs = db.list_documents(project)
    total_docs = len(docs)
    processed_docs = sum(1 for d in docs if d.get("status") in ("ready", "published", "verified"))

    # Finding stats
    finding_stats = validation_engine.get_stats(project)

    # BIM stats
    bim_stats_data = bim_service.get_stats(project_id=project)

    # Knowledge Hub stats
    hub_stats = knowledge_hub.get_stats()

    return {
        "project": project,
        "documents": {
            "total": total_docs,
            "processed": processed_docs,
            "pending": total_docs - processed_docs,
        },
        "findings": finding_stats,
        "bim": bim_stats_data,
        "knowledge_hub": hub_stats,
    }


# ── V2 UI: Schedules / Quantities read endpoint ─────────────
# Additive, read-only. Surfaces the structured rows (ScheduleRow) and numeric
# quantities (Quantity) that ingestion already writes, so the Schedules workspace
# can show a real data table with source/page/revision. No schema change.
@api_v1.get("/projects/{project}/schedules")
async def project_schedules(project: str, request: Request):
    """List structured schedule rows and quantities for a project."""
    user = auth.require_project(request, project)
    rows_out, qty_out = [], []
    s = db.SessionLocal()
    try:
        proj = s.query(db.Project).filter_by(name=project).first()
        if proj:
            for r in s.query(db.ScheduleRow).filter(db.ScheduleRow.project_id == proj.id).all():
                rows_out.append({
                    "id": r.id,
                    "table_name": r.table_name or "",
                    "row_key": r.row_key or "",
                    "row_values": r.row_values or {},
                    "doc": r.doc or "",
                    "page": r.page,
                    "revision": r.revision or "",
                })
            for q in s.query(db.Quantity).filter(db.Quantity.project_id == proj.id).all():
                qty_out.append({
                    "id": q.id,
                    "building": q.building or "",
                    "metric": q.metric or "",
                    "value": q.value or "",
                    "unit": q.unit or "",
                    "source_doc": q.source_doc or "",
                    "source_page": q.source_page,
                    "revision": q.revision or "",
                })
    finally:
        s.close()
    return {
        "project": project,
        "rows": rows_out,
        "quantities": qty_out,
        "row_count": len(rows_out),
        "quantity_count": len(qty_out),
    }


app.include_router(api_v1)

vectorstores = {}
embedder = local_embed.LocalOllamaEmbeddings(model="bge-m3")
# Chat/reasoning uses the same vision-language model as drawings (qwen2.5vl:32b),
# so only ONE large model is ever loaded -- important on a 16GB GPU.
llm = ChatOllama(model="qwen2.5vl:32b", temperature=0.1, keep_alive="5m")

def get_vectorstore(project: str):
    if project in vectorstores: return vectorstores[project]
    proj_idx = os.path.join(INDEX_DIR, project)
    if os.path.isdir(proj_idx) and os.path.exists(os.path.join(proj_idx, "index.faiss")):
        try:
            vs = FAISS.load_local(proj_idx, embedder, allow_dangerous_deserialization=True)
            vectorstores[project] = vs
            return vs
        except Exception as _e:
            logger.exception("get_vectorstore LOAD FAILED for {}: {}", project, _e)
            pass
    else:
        logger.warning("get_vectorstore: no index for {} at {}", project, proj_idx)
    return None

def save_vectorstore(project: str):
    if project in vectorstores:
        try: vectorstores[project].save_local(os.path.join(INDEX_DIR, project))
        except Exception as e: logger.error("index save failed: {}", e)

class Message(BaseModel):
    role: str
    content: str

class QueryRequest(BaseModel):
    query: str
    project: str = "default"
    messages: List[Message] = []
    k: int = 3
    model: str = "qwen2.5vl:32b"
    mode: str = "chat"
    discipline: str = ""
    focus_doc: str = ""
    attachment_id: Optional[int] = None  # a private chat attachment (see /chat/attachments)

class QueryResponse(BaseModel):
    answer: str
    sources: List[str]

class ModelQueryReq(BaseModel):
    """Question about a 3D/BIM model. The viewer parses the IFC in the browser
    (web-ifc) and sends a compact, already-extracted MODEL DATA summary as `context`.
    No RAG / no document retrieval is used here -- the answer is grounded ONLY in the
    model data the viewer supplies."""
    query: str
    project: str = "default"
    context: str = ""          # model summary built by the viewer
    selection: str = ""        # properties of the currently-selected element (optional)
    messages: List[Message] = []
    model: str = "qwen2.5vl:32b"

class ProjectSave(BaseModel):
    project: str
    chat_id: str
    title: str
    messages: list

class LoginReq(BaseModel):
    username: str
    password: str


# Phase 0: Simple in-memory rate limiter for login
_login_attempts = {}
_LOGIN_RATE_LIMIT = 10  # attempts
_LOGIN_RATE_WINDOW = 300  # seconds (5 minutes)


def _check_rate_limit(ip: str) -> bool:
    """Check if IP has exceeded login rate limit. Returns True if allowed."""
    now = time.time()
    attempts = _login_attempts.get(ip, [])
    # Remove old attempts
    attempts = [t for t in attempts if now - t < _LOGIN_RATE_WINDOW]
    _login_attempts[ip] = attempts
    if len(attempts) >= _LOGIN_RATE_LIMIT:
        return False
    attempts.append(now)
    return True

class CreateUserReq(BaseModel):
    username: str
    password: str
    role: str = "user"
    full_name: str = ""
    email: str = ""

class PasswordReq(BaseModel):
    password: str

class RoleReq(BaseModel):
    role: str

class ActiveReq(BaseModel):
    active: bool

class ChangePwReq(BaseModel):
    old_password: str
    new_password: str

class CreateProjectReq(BaseModel):
    name: str
    discipline: Optional[str] = None

class MemberReq(BaseModel):
    username: str

def safe_project_name(project: str) -> str:
    name = re.sub(r'[^A-Za-z0-9._ -]', '_', project or "default").strip()
    return name or "default"

def project_workspace(project: str) -> str:
    # One sandboxed workspace folder per project; all cowork file ops stay inside it.
    root = os.path.abspath(os.path.join(WORKSPACE_DIR, safe_project_name(project)))
    os.makedirs(root, exist_ok=True)
    return root

def resolve_in_workspace(project: str, path: str) -> str:
    # Resolve an LLM-supplied path INSIDE the project workspace. Absolute paths,
    # drive letters and .. traversal that escape the sandbox are rejected.
    root = project_workspace(project)
    p = (path or "").strip().replace(chr(92), "/")
    p = re.sub(r'^[A-Za-z]:', '', p).lstrip("/")
    candidate = os.path.abspath(os.path.join(root, p))
    if candidate != root and not candidate.startswith(root + os.sep):
        raise ValueError("path escapes the project workspace sandbox")
    return candidate

def load_document(path):
    ext = os.path.splitext(path)[-1].lower()
    if ext == ".pdf": return PyPDFLoader(path).load()
    if ext == ".docx": return Docx2txtLoader(path).load()
    if ext in (".xlsx",".xls"): return UnstructuredExcelLoader(path).load()
    raise HTTPException(400, f"Unsupported: {ext}")

def index_document(collection, path):
    docs = load_document(path)
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=80)
    chunks = splitter.split_documents(docs)
    vs = get_vectorstore(collection)
    if vs is None:
        vs = FAISS.from_documents(chunks, embedder)
        vectorstores[collection] = vs
    else:
        vs.add_documents(chunks)
    save_vectorstore(collection)
    return len(chunks)

def index_text(collection, text, source, folder_id=None):
    from langchain_core.documents import Document as LCDocument
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=80)
    chunks = splitter.split_documents([LCDocument(page_content=text, metadata={"source": source, "folder_id": folder_id})])
    vs = get_vectorstore(collection)
    if vs is None:
        vs = FAISS.from_documents(chunks, embedder)
        vectorstores[collection] = vs
    else:
        vs.add_documents(chunks)
    save_vectorstore(collection)
    return len(chunks)

def _units_from_meta(meta):
    """Break a document's structured extraction into (text, page_label) units so
    each indexed chunk can be tagged with the exact page / sheet / view it came
    from. page_label is an int page for PDFs, a sheet/view name otherwise, or None."""
    units = []
    t = meta.get("type")
    if meta.get("pages"):  # PDF
        for pg in meta["pages"]:
            body = (pg.get("text") or "")
            tbl = (pg.get("tables") or "")
            if tbl:
                body = (body + "\n\n[TABLES]\n" + tbl).strip()
            vis = (pg.get("vision") or "")
            if vis:
                body = (body + "\n[DRAWING/VISION]\n" + vis).strip()
            if body.strip():
                units.append((body, pg.get("page")))
    elif meta.get("sheets"):  # excel
        for sh in meta["sheets"]:
            rows = sh.get("rows") or []
            body = "\n".join(" | ".join(str(c) for c in r) for r in rows)
            if body.strip():
                units.append((body, sh.get("sheet")))
    elif meta.get("views") or meta.get("data"):  # cad
        if meta.get("data"):
            units.append((meta["data"], "data"))
        for v in (meta.get("views") or []):
            vis = v.get("vision") or ""
            if vis.strip():
                units.append((vis, v.get("image")))
    elif t == "docx":
        body = "\n".join(meta.get("paragraphs") or [])
        if body.strip():
            units.append((body, None))
        for i, tbl in enumerate(meta.get("tables") or []):
            tb = "\n".join(" | ".join(str(c) for c in r) for r in tbl)
            if tb.strip():
                units.append((tb, "table %d" % (i + 1)))
    elif t == "image":
        vis = meta.get("vision") or ""
        if vis.strip():
            units.append((vis, None))
    return units

def index_structured(collection, meta, source, folder_id=None):
    """Page-aware indexing: every chunk carries {source, page} metadata so answers
    and citations can point to the exact page. Falls back to nothing if meta has
    no usable units (caller then uses index_text)."""
    from langchain_core.documents import Document as LCDocument
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=80)
    all_chunks = []
    for body, page in _units_from_meta(meta):
        md = {"source": source, "folder_id": folder_id}
        if page is not None:
            md["page"] = page
        all_chunks += splitter.split_documents([LCDocument(page_content=body, metadata=md)])
    if not all_chunks:
        return 0
    vs = get_vectorstore(collection)
    if vs is None:
        vs = FAISS.from_documents(all_chunks, embedder)
        vectorstores[collection] = vs
    else:
        vs.add_documents(all_chunks)
    save_vectorstore(collection)
    return len(all_chunks)

_bm25_cache = {}

def _get_bm25(project, vs):
    """Build (and cache per vectorstore instance) a BM25 keyword index over the
    project's FAISS chunks. Rebuilt automatically when the vectorstore is replaced
    (re-index/re-extract swap the object)."""
    try:
        key = id(vs)
        cached = _bm25_cache.get(project)
        if cached and cached[0] == key:
            return cached[1]
        ds = getattr(vs, "docstore", None)
        docs = list(ds._dict.values()) if ds is not None and hasattr(ds, "_dict") else []
        if not docs:
            return None
        from intelligence.retrieval import BM25Index
        idx = BM25Index()
        idx.add_documents([{"content": d.page_content, "metadata": getattr(d, "metadata", {}) or {},
                            "_doc": d} for d in docs])
        _bm25_cache[project] = (key, idx)
        logger.info("BM25 index built for {} ({} chunks)", project, len(docs))
        return idx
    except Exception as e:
        logger.warning("BM25 build failed for {}: {}", project, e)
        return None

def _rrf_merge(vec_docs, bm_docs, limit, rrf_k=60):
    """Reciprocal-rank-fuse two ranked Document lists into one (keyword + vector)."""
    def _k(d):
        m = getattr(d, "metadata", {}) or {}
        return (m.get("source"), m.get("page"), (d.page_content or "")[:120])
    fused, order = {}, {}
    for rank, d in enumerate(vec_docs):
        kk = _k(d); fused[kk] = fused.get(kk, 0.0) + 1.0 / (rrf_k + rank + 1); order.setdefault(kk, d)
    for rank, d in enumerate(bm_docs):
        kk = _k(d); fused[kk] = fused.get(kk, 0.0) + 1.0 / (rrf_k + rank + 1); order.setdefault(kk, d)
    ranked = sorted(fused.items(), key=lambda x: -x[1])
    return [order[kk] for kk, _ in ranked[:limit]]


def retrieve_context(project: str, query: str, k: int, user=None):
    """Retrieve grounded context. Folder permissions are ENFORCED here: a chunk is
    only included if the user may access the folder its source document lives in.
    allow_all (admin, or lead who is a member) sees everything; a regular member
    sees ONLY chunks from folders assigned to them; anyone else sees nothing.

    Phase 3: Now uses hybrid retrieval (BM25 + Vector + RRF + Reranker) when available.
    Phase 2: Adds confidence gate for honest "not found" responses.
    """
    srcs, parts = [], []
    # Resolve the user's folder access up front.
    if user is None:
        allow_all, allowed_ids = True, None
    else:
        allow_all, allowed_ids = db.folder_access(user, project)
    fmap = None  # filename -> folder_id (fallback for chunks lacking folder_id metadata)

    def _chunk_folder(d):
        fid = d.metadata.get("folder_id")
        if fid is None:
            nonlocal fmap
            if fmap is None:
                try:
                    fmap = db.doc_folder_map(project)
                except Exception:
                    fmap = {}
            fid = fmap.get(d.metadata.get("source"))
        return fid

    def _permitted(d):
        if allow_all:
            return True
        fid = _chunk_folder(d)
        return fid is not None and fid in (allowed_ids or set())

    vs = get_vectorstore(project)
    # If a restricted user has no accessible folders, skip project docs entirely.
    if vs is not None and (allow_all or allowed_ids):
        # Wave 1: Configurable rerank candidates and keep count
        from intelligence.reranker import get_reranker
        reranker = get_reranker()

        # Get rerank configuration
        try:
            from config import get_settings
            s = get_settings()
            rerank_candidates = s.rerank_candidates
            rerank_keep = s.rerank_keep
        except Exception:
            rerank_candidates = 20
            rerank_keep = 5

        # Over-fetch, then filter by folder permission
        # Wave 2 (safe, flag-gated): expand short/coded queries via the worker model.
        search_query = query
        try:
            from config import get_settings as _gs_qe
            if _gs_qe().enable_query_expansion:
                import local_chat as _lc_qe
                _exp = _lc_qe.worker_complete(
                    "You expand construction-review search queries. Given a question, "
                    "output 3-8 extra search keywords or likely legend/schedule terms, "
                    "comma-separated, no sentences.", query, num_predict=96)
                if _exp:
                    search_query = query + " " + _exp.replace(chr(10), " ")
        except Exception:
            search_query = query
        cand = vs.similarity_search(search_query, k=max(rerank_candidates, k))
        # Hybrid retrieval: fuse BM25 keyword hits with the vector hits (RRF), so
        # exact terms (drawing numbers, codes, legends like "TOS Tower 3") rank well.
        try:
            from config import get_settings as _gs_hy
            if _gs_hy().enable_hybrid_bm25:
                _bm = _get_bm25(project, vs)
                if _bm is not None:
                    _kk = max(rerank_candidates, k)
                    _hits = _bm.search(search_query, k=_kk)
                    _bm_docs = [_bm.documents[i]["_doc"] for i, _ in _hits
                                if i < len(_bm.documents) and isinstance(_bm.documents[i], dict)]
                    if _bm_docs:
                        cand = _rrf_merge(cand, _bm_docs, limit=_kk)
        except Exception as _he:
            logger.warning("hybrid BM25 fusion skipped: {}", _he)
        permitted = [d for d in cand if _permitted(d)]

        # Wave 1.5 (Task D): Metadata pre-filter — restrict candidates BEFORE ranking
        # Only active when enable_metadata_prefilter=True (default: False)
        # Auto-widens if too few candidates match (never filters the answer away)
        try:
            from config import get_settings as _gs_pf
            if _gs_pf().enable_metadata_prefilter:
                # Extract discipline/doctype/drawing-no from query
                import re as _re_pf
                _q_lower = query.lower()
                # Discipline detection
                _disc = None
                for _d in ["architect", "structural", "mep", "landscape", "bim", "cost"]:
                    if _d in _q_lower:
                        _disc = _d
                        break
                # Document type detection
                _doctype = None
                for _dt in ["drawing", "schedule", "report", "spec", "calculation"]:
                    if _dt in _q_lower:
                        _doctype = _dt
                        break
                # Drawing number detection (e.g., C3085-RPT-3EH6105-AR-0000002)
                _drawing_no = None
                _dn_match = _re_pf.search(r'C\d{4}-[A-Z]{2,4}-[A-Z0-9-]+', query, _re_pf.IGNORECASE)
                if _dn_match:
                    _drawing_no = _dn_match.group(0).upper()

                # DBC Part filtering — map discipline to DBC parts
                _dbc_parts = None
                try:
                    from disciplines import DISCIPLINE_TO_DBC_PART
                    if _disc and _disc in DISCIPLINE_TO_DBC_PART:
                        _dbc_parts = DISCIPLINE_TO_DBC_PART[_disc]
                except Exception:
                    pass

                # Apply pre-filter
                _filtered = permitted
                if _disc:
                    _filtered = [d for d in _filtered
                                 if d.metadata.get("discipline", "").lower() == _disc
                                 or _disc in d.metadata.get("source", "").lower()]
                if _doctype:
                    _filtered = [d for d in _filtered
                                 if d.metadata.get("doctype", "").lower() == _doctype
                                 or _doctype in d.metadata.get("source", "").lower()]
                if _drawing_no:
                    _filtered = [d for d in _filtered
                                 if _drawing_no.lower() in d.metadata.get("source", "").lower()]
                if _dbc_parts:
                    _filtered = [d for d in _filtered
                                 if d.metadata.get("dbc_part", "") in _dbc_parts]

                # Auto-widen: if too few candidates, use original permitted list
                if len(_filtered) >= max(k, 3):
                    permitted = _filtered
                    logger.info("Metadata pre-filter: {} candidates (disc={}, doctype={}, drawing={}, dbc_parts={})",
                                len(permitted), _disc, _doctype, _drawing_no, _dbc_parts)
                else:
                    logger.info("Metadata pre-filter: too few matches ({}), using original {}",
                                len(_filtered), len(permitted))
        except Exception:
            pass  # Pre-filter is optional, never break retrieval

        # Rerank if enabled
        top_score = None
        if reranker.is_enabled() and permitted:
            docs_for_rerank = [{"content": d.page_content, "metadata": d.metadata} for d in permitted]
            reranked = reranker.rerank_with_fallback(query, docs_for_rerank, top_k=rerank_keep)
            # top_score is the BEST relevance score. reranked is sorted descending,
            # so the top score is the first entry's. (Previously this was set inside
            # the map-back loop and ended up holding the LAST/lowest kept score, which
            # made the confidence gate below compare the wrong value.)
            if reranked and reranked[0].get("rerank_score") is not None:
                top_score = reranked[0]["rerank_score"]
            # Map back to document objects
            docs = []
            for r in reranked:
                for d in permitted:
                    if d.page_content == r.get("content"):
                        docs.append(d)
                        break
            # If reranking returned fewer than k, fill from permitted
            if len(docs) < k:
                existing = set(d.page_content for d in docs)
                for d in permitted:
                    if d.page_content not in existing:
                        docs.append(d)
                        existing.add(d.page_content)
                        if len(docs) >= k:
                            break
        else:
            docs = permitted[:k]

        # Phase 2 (Task 3): Confidence gate — check if top score indicates "not found"
        try:
            from config import get_settings as _gs_cg
            _nf_thresh = _gs_cg().not_found_threshold
            if top_score is not None and _nf_thresh > 0 and top_score < _nf_thresh:
                logger.info("Confidence gate: top score {:.4f} below threshold {:.4f} — dropping weak project-vector docs",
                            top_score, _nf_thresh)
                # Drop only the weak project-vector docs. Do NOT early-return: the
                # structured-data read (schedules/quantities) and the code-KB block
                # below can still answer this query. If everything ends up empty, the
                # assembled context is "" and the answer builder handles "not found".
                docs = []
        except Exception:
            pass

        # Phase 2 (Task 1): Read structured rows/quantities — inject as HIGH-PRIORITY context
        try:
            from config import get_settings as _gs_read
            _enable_tables = _gs_read().enable_structured_tables
            _enable_quantities = _gs_read().enable_quantities_store

            if _enable_tables or _enable_quantities:
                import re as _re_read
                _q_lower = query.lower()

                # Derive lookup key from query
                _lookup_key = None
                # Check for TOS/TOPR + Tower pattern
                _tos_match = _re_read.search(r'(TOS|TOPR)\s*(?:level\s*)?(?:for\s*)?(?:tower\s*)?(\d+)', query, _re_read.IGNORECASE)
                if _tos_match:
                    _metric = _tos_match.group(1).upper()
                    _tower = _tos_match.group(2)
                    _lookup_key = f"{_metric} Tower {_tower}"
                else:
                    # Check for legend code pattern (e.g., LX-PT)
                    _legend_match = _re_read.search(r'\b([A-Z]{1,3}-[A-Z]{1,3})\b', query)
                    if _legend_match:
                        _lookup_key = _legend_match.group(1)

                if _lookup_key:
                    # Query structured stores
                    _structured_context = ""
                    _structured_src = None

                    # Check schedule_rows and quantities using ONE session
                    _session = db.SessionLocal()
                    try:
                        _proj = _session.query(db.Project).filter_by(name=project).first()
                        if _proj:
                            # Check schedule_rows
                            if _enable_tables:
                                _rows = _session.query(db.ScheduleRow).filter(
                                    db.ScheduleRow.project_id == _proj.id,
                                    db.ScheduleRow.row_key.ilike(f"%{_lookup_key}%")
                                ).all()

                                for _row in _rows:
                                    _row_data = _row.row_values if hasattr(_row, 'row_values') else {}
                                    _structured_context += f"\n[STRUCTURED ROW: {_row.table_name}]\n"
                                    _structured_context += f"Row Key: {_row.row_key}\n"
                                    for _k, _v in _row_data.items():
                                        _structured_context += f"  {_k}: {_v}\n"
                                    _structured_src = {
                                        "source": _row.doc,
                                        "page": _row.page,
                                        "revision": _row.revision,
                                    }

                            # Check quantities
                            if _enable_quantities and not _structured_context:
                                _metric = None
                                if "tos" in _q_lower:
                                    _metric = "TOS"
                                elif "topr" in _q_lower:
                                    _metric = "TOPR"
                                elif "gfa" in _q_lower or "area" in _q_lower:
                                    _metric = "GFA"

                                if _metric:
                                    _building = None
                                    _tower_match = _re_read.search(r'tower\s*(\d+)', query, _re_read.IGNORECASE)
                                    if _tower_match:
                                        _building = f"Tower {_tower_match.group(1)}"

                                    _q_filter = db.Quantity.project_id == _proj.id
                                    if _metric:
                                        _q_filter = _q_filter & (db.Quantity.metric == _metric)
                                    if _building:
                                        _q_filter = _q_filter & (db.Quantity.building == _building)

                                    _quantities = _session.query(db.Quantity).filter(_q_filter).all()
                                    for _q in _quantities:
                                        _structured_context += f"\n[QUANTITY: {_q.metric}]\n"
                                        _structured_context += f"  Building: {_q.building}\n"
                                        _structured_context += f"  Value: {_q.value} {_q.unit}\n"
                                        _structured_src = {
                                            "source": _q.source_doc,
                                            "page": _q.source_page,
                                            "revision": _q.revision,
                                        }
                    finally:
                        _session.close()

                    # Inject structured context as HIGH-PRIORITY block
                    if _structured_context:
                        parts.insert(0, "STRUCTURED DATA (from schedules/quantities):\n" + _structured_context)
                        if _structured_src:
                            srcs.insert(0, _structured_src)
                        logger.info("Injected structured data for lookup: {}", _lookup_key)

                # General table lookup: match query terms against any captured table
                # row (area / parking / lift / unit-mix, etc.), not just TOS/TOPR.
                if _enable_tables and not _lookup_key:
                    try:
                        _sess2 = db.SessionLocal()
                        try:
                            _proj2 = _sess2.query(db.Project).filter_by(name=project).first()
                            _toks = [w for w in _re_read.findall(r'[a-z0-9]+', _q_lower) if len(w) >= 3]
                            if _proj2 and _toks:
                                _allrows = _sess2.query(db.ScheduleRow).filter(
                                    db.ScheduleRow.project_id == _proj2.id).all()
                                _scored = []
                                for _r in _allrows:
                                    _rk = (_r.row_key or "").lower()
                                    _tn = (_r.table_name or "").lower()
                                    if not _rk:
                                        continue
                                    _rk_in_q = _rk in _q_lower
                                    _rk_word_hit = any(w in _q_lower for w in _rk.split() if len(w) >= 3)
                                    if not (_rk_in_q or _rk_word_hit):
                                        continue
                                    _sc = (3 if _rk_in_q else 1) + sum(1 for t in _toks if t in _tn)
                                    _scored.append((_sc, _r))
                                _scored.sort(key=lambda x: x[0], reverse=True)
                                _gblocks, _gsrc = [], None
                                for _sc, _r in _scored[:15]:
                                    _rv = _r.row_values or {}
                                    _b = "[STRUCTURED ROW: %s]\nRow Key: %s\n" % (_r.table_name, _r.row_key)
                                    for _k, _v in _rv.items():
                                        _b += "  %s: %s\n" % (_k, _v)
                                    _gblocks.append(_b)
                                    if _gsrc is None:
                                        _gsrc = {"source": _r.doc, "page": _r.page, "revision": _r.revision}
                                if _gblocks:
                                    parts.insert(0, "STRUCTURED DATA (exact table rows matching the question - prefer these for numbers):\n" + "\n".join(_gblocks))
                                    if _gsrc:
                                        srcs.insert(0, _gsrc)
                                    logger.info("Injected {} general structured rows", len(_gblocks))
                        finally:
                            _sess2.close()
                    except Exception as _ge:
                        logger.warning("general structured lookup failed: {}", _ge)
        except Exception as _e_read:
            logger.warning("Structured data read failed: {}", _e_read)

        if docs:
            blocks = []
            for d in docs:
                src = d.metadata.get("source", "?")
                pg = d.metadata.get("page")
                tag = "[SOURCE: %s%s]" % (src, (" | PAGE %s" % pg) if pg is not None else "")
                blocks.append("%s\n%s" % (tag, d.page_content))
                srcs.append({"source": src, "page": pg})
            parts.append("PROJECT DOCUMENTS (uploaded to this project):\n" +
                         "\n\n---\n\n".join(blocks))
    kb = get_vectorstore(KB_COLLECTION)
    if kb is not None:
        cdocs = kb.similarity_search(query, k=k)
        if cdocs:
            # Grounding fix: tag each code excerpt with [SOURCE | PAGE] like project docs,
            # so the model can cite the real page instead of inventing a section/page.
            _kb_blocks = []
            for d in cdocs:
                _src = d.metadata.get("source", "?")
                _pg = d.metadata.get("page")
                _tag = "[SOURCE: %s%s]" % (_src, (" | PAGE %s" % _pg) if _pg is not None else "")
                _kb_blocks.append("%s\n%s" % (_tag, d.page_content))
            parts.append("CODE CONTEXT (DBC 2021 / IBC 2021 excerpts):\n" +
                         "\n\n---\n\n".join(_kb_blocks))
            srcs += [{"source": d.metadata.get("source","?"), "page": d.metadata.get("page")} for d in cdocs]
    note = revision_notice(project, user)
    if note:
        parts.insert(0, note)
    ctx = "\n\n====\n\n".join(parts)
    # de-duplicate (source, page) pairs, preserving order
    seen, uniq = set(), []
    for it in srcs:
        key = (it.get("source"), it.get("page"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)
    return uniq, ctx

def revision_notice(project, user=None):
    """Build a context warning when multiple revisions of the same drawing are
    in the project, so the model never silently quotes a superseded revision.
    Only considers documents the user is allowed to see."""
    try:
        docs = db.list_documents(project, user)
    except Exception:
        return ""
    groups = meta_parse.group_revisions(docs)
    multi = [(b, g) for b, g in groups.items() if g.get("multi")]
    if not multi:
        return ""
    lines = ["REVISION STATUS (multiple revisions exist for some drawings in this project):"]
    for base, g in multi:
        by_rev = {it["revision"]: it["filename"] for it in g["items"] if it.get("revision")}
        latest = g["latest"]
        ordered = sorted(g["revisions"], key=meta_parse._rev_sort_key)
        older = [r for r in ordered if r != latest]
        lines.append("- Drawing %s: revisions present %s. LATEST = %s (%s). Superseded: %s." % (
            base, ", ".join(ordered), latest, by_rev.get(latest, "?"),
            ", ".join(older) if older else "none"))
    lines.append("Use the LATEST revision unless the user asks about a specific earlier revision, "
                 "and always state which revision your answer is based on.")
    return "\n".join(lines)


def resolve_sources(project, items):
    """Map (source, page) items to {filename, rel, previewable, exists, revision,
    page} so the UI can show which file+page an answer came from and open it there.
    Accepts either dicts {"source","page"} or bare filename strings."""
    base = os.path.abspath(os.path.join(DOCS_DIR, project))
    docs = {d["filename"]: d for d in db.list_documents(project)}
    prev_exts = ("pdf","png","jpg","jpeg","webp","gif","bmp","xlsx","xls","csv","docx","doc","txt","dwg","dxf")
    out, seen = [], set()
    for it in items:
        if isinstance(it, dict):
            fn = it.get("source", "?"); page = it.get("page")
        else:
            fn = it; page = None
        key = (fn, page)
        if key in seen:
            continue
        seen.add(key)
        rel, exists = fn, False
        d = docs.get(fn)
        if d and d.get("path"):
            exists = True
            try:
                r = os.path.relpath(d["path"], base)
                if not r.startswith(".."):
                    rel = r
            except Exception:
                pass
        ext = (fn.rsplit(".", 1)[-1] if "." in fn else "").lower()
        dm = meta_parse.parse_drawing_meta(fn)
        out.append({"filename": fn, "rel": rel.replace(os.sep, "/"),
                    "previewable": ext in prev_exts, "exists": exists,
                    "revision": dm.get("revision"), "doctype": dm.get("doctype"),
                    "page": page})
    return out

PROGRESS = {}

def _pkey(project, filename):
    return project + "||" + filename

# ============================================================
# IFC pipeline diagnostics -- a structured, appendable record of what happens to
# every uploaded IFC (received -> convert -> ok/failed/skipped). Lets you (and
# me) see exactly what went right or wrong on the real machine. Stored as JSON
# lines under data/diagnostics/ (gitignored), readable via /diagnostics/ifc.
# ============================================================
_IFC_DIAG_LOCK = threading.Lock()
IFC_DIAG_PATH = os.path.join(DATA_DIR, "diagnostics", "ifc_pipeline.jsonl")
IFC_DIAG_MAX_LINES = 2000  # keep the file bounded (ring-trim on write)

def record_ifc_event(project, filename, stage, status, **details):
    """Append one structured diagnostics line for the IFC upload/convert
    pipeline, and echo it to the normal logger. Best-effort; never raises."""
    try:
        evt = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "project": project,
               "file": filename, "stage": stage, "status": status}
        for k, v in details.items():
            # keep values small/serializable
            if isinstance(v, str) and len(v) > 1000:
                v = v[:1000] + "…"
            evt[k] = v
        line = json.dumps(evt, ensure_ascii=False)
        os.makedirs(os.path.dirname(IFC_DIAG_PATH), exist_ok=True)
        with _IFC_DIAG_LOCK:
            with open(IFC_DIAG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            # Trim if it has grown past the cap (cheap, infrequent).
            try:
                with open(IFC_DIAG_PATH, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                if len(lines) > IFC_DIAG_MAX_LINES:
                    with open(IFC_DIAG_PATH, "w", encoding="utf-8") as f:
                        f.writelines(lines[-IFC_DIAG_MAX_LINES:])
            except Exception:
                pass
        logger.info("[ifc-diag] " + line)
    except Exception:
        pass

def convert_ifc_to_fragments(project, save_path, filename):
    """Best-effort: convert an uploaded .ifc to a lightweight Fragments (.frag)
    sibling via the Node converter in tools/fragments/. Runs in a background
    task. NEVER raises -- any failure (disabled, Node or deps missing, timeout,
    converter error) is logged + recorded in the IFC diagnostics, and the
    original .ifc is kept so the viewer falls back to parsing it directly.
    Produces <save_path>.frag on success. See tools/fragments/README.md."""
    import subprocess
    if os.getenv("EXPO_FRAGMENTS_CONVERT", "1").lower() not in ("1", "true", "yes", "on"):
        record_ifc_event(project, filename, "convert", "skipped", reason="disabled (EXPO_FRAGMENTS_CONVERT)")
        return
    if not save_path.lower().endswith(".ifc"):
        return
    app_dir = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(app_dir, "tools", "fragments", "convert_ifc_to_frag.mjs")
    deps = os.path.join(app_dir, "tools", "fragments", "node_modules")
    if not os.path.exists(script):
        record_ifc_event(project, filename, "convert", "skipped", reason="converter-script-missing", path=script)
        logger.warning("[fragments] converter script missing, skipping: " + script)
        return
    if not os.path.isdir(deps):
        record_ifc_event(project, filename, "convert", "skipped", reason="deps-not-installed",
                         hint="run `npm install` in tools/fragments/")
        logger.warning("[fragments] tools/fragments/node_modules not installed -- run `npm install` there to enable .frag compression. Keeping raw IFC.")
        return
    node_bin = os.getenv("EXPO_NODE_BIN", "node")
    out_path = save_path + ".frag"
    try:
        timeout_s = int(os.getenv("EXPO_FRAGMENTS_TIMEOUT", "900"))
    except ValueError:
        timeout_s = 900

    def _cleanup_partial():
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass

    try:
        in_bytes = os.path.getsize(save_path) if os.path.exists(save_path) else None
    except Exception:
        in_bytes = None
    record_ifc_event(project, filename, "convert", "started", inBytes=in_bytes, node=node_bin, timeout_s=timeout_s)
    t_start = time.time()

    try:
        logger.info("[fragments] converting " + filename + " -> .frag")
        proc = subprocess.run([node_bin, script, save_path, out_path],
                              capture_output=True, text=True, timeout=timeout_s)
        if proc.returncode == 0:
            info = {}
            try:
                info = json.loads((proc.stdout or "").strip().splitlines()[-1])
            except Exception:
                pass
            record_ifc_event(project, filename, "convert", "ok",
                             inBytes=info.get("inBytes"), outBytes=info.get("outBytes"),
                             ratio=info.get("ratio"), ms=info.get("ms", int((time.time() - t_start) * 1000)),
                             frag=os.path.basename(out_path))
            logger.info("[fragments] done: {in_mb:.1f} MB IFC -> {out_mb:.1f} MB frag ({ratio}x) in {ms} ms".format(
                in_mb=(info.get("inBytes", 0) or 0) / 1e6, out_mb=(info.get("outBytes", 0) or 0) / 1e6,
                ratio=info.get("ratio", "?"), ms=info.get("ms", "?")))
        else:
            _cleanup_partial()
            err = (proc.stderr or proc.stdout or "").strip()
            record_ifc_event(project, filename, "convert", "failed", returncode=proc.returncode, error=err[:800])
            logger.warning("[fragments] conversion failed (rc=" + str(proc.returncode) + "): " + err[:500])
    except subprocess.TimeoutExpired:
        _cleanup_partial()
        record_ifc_event(project, filename, "convert", "timeout", timeout_s=timeout_s)
        logger.warning("[fragments] conversion timed out after " + str(timeout_s) + "s for " + filename)
    except FileNotFoundError:
        record_ifc_event(project, filename, "convert", "skipped", reason="node-not-found",
                         hint="install Node or set EXPO_NODE_BIN", node=node_bin)
        logger.warning("[fragments] Node not found (set EXPO_NODE_BIN to the node binary). Keeping raw IFC.")
    except Exception as e:
        record_ifc_event(project, filename, "convert", "error", error=str(e)[:800])
        logger.warning("[fragments] conversion error: " + str(e))

def process_document(project, save_path, filename, disc, category, folder_id=None):
    """Runs in a background thread. Deep-extracts, writes JSON, indexes, sets status.
    Live progress is kept in PROGRESS so the documents endpoint can report it."""
    key = _pkey(project, filename)
    PROGRESS[key] = {"stage": "starting", "done": 0, "total": 0}
    try:
        ext = os.path.splitext(save_path)[-1].lower()
        combined = ""
        meta = {"type": "other"}
        if vision.is_image(save_path):
            PROGRESS[key] = {"stage": "reading image", "done": 0, "total": 1}
            combined = vision.describe_image(save_path) or ""
            meta = {"type": "image", "vision": combined}
            PROGRESS[key] = {"stage": "reading image", "done": 1, "total": 1}
        elif cad.is_cad(save_path):
            data, imgs = cad.ingest(save_path, save_path + "_render")
            parts, views = [], []
            if data:
                parts.append("CAD DATA (extracted from the drawing):\n" + data)
            total = max(1, len(imgs))
            for idx, im in enumerate(imgs):
                PROGRESS[key] = {"stage": "reading views", "done": idx, "total": total}
                try:
                    vt = vision.describe_image(im)
                    if vt:
                        parts.append("DRAWING VIEW (%s):\n%s" % (os.path.basename(im), vt))
                        views.append({"image": os.path.basename(im), "vision": vt})
                except Exception:
                    logger.exception("vision on CAD render failed")
            PROGRESS[key] = {"stage": "reading views", "done": total, "total": total}
            combined = "\n\n====\n\n".join(parts)
            meta = {"type": "cad", "data": data, "views": views}
        elif ext == ".pdf":
            def _cb(done, total):
                PROGRESS[key] = {"stage": "reading pages", "done": done, "total": total}
            # Phase 5B: Disable unbounded legacy vision; use native extraction only.
            combined, meta = extract.extract_pdf(save_path, vision_fn=None,
                                                 render_dir=save_path + "_pages", deep=False,
                                                 smart=True, max_pages=300, progress_cb=_cb)
        elif ext in (".xlsx", ".xls"):
            PROGRESS[key] = {"stage": "reading spreadsheet", "done": 0, "total": 1}
            combined, meta = extract.extract_excel(save_path)
            PROGRESS[key] = {"stage": "reading spreadsheet", "done": 1, "total": 1}
        elif ext == ".docx":
            PROGRESS[key] = {"stage": "reading document", "done": 0, "total": 1}
            combined, meta = extract.extract_docx(save_path)
            PROGRESS[key] = {"stage": "reading document", "done": 1, "total": 1}
        cur = PROGRESS.get(key, {})
        PROGRESS[key] = {"stage": "indexing", "done": cur.get("total", 1), "total": cur.get("total", 1)}
        meta["filename"] = filename
        meta["category"] = category
        extract.save_json(save_path + ".index.json", meta)
        try:
            with open(save_path + ".extracted.txt", "w", encoding="utf-8") as tf:
                tf.write(combined or "")
        except Exception:
            pass
            
        chunks_n = 0
        has_warnings = False
        
        if combined and combined.strip():
            try:
                chunks_n = index_structured(project, meta, filename, folder_id)
                if chunks_n == 0:  # fallback if structured units were empty
                    chunks_n = index_text(project, combined, filename, folder_id)
                # Phase 2: Structured table extraction
                try:
                    from config import get_settings as _gs_st
                    if _gs_st().enable_structured_tables:
                        from services.ingestion import get_pipeline
                        # Get project ID (not name)
                        with db.SessionLocal() as _s:
                            _proj = _s.query(db.Project).filter_by(name=project).first()
                            _proj_id = _proj.id if _proj else None
                        if _proj_id:
                            table_rows = get_pipeline().extract_structured_tables(_proj_id, filename, meta)
                            if table_rows > 0:
                                logger.info("Extracted {} structured table rows for {}", table_rows, filename)
                            
                            # Phase 5B: Visual Table Extraction Pipeline (EasyOCR + Qwen2.5-VL 7B)
                            if ext == ".pdf":
                                PROGRESS[key] = {"stage": "visual extraction", "done": 0, "total": 1}
                                from services.pipeline import process_document_pipeline
                                pipe_status = process_document_pipeline(_proj_id, save_path, filename)
                                if pipe_status == "WARNINGS":
                                    has_warnings = True
                except Exception as e:
                    logger.warning("Structured table extraction failed: {}", e)
                # Phase 2: Quantities extraction
                try:
                    from config import get_settings as _gs_q
                    if _gs_q().enable_quantities_store:
                        from services.ingestion import get_pipeline
                        # Get project ID (not name)
                        with db.SessionLocal() as _s:
                            _proj = _s.query(db.Project).filter_by(name=project).first()
                            _proj_id = _proj.id if _proj else None
                        if _proj_id:
                            quantities = get_pipeline().extract_quantities(_proj_id, filename, meta)
                            if quantities > 0:
                                logger.info("Extracted {} quantities for {}", quantities, filename)
                except Exception as e:
                    logger.warning("Quantities extraction failed: {}", e)
                
                final_status = "ready_with_warnings" if has_warnings else "ready"
                db.update_document_status(project, filename, chunks_n, final_status)
                logger.info("Processed {} -> {} chunks (page-aware), status: {}", filename, chunks_n, final_status)
            except Exception:
                # Extraction succeeded and is saved to .extracted.txt; only the
                # embedding step failed (usually the local model server). Keep the
                # text and mark 'extracted' so it can be re-indexed without redoing
                # the heavy extraction.
                logger.exception("indexing failed (extraction saved) for " + str(filename))
                db.update_document_status(project, filename, 0, "extracted")
        else:
            db.update_document_status(project, filename, 0, "error")
    except Exception:
        logger.exception("process_document failed for " + str(filename))
        db.update_document_status(project, filename, 0, "error")
    finally:
        PROGRESS.pop(key, None)
def process_user_upload(upload_id, save_path, filename):
    """Background extraction for a PRIVATE chat attachment (the Copilot "+"
    button). Deliberately lightweight and fully isolated from the shared
    project pipeline above: no FAISS indexing, no ScheduleRow/Quantity rows,
    no vision pass on PDFs (text layer only, deep=False) -- this only needs
    to ground THIS user's own follow-up questions, not feed project-wide
    search. Writes a .extracted.txt sidecar, same convention as
    process_document, so /ask_stream's attachment injection can read it."""
    try:
        ext = os.path.splitext(save_path)[-1].lower()
        combined = ""
        if vision.is_image(save_path):
            combined = vision.describe_image(save_path) or ""
        elif ext == ".pdf":
            combined, _meta = extract.extract_pdf(save_path, deep=False)
        elif ext in (".xlsx", ".xls"):
            combined, _meta = extract.extract_excel(save_path)
        elif ext == ".docx":
            combined, _meta = extract.extract_docx(save_path)
        elif ext in (".txt", ".csv", ".md"):
            with open(save_path, encoding="utf-8", errors="ignore") as f:
                combined = f.read()
        try:
            with open(save_path + ".extracted.txt", "w", encoding="utf-8") as tf:
                tf.write(combined or "")
        except Exception:
            pass
        db.update_user_upload_status(upload_id, "ready" if (combined and combined.strip()) else "error")
    except Exception:
        logger.exception("process_user_upload failed for " + str(filename))
        db.update_user_upload_status(upload_id, "error")


# Phase 0: File content validation (magic bytes)
MAGIC_BYTES = {
    ".pdf": b"%PDF",
    ".png": b"\x89PNG",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".gif": b"GIF8",
    ".webp": b"RIFF",
    ".bmp": b"BM",
    ".tiff": b"II",
    ".tif": b"II",
    ".zip": b"PK",
    ".docx": b"PK",  # docx is a zip
    ".xlsx": b"PK",  # xlsx is a zip
    ".dwg": b"AC10",  # DWG files start with AC10xx
    ".dxf": b"AutoCAD",
}


def validate_file_content(path: str, ext: str) -> bool:
    """Validate file content matches expected magic bytes."""
    magic = MAGIC_BYTES.get(ext)
    if magic is None:
        return True  # Unknown type, allow
    try:
        with open(path, "rb") as f:
            header = f.read(len(magic) + 8)
        if ext in (".docx", ".xlsx"):
            # ZIP-based formats — check for ZIP signature
            return header[:2] == b"PK"
        if ext == ".dxf":
            # DXF files may start with whitespace or AutoCAD header
            return b"AutoCAD" in header or b"DXF" in header or header[:4] == b"  0\n"
        if ext == ".dwg":
            return header[:4] == b"AC10" or header[:4] == b"AC11" or header[:4] == b"AC12"
        return header[:len(magic)] == magic
    except Exception:
        return False


@app.post("/upload")
async def upload_document(request: Request, background: BackgroundTasks, project: str = Form("default"), discipline: str = Form(""), folder_id: int = Form(None), file: UploadFile = File(...)):
    user = auth.require_roles(request, "admin", "lead")
    if user["role"] != "admin":
        auth.require_project(request, project)
    # A document must live in a folder (the permission unit).
    folders = {f["id"]: f["name"] for f in db.list_folders(project)}
    if folder_id is None or folder_id not in folders:
        raise HTTPException(400, "Please choose a folder to upload into (create one first if needed).")
    folder_name = folders[folder_id]
    ext = os.path.splitext(file.filename)[-1].lower()
    if ext in BLOCK_EXTS:
        raise HTTPException(400, "This file type is not allowed for security reasons.")
    category = categorize(file.filename)
    fsafe = re.sub(r"[^A-Za-z0-9._-]+", "_", folder_name).strip("_") or ("folder_%d" % folder_id)
    proj_doc_dir = os.path.join(DOCS_DIR, project, fsafe)
    os.makedirs(proj_doc_dir, exist_ok=True)
    save_path = os.path.join(proj_doc_dir, file.filename)
    _save_upload_capped(file, save_path)
    # Phase 0: Validate file content
    if not validate_file_content(save_path, ext):
        os.remove(save_path)
        raise HTTPException(400, "File content does not match its extension. Upload rejected.")
    disc = disciplines.normalize(discipline) or category
    needs = (ext in INDEXABLE_EXTS) or vision.is_image(save_path) or cad.is_cad(save_path)
    status = "processing" if needs else "stored"
    db.record_document(project, file.filename, save_path, 0, discipline=disc, status=status,
                       folder_id=folder_id, user=user, ip=_client_ip(request))
    if needs:
        background.add_task(process_document, project, save_path, file.filename, disc, category, folder_id)
    # Compress uploaded IFC models to a lightweight Fragments (.frag) sibling in
    # the background (best-effort; keeps the raw .ifc either way).
    if ext == ".ifc":
        try:
            _sz = os.path.getsize(save_path)
        except Exception:
            _sz = None
        record_ifc_event(project, file.filename, "upload", "received", inBytes=_sz, folder=folder_name, by=user.get("username") if isinstance(user, dict) else None)
        background.add_task(convert_ifc_to_fragments, project, save_path, file.filename)
    return {"message": ("Processing started" if needs else "Stored (original kept, not AI-indexed)"),
            "filename": file.filename, "category": category, "folder": folder_name, "status": status}

# ============================================================
# Private AI-chat attachments ("+" button in Design AI Copilot).
# Any authenticated user with access to the project may use these -- NOT
# gated to admin/lead like /upload, since this never touches the shared,
# permission-managed project document corpus. Stored outside DOCS_DIR,
# never indexed into FAISS/ScheduleRow, never listed in /projects/{p}/documents,
# /projects/{p}/folders, Drawings, Documents or Schedules. Visible only to the
# uploading user (and to admins, read-only, via /admin/chat-attachments).
# ============================================================
@app.post("/chat/attachments")
async def upload_chat_attachment(request: Request, background: BackgroundTasks,
                                 project: str = Form(...), file: UploadFile = File(...)):
    user = auth.require_project(request, project)
    ext = os.path.splitext(file.filename)[-1].lower()
    if ext in BLOCK_EXTS:
        raise HTTPException(400, "This file type is not allowed for security reasons.")
    import datetime as _dt
    stamp = _dt.datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    user_dir = os.path.join(PRIVATE_UPLOADS_DIR, str(user["id"]),
                            re.sub(r"[^A-Za-z0-9._-]+", "_", project).strip("_") or "project")
    os.makedirs(user_dir, exist_ok=True)
    save_path = os.path.join(user_dir, "%s_%s" % (stamp, file.filename))
    _save_upload_capped(file, save_path)
    if not validate_file_content(save_path, ext):
        os.remove(save_path)
        raise HTTPException(400, "File content does not match its extension. Upload rejected.")
    size = os.path.getsize(save_path)
    try:
        rec = db.create_user_upload(user["id"], project, file.filename, save_path, size)
    except ValueError as e:
        os.remove(save_path)
        raise HTTPException(400, str(e))
    background.add_task(process_user_upload, rec["id"], save_path, file.filename)
    db.audit("chat_attachment.upload", project=project, target=file.filename, user=user, ip=_client_ip(request))
    return rec

@app.get("/chat/attachments")
async def list_chat_attachments(request: Request, project: str):
    user = auth.require_user(request)
    return {"attachments": db.list_user_uploads(user["id"], project)}

@app.get("/chat/attachments/{upload_id}")
async def get_chat_attachment(upload_id: int, request: Request):
    user = auth.require_user(request)
    rec = db.get_user_upload(upload_id)
    if not rec or (rec["user_id"] != user["id"] and user["role"] != "admin"):
        raise HTTPException(404, "Not found")
    return rec

@app.delete("/chat/attachments/{upload_id}")
async def delete_chat_attachment(upload_id: int, request: Request):
    user = auth.require_user(request)
    rec = db.get_user_upload(upload_id)
    if not rec or (rec["user_id"] != user["id"] and user["role"] != "admin"):
        raise HTTPException(404, "Not found")
    db.delete_user_upload(upload_id)
    db.audit("chat_attachment.delete", project=rec.get("project"), target=rec.get("filename"), user=user, ip=_client_ip(request))
    return {"status": "deleted"}

@app.get("/admin/chat-attachments")
async def admin_list_chat_attachments(request: Request, project: str = None):
    auth.require_roles(request, "admin")
    return {"attachments": db.list_all_user_uploads(project)}


@app.delete("/projects/{project}/docs")
async def clear_docs(project: str, request: Request = None):
    user = auth.require_roles(request, "admin", "lead")
    auth.require_project(request, project)
    if project in vectorstores:
        del vectorstores[project]
    proj_idx = os.path.join(INDEX_DIR, project)
    if os.path.exists(proj_idx):
        shutil.rmtree(proj_idx)
    db.clear_docs(project, user=user, ip=_client_ip(request))
    return {"status": "cleared"}

def build_messages(req: QueryRequest, ctx: str = ""):
    msgs = []
    if ctx:
        sys_msg = f"""You are Expo Design AI, an expert engineering assistant. The user has uploaded documents to this project, and the relevant content has been automatically extracted and is provided below as CONTEXT. You MUST use this context to answer the user's question. Do NOT say you cannot read files — the files have already been read and the text is right here.

DOCUMENT CONTEXT (extracted from uploaded files):
---
{ctx}
---

ANSWER RULES:
- Use ONLY the DOCUMENT CONTEXT above. Do not use outside knowledge and do NOT invent or estimate any number.
- Quote the exact value(s) and units exactly as written in the context.
- Cite where it came from: the [SOURCE: filename] of the chunk you used, and the [PAGE n] marker nearest the value if one is shown.
- The user's wording may differ from the document's. For example "SBC" (safe bearing capacity) may appear as "soil pressure under the foundation", "bearing pressure", or a value in kPa / kN/m2. Match on meaning, not just exact words.
- If the value is genuinely not present in the context, say clearly: "I could not find this in the uploaded documents" and name what document/section would contain it. Never fabricate a value.

ABOUT YOUR CAPABILITIES: You are a VISION-capable engineering assistant. Every uploaded drawing, PDF page and image has ALREADY been read by a local vision model (Qwen2.5-VL) and its extracted text/description appears in the context above under [DRAWING/VISION] or [SOURCE:] markers. NEVER say you are a text-only AI, that you cannot see or view images/drawings, or that you have no access to uploaded files - that is false. If a specific drawing's details are not in the provided context, say the drawing was not found in the retrieved context and ask the user to open it or name the sheet - do NOT deny your ability to read drawings."""

        # Phase 2 (Task 3): Add not-found guidance when context is empty
        if not ctx.strip():
            sys_msg = """You are Expo Design AI, an expert engineering assistant. The user asked a question, but NO relevant content was found in the uploaded documents.

IMPORTANT: You MUST honestly state that you could not find the information. Do NOT invent or guess any value.

Response format:
"I could not find this in the uploaded documents. This information would typically be found in [document type: e.g., door schedule, finishes legend, structural calculations, etc.]."

Replace [document type] with the most likely document type based on the question."""
    else:
        sys_msg = "You are Expo Design AI, an expert engineering assistant for structural design, Dubai local code compliance, drawings review, and technical reports. Uploaded drawings, PDFs and images are read by a local vision model (Qwen2.5-VL), so you CAN analyze drawings and images. NEVER claim to be a text-only AI or that you cannot see images/drawings/PDFs - that is false. If the user has not uploaded a relevant file yet, ask them to upload it; do not deny your vision ability."
        
    dprompt = disciplines.system_prompt(req.discipline)
    if dprompt:
        sys_msg = dprompt + "\n\n" + sys_msg

    if req.mode == "cowork":
        sys_msg += """

COWORK MODE: You are an autonomous Agent with access to a SANDBOXED project workspace (NOT the whole computer).
All paths are relative to this project's workspace folder; any path outside it is blocked by the system.
To interact with the workspace, output a JSON block wrapped EXACTLY in <tool> tags.
Supported actions:
1. {"action": "list_dir", "path": "."}
2. {"action": "read_file", "path": "notes/spec.txt"}
3. {"action": "write_file", "path": "output/report.md", "content": "..."}
4. {"action": "create_folder", "path": "output"}

Example:
I will check the workspace files.
<tool>
{"action": "list_dir", "path": "."}
</tool>

You must wait for the system to reply with the tool result before continuing your reasoning."""
    else:
        sys_msg += "\n\nFormat your responses beautifully using markdown (bold, lists, etc). IMPORTANT: Only if the user explicitly asks you to build a UI, generate code, create a website, or draw a diagram, then you should provide complete HTML, CSS, SVG, or code wrapped in a fenced block (e.g. ```html ... ```)."
    
    msgs.append(SystemMessage(content=sys_msg))
    
    _hist = req.messages[-4:] if ctx else req.messages[-8:]
    for m in _hist:
        if m.role in ['user', 'human']:
            msgs.append(HumanMessage(content=m.content))
        elif m.role in ['assistant', 'ai']:
            msgs.append(AIMessage(content=m.content))
            
    msgs.append(HumanMessage(content=req.query))
    return msgs

def get_llm(req: QueryRequest):
    # Direct /api/chat streamer (reliable + larger context) instead of ChatOllama.
    # Wave 1: Model tiering — when enabled, uses worker/author split.
    # When disabled, preserves existing behavior (single author model).
    _DEFAULT = "qwen2.5vl:32b"
    try:
        from config import get_settings
        s = get_settings()
        mdl = getattr(s, "chat_model", "qwen2.5vl:7b") or "qwen2.5vl:7b"
        # honor an explicit per-request model choice; otherwise use the fast chat model
        if getattr(req, "model", None) and req.model != _DEFAULT:
            mdl = req.model
        return local_chat.LocalChatOllama(model=mdl, temperature=0.1,
                                          num_predict=3072, keep_alive="5m")
    except Exception:
        pass
    return local_chat.LocalChatOllama(model=req.model, temperature=0.1,
                                      num_predict=3072, keep_alive="5m")


def self_check_answer(answer: str, context: str, query: str) -> str:
    """
    Phase 2 (Task 3): Worker model self-check.
    Drops any claim not supported by a cited chunk.
    Returns the cleaned answer or the original if self-check fails.
    """
    try:
        from config import get_settings as _gs_sc
        if not _gs_sc().enable_self_check:
            return answer

        import local_chat as _lc_sc
        prompt = (
            "You verify engineering answers. Given a question, context, and answer, "
            "remove any claim NOT supported by the context. Keep all supported claims. "
            "If the answer cannot be supported, say: 'I could not find this in the uploaded documents.'\n\n"
            f"Question: {query}\n\n"
            f"Context:\n{context[:4000]}\n\n"
            f"Answer:\n{answer}\n\n"
            "Verified answer:"
        )
        result = _lc_sc.worker_complete(prompt, num_predict=512)
        if result and result.strip():
            logger.info("Self-check: answer verified/cleaned")
            return result.strip()
        return answer
    except Exception as e:
        logger.warning("Self-check failed: {}", e)
        return answer

@app.post("/ask_image")
async def ask_image(request: Request, project: str = Form("default"),
                    query: str = Form(""), files: List[UploadFile] = File(...)):
    """Ephemeral vision Q&A: answer a question about pasted/attached image(s) using
    the local vision model, for ANY role with access to the project. The image is
    NOT stored in the project knowledge base -- it is written to a temp file, read,
    then deleted."""
    user = auth.require_project(request, project)  # any role (admin/lead/user) with access
    db.audit("ask.image", project=project,
             detail={"images": len(files), "chars": len(query or "")},
             user=user, ip=_client_ip(request))
    import tempfile
    tmp_paths = []
    for f in files:
        ext = os.path.splitext(f.filename or "")[-1].lower() or ".png"
        fd, tp = tempfile.mkstemp(suffix=ext)
        with os.fdopen(fd, "wb") as out:
            shutil.copyfileobj(f.file, out)
        tmp_paths.append(tp)

    def gen():
        try:
            q = (query or "").strip()
            instr = (q if q else "Describe this image for an engineering review.") + (
                "\n\nAnswer ONLY from what is visibly written/shown in the image. "
                "Quote exact values and units. If something is not legible or not present, "
                "say so plainly -- never guess or invent a value.")
            produced = False
            for i, tp in enumerate(tmp_paths):
                if not vision.is_image(tp):
                    continue
                try:
                    txt = (vision.describe_image(tp, instruction=instr) or "").strip()
                except Exception as e:
                    yield f"data: {json.dumps({'type':'error','message': 'Vision failed: %s' % e})}\n\n"
                    return
                if len(tmp_paths) > 1:
                    header = "\n\n**Image %d:**\n" % (i + 1)
                    yield f"data: {json.dumps({'type':'token','text': header})}\n\n"
                for j in range(0, len(txt), 400):
                    yield f"data: {json.dumps({'type':'token','text': txt[j:j+400]})}\n\n"
                produced = True
            if not produced:
                yield f"data: {json.dumps({'type':'token','text':'No readable image was provided.'})}\n\n"
            yield f"data: {json.dumps({'type':'done'})}\n\n"
        finally:
            for tp in tmp_paths:
                try:
                    os.remove(tp)
                except Exception:
                    pass

    return StreamingResponse(gen(), media_type="text/event-stream")



@app.post("/api/query_document")
async def api_query_document(request: Request):
    user = auth.require_project(request, "default")
    try:
        body = await request.json()
    except:
        body = {}
        
    project_id = body.get("project", "default")
    question = body.get("question", "")
    
    if not question:
        return {"status": "ERROR", "answer": "Question is required."}
        
    import intelligence.structured_query as sq
    
    def do_retrieve(proj, q, k=5, user=None):
        return retrieve_context(proj, q, k, user)
        
    def do_qwen(prompt):
        import time
        t_start = time.perf_counter()
        import httpx
        try:
            r = httpx.post("http://127.0.0.1:11434/api/generate", json={
                "model": "qwen2.5:32b", "prompt": prompt, "stream": False, "options": {"temperature": 0.0}
            }, timeout=10.0)
            return r.json().get("response", ""), time.perf_counter() - t_start
        except:
            return "[Qwen Fallback Generated Answer]", time.perf_counter() - t_start
            
    resp, latencies = sq.query_document(
        question, project_id, 
        retrieve_context_func=do_retrieve,
        call_qwen_func=do_qwen,
        user_context={"user": user, "selected_guid": body.get("selected_guid"), "history": body.get("history", [])}
    )
    
    return resp

@app.post("/ask_stream")
async def ask_stream(req: QueryRequest, request: Request = None):
    user = auth.require_project(request, req.project)
    db.audit("ask.stream", project=req.project,
             detail={"model": req.model, "mode": req.mode, "chars": len(req.query or "")},
             user=user, ip=_client_ip(request))

    # Phase 0: Optional orchestrator mode (falls back to direct RAG if orchestrator fails)
    if req.mode == "orchestrated":
        try:
            result = orchestrator.process(
                query=req.query,
                project=req.project,
                user=user,
                discipline=req.discipline,
                messages=[{"role": m.role, "content": m.content} for m in (req.messages or [])],
            )
            # For now, fall through to normal RAG — orchestrator returns classification only
            logger.info("Orchestrator classified query as: {} (confidence={:.2f})",
                        result.query_type, result.confidence)
        except Exception as e:
            logger.warning("Orchestrator failed, falling back to direct RAG: {}", e)

    srcs, ctx = retrieve_context(req.project, req.query, req.k, user)
    # Focused-document grounding (additive): when the user is asking about a
    # specific open document, include its FULL extracted text so the answer is not
    # limited to whichever 800-char chunks vector search happened to return. This
    # fixes tables whose heading and numbers land in different chunks.
    _focus_used = False
    if getattr(req, "focus_doc", ""):
        try:
            _base = os.path.abspath(os.path.join(DOCS_DIR, req.project))
            _rel = (req.focus_doc or "").replace(chr(92), "/").lstrip("/")
            _tgt = os.path.abspath(os.path.join(_base, _rel))
            if _tgt == _base or _tgt.startswith(_base + os.sep):
                _etp = _tgt + ".extracted.txt"
                if os.path.isfile(_etp):
                    with open(_etp, encoding="utf-8") as _ef:
                        _ftext = _ef.read()
                    if _ftext.strip():
                        _fn = os.path.basename(_tgt)
                        _ftext = _ftext[:16000]
                        _blk = ("FOCUSED DOCUMENT (the document the user is currently viewing "
                                "- answer from this first; it is the authoritative source):\n"
                                "[SOURCE: %s | PAGE 1]\n%s" % (_fn, _ftext))
                        ctx = _blk + "\n\n====\n\n" + ctx
                        srcs = [{"source": _fn, "page": 1}] + [
                            s for s in srcs
                            if not (isinstance(s, dict) and s.get("source") == _fn and s.get("page") == 1)]
                        logger.info("focus_doc injected: {} ({} chars)", _fn, len(_ftext))
                        _focus_used = True
        except Exception as _fe:
            logger.warning("focus_doc injection failed: {}", _fe)

    # Private chat-attachment grounding (additive, isolated): the uploading
    # user's own attached file, injected as the authoritative source the same
    # way focus_doc is, but ownership-checked here (not by a path prefix)
    # since the file lives outside DOCS_DIR entirely. Project docs still
    # retrieved above stay available alongside it.
    if getattr(req, "attachment_id", None):
        try:
            _att = db.get_user_upload(req.attachment_id)
            if _att and _att["user_id"] == user["id"] and _att["project"] == req.project:
                _atp = _att["path"] + ".extracted.txt"
                if os.path.isfile(_atp):
                    with open(_atp, encoding="utf-8") as _af:
                        _atext = _af.read()
                    if _atext.strip():
                        _afn = _att["filename"]
                        _atext = _atext[:16000]
                        _ablk = ("PRIVATE ATTACHMENT (uploaded by the user asking this question, visible "
                                 "only to them - answer from this first; it is the authoritative source):\n"
                                 "[SOURCE: %s | PAGE 1]\n%s" % (_afn, _atext))
                        ctx = _ablk + "\n\n====\n\n" + ctx
                        srcs = [{"source": _afn, "page": 1}] + [
                            s for s in srcs
                            if not (isinstance(s, dict) and s.get("source") == _afn and s.get("page") == 1)]
                        logger.info("chat attachment injected: {} ({} chars)", _afn, len(_atext))
        except Exception as _ae:
            logger.warning("chat attachment injection failed: {}", _ae)

    msgs = build_messages(req, ctx)
    current_llm = get_llm(req)
    
    def execute_tool(j):
        action = j.get("action")
        raw = j.get("path", "")
        try:
            path = resolve_in_workspace(req.project, raw)
        except Exception as e:
            return f"Blocked: {e}"
        ws = project_workspace(req.project)
        rel = os.path.relpath(path, ws)
        if action == "list_dir":
            try: return f"Files in ./{rel}:\n" + "\n".join(os.listdir(path))
            except Exception as e: return str(e)
        elif action == "read_file":
            try:
                with open(path, "r", encoding="utf-8") as f: return f.read()[:5000]
            except Exception as e: return str(e)
        elif action == "write_file":
            try:
                os.makedirs(os.path.dirname(path) or ws, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f: f.write(j.get("content",""))
                return f"Successfully wrote to ./{rel}"
            except Exception as e: return str(e)
        elif action == "create_folder":
            try:
                os.makedirs(path, exist_ok=True)
                return f"Successfully created folder ./{rel}"
            except Exception as e: return str(e)
        return "Unknown tool action"

    _resolved_srcs = resolve_sources(req.project, srcs) if srcs else []

    def gen():
        if srcs:
            yield f"data: {json.dumps({'type':'sources','sources':_resolved_srcs})}\n\n"

        nonlocal msgs
        iteration = 0

        while iteration < 5: # Max 5 tool loops per request to prevent infinite loop
            iteration += 1
            full_response = ""
            tool_call_text = ""
            in_tool = False
            
            try:
                for chunk in current_llm.stream(msgs):
                    token = chunk.content if hasattr(chunk,"content") else str(chunk)
                    full_response += token
                    
                    if "<tool>" in full_response and not in_tool:
                        in_tool = True
                        idx = full_response.index("<tool>")
                        tool_call_text = full_response[idx+6:]
                    elif in_tool:
                        tool_call_text += token
                        
                    if token: 
                        yield f"data: {json.dumps({'type':'token','text':token})}\n\n"
                        
                    if in_tool and "</tool>" in tool_call_text:
                        break # Stop streaming this turn, we need to execute the tool
                        
            except Exception as e:
                yield f"data: {json.dumps({'type':'error','message':str(e)})}\n\n"
                break
                
            msgs.append(AIMessage(content=full_response))
            
            if in_tool and "</tool>" in tool_call_text:
                json_str = tool_call_text.split("</tool>")[0].strip()
                try:
                    j = json.loads(json_str)
                    tool_result = execute_tool(j)
                    # Yield tool result to UI so user sees what happened
                    yield f"data: {json.dumps({'type':'token','text': chr(10) + f'> **System**: {tool_result}' + chr(10)})}\n\n"
                    # Add to history for next LLM iteration
                    msgs.append(SystemMessage(content=f"Tool Execution Result:\n{tool_result}"))
                except Exception as e:
                    err = f"Failed to parse or execute tool JSON: {str(e)}"
                    yield f"data: {json.dumps({'type':'token','text': chr(10) + f'> **System Error**: {err}' + chr(10)})}\n\n"
                    msgs.append(SystemMessage(content=err))
            else:
                break # No tool called, we are done

        # Phase 2 (Task 2): Self-check the final answer
        try:
            from config import get_settings as _gs_sc
            if _gs_sc().enable_self_check and full_response:
                verified = self_check_answer(full_response, ctx, req.query)
                if verified != full_response:
                    logger.info("Self-check: answer was modified")
                    # Send the corrected answer
                    _vtxt = "\n\n[Verified Answer]\n" + verified
                    yield f"data: {json.dumps({'type':'token','text':_vtxt})}\n\n"
        except Exception as _e_sc:
            logger.warning("Self-check failed: {}", _e_sc)

        # Response Rendering Engine (additive, read-only post-processing):
        # build a structured-JSON view of the answer the model already produced.
        # Never changes the model, retrieval, or the plain-text answer above;
        # a plain conversational answer still comes back type="simple_answer"
        # and the frontend renders it exactly as before.
        try:
            structured = response_schema.build_structured_response(
                req.query, full_response, _resolved_srcs,
                subtitle_hint=os.path.basename(req.focus_doc) if getattr(req, "focus_doc", "") else "",
                focus_doc_used=_focus_used,
            )
            yield f"data: {json.dumps({'type':'structured','data':structured})}\n\n"
        except Exception as _e_rr:
            logger.warning("Response renderer build failed: {}", _e_rr)

        yield f"data: {json.dumps({'type':'done'})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")

@app.post("/ask_model")
async def ask_model(req: ModelQueryReq, request: Request = None):
    """Answer a plain-language question about a 3D/BIM model. The viewer supplies a
    compact MODEL DATA summary (building/storeys, element counts by IFC type, spaces &
    areas) plus, optionally, the properties of the selected element. Streams the answer
    via the local LLM. Grounded strictly in the supplied model data -- no RAG."""
    user = auth.require_project(request, req.project)
    db.audit("ask.model", project=req.project,
             detail={"model": req.model, "ctxChars": len(req.context or ""),
                     "hasSel": bool(req.selection)},
             user=user, ip=_client_ip(request))

    # Keep the whole prompt within num_ctx. num_ctx=16384 tokens; reserve room for the
    # system template, chat history and the answer. Cap model data to ~38k chars (~9.5k
    # tokens) and the selection to ~6k chars.
    ctx = (req.context or "")[:38000]
    sel = (req.selection or "")[:6000]

    sys_msg = f"""You are Expo Design AI, a BIM model reviewer for a client-side engineering consultancy. The user is looking at a 3D model in the viewer. The model has ALREADY been parsed from its IFC file and the extracted data is given below as MODEL DATA. Answer the user's question using this data.

MODEL DATA (extracted from the IFC file currently open in the 3D viewer):
---
{ctx}
---
"""
    if sel:
        sys_msg += f"""
CURRENTLY SELECTED ELEMENT (the user has this element selected in the viewer):
---
{sel}
---
"""
    sys_msg += """
ANSWER RULES:
- Use ONLY the MODEL DATA (and the selected element, if given) above. Do NOT use outside knowledge and do NOT invent or estimate any number, quantity, level, name or property.
- Quote exact values and units exactly as they appear (areas in m2, counts, level names, IFC types, property values).
- The user's wording may differ from IFC terms. Map on meaning: "columns" -> IfcColumn, "walls" -> IfcWall, "rooms"/"spaces" -> IfcSpace, "floors"/"levels"/"storeys" -> IfcBuildingStorey, "beams" -> IfcBeam, "doors" -> IfcDoor, etc.
- For "how many X" give the count of the matching IFC type. For areas, sum or list the IfcSpace areas as asked. For "what is selected" / "properties of this", use the SELECTED ELEMENT block.
- If the answer is genuinely not in the model data, say clearly: "That information is not in the current model data" and say what would provide it (e.g. select the element, or the property was not exported to IFC). NEVER fabricate.
- You ARE able to read this model -- the geometry and properties were extracted from the IFC. Never say you cannot see or open 3D models.
- Answer concisely. Use markdown (short lists / bold) when it helps a reviewer scan the answer.

SPECIAL VIEWER COMMANDS:
If the user's query asks you to "show me", "isolate", "hide", or "highlight" specific types of elements in the 3D model, you must append a special command to the very end of your response. 
Map their request to the correct IFC category (e.g., "walls" -> IFCWALL, "doors" -> IFCDOOR, "windows" -> IFCWINDOW, "lift lobby" -> IFCSPACE, "columns" -> IFCCOLUMN).
Format exactly like this at the end of your text: [COMMAND:ISOLATE:IFCWALL]"""

    msgs = [SystemMessage(content=sys_msg)]
    for m in (req.messages or [])[-4:]:
        if m.role in ('user', 'human'):
            msgs.append(HumanMessage(content=m.content))
        elif m.role in ('assistant', 'ai'):
            msgs.append(AIMessage(content=m.content))
    msgs.append(HumanMessage(content=req.query))

    try:
        from config import get_settings as _gs_am
        _cm = getattr(_gs_am(), "chat_model", "qwen2.5vl:7b") or "qwen2.5vl:7b"
    except Exception:
        _cm = "qwen2.5vl:7b"
    _mdl_am = req.model if (getattr(req, "model", None) and req.model != "qwen2.5vl:32b") else _cm
    current_llm = local_chat.LocalChatOllama(model=_mdl_am, temperature=0.1,
                                             num_predict=3072, keep_alive="5m")

    def gen():
        _full = ""
        try:
            for chunk in current_llm.stream(msgs):
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                if token:
                    _full += token
                    yield f"data: {json.dumps({'type':'token','text':token})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','message':str(e)})}\n\n"
        try:
            structured = response_schema.build_structured_response(
                req.query, _full, [], subtitle_hint="3D model", focus_doc_used=False)
            yield f"data: {json.dumps({'type':'structured','data':structured})}\n\n"
        except Exception as _e_rr:
            logger.warning("Response renderer build failed (ask_model): {}", _e_rr)
        yield f"data: {json.dumps({'type':'done'})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/ask_chat")
async def ask_chat(req: QueryRequest, request: Request = None):
    user = auth.require_project(request, req.project)
    db.audit("ask.chat", project=req.project,
             detail={"model": req.model, "chars": len(req.query or "")},
             user=user, ip=_client_ip(request))
    msgs = build_messages(req, "")
    current_llm = get_llm(req)
    
    def gen():
        try:
            for chunk in current_llm.stream(msgs):
                token = chunk.content if hasattr(chunk,"content") else str(chunk)
                if token: yield f"data: {json.dumps({'type':'token','text':token})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','message':str(e)})}\n\n"
        yield f"data: {json.dumps({'type':'done'})}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/projects")
async def list_projects(request: Request):
    return db.projects_with_chats(request.state.user)

@app.post("/projects/save")
async def save_project(data: ProjectSave, request: Request = None):
    user = auth.require_project(request, data.project)
    db.save_chat(data.project, data.chat_id, data.title, data.messages, user=user, ip=_client_ip(request))
    return {"status":"ok"}

@app.delete("/projects/{project}/{chat_id}")
async def delete_chat(project: str, chat_id: str, request: Request = None):
    user = auth.require_project(request, project)
    db.delete_chat(project, chat_id, user=user, ip=_client_ip(request))
    return {"status":"deleted"}

@app.get("/disciplines")
async def get_disciplines():
    return {"editions": disciplines.CODE_EDITIONS, "disciplines": disciplines.list_all()}

@app.get("/disciplines/{key}")
async def get_discipline(key: str):
    d = disciplines.get(key)
    if not d: raise HTTPException(404, "Unknown discipline")
    return {"key": d["key"], "name": d["name"], "status": d["status"],
            "codes": [disciplines.CODE_EDITIONS[c] for c in d["codes"]],
            "checklist": d["checklist"]}

@app.post("/projects/{project}/discipline")
async def set_project_discipline(project: str, discipline: str, request: Request = None):
    user = auth.require_roles(request, "admin", "lead")
    auth.require_project(request, project)
    d = disciplines.get(discipline)
    if not d: raise HTTPException(400, "Unknown discipline")
    db.set_project_discipline(project, d["key"], user=user, ip=_client_ip(request))
    return {"status": "ok", "project": project, "discipline": d["key"]}

@app.post("/kb/upload")
async def kb_upload(request: Request, file: UploadFile = File(...), code: str = Form(""), part: str = Form("")):
    user = auth.require_roles(request, "admin", "lead")
    ext = os.path.splitext(file.filename)[-1].lower()
    if ext not in (".pdf",".docx",".xlsx",".xls"):
        raise HTTPException(400, "Only PDF, DOCX, XLSX, XLS.")
    kb_dir = os.path.join(DOCS_DIR, KB_COLLECTION)
    os.makedirs(kb_dir, exist_ok=True)
    save_path = os.path.join(kb_dir, file.filename)
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        chunks_n = await run_in_threadpool(index_document, KB_COLLECTION, save_path)
        # Store discipline and part in metadata
        discipline = code or "code"
        db.record_document(KB_COLLECTION, file.filename, save_path, chunks_n,
                           discipline=discipline, user=user, ip=_client_ip(request))
        # Save part info in doc_meta
        if part:
            import json
            meta_path = save_path + ".index.json"
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta["dbc_part"] = part
                meta["discipline"] = discipline
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=1)
        return {"message":"Indexed into code knowledge base","filename":file.filename,"chunks":chunks_n,"part":part}
    except Exception as e:
        logger.exception("KB upload error")
        raise HTTPException(500, f"Error processing file: {str(e)}")

@app.get("/kb")
async def kb_list():
    return {"collection": KB_COLLECTION, "documents": db.list_documents(KB_COLLECTION)}

@app.get("/projects/{project}/documents")
async def project_documents(project: str, request: Request):
    user = auth.require_project(request, project)
    base = os.path.abspath(os.path.join(DOCS_DIR, project))
    out = []
    for d in db.list_documents(project, user):
        fn = d["filename"]; pth = d.get("path")
        rel = fn
        if pth:
            try:
                r = os.path.relpath(pth, base)
                if not r.startswith(".."):
                    rel = r
            except Exception:
                pass
        fp = os.path.join(base, rel)
        size = None
        try:
            if os.path.isfile(fp):
                size = os.path.getsize(fp)
        except Exception:
            pass
        out.append({"filename": fn, "category": categorize(fn),
                    "rel": rel.replace(os.sep, "/"), "chunks": d["chunks"],
                    "indexed": (d["chunks"] or 0) > 0, "discipline": d.get("discipline"),
                    "status": d.get("status", "ready"),
                    "folder": d.get("folder"), "folder_id": d.get("folder_id"),
                    "progress": PROGRESS.get(_pkey(project, fn)),
                    "hasData": os.path.isfile(fp + ".index.json"),
                    "uploaded_at": d.get("uploaded_at"), "size": size,
                    "exists": os.path.isfile(fp)})
    return {"project": project, "documents": out}


# ============================================================
# Folders + folder-level permissions
# ============================================================
def _require_manage(request, project):
    user = auth.require_project(request, project)
    if not auth.can_manage_project(user, project):
        raise HTTPException(403, "Not permitted for your role")
    return user

@app.get("/projects/{project}/folders")
async def list_project_folders(project: str, request: Request):
    user = auth.require_project(request, project)
    allow_all, ids = db.folder_access(user, project)
    all_folders = db.list_folders(project)
    can_manage = auth.can_manage_project(user, project)
    if allow_all:
        return {"folders": all_folders, "can_manage": can_manage}
    allowed = [f for f in all_folders if f["id"] in (ids or set())]
    return {"folders": allowed, "can_manage": False}

@app.post("/projects/{project}/folders")
async def create_project_folder(project: str, request: Request):
    user = _require_manage(request, project)
    body = await request.json()
    try:
        f = db.create_folder(project, (body or {}).get("name", ""), by=user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok", "folder": f}

@app.post("/projects/{project}/folders/{folder_id}/rename")
async def rename_project_folder(project: str, folder_id: int, request: Request):
    user = _require_manage(request, project)
    body = await request.json()
    try:
        ok = db.rename_folder(folder_id, (body or {}).get("name", ""), by=user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok" if ok else "error"}

@app.delete("/projects/{project}/folders/{folder_id}")
async def delete_project_folder(project: str, folder_id: int, request: Request):
    user = _require_manage(request, project)
    db.delete_folder(folder_id, by=user)
    return {"status": "ok"}

@app.get("/projects/{project}/folders/{folder_id}/members")
async def folder_members_list(project: str, folder_id: int, request: Request):
    _require_manage(request, project)
    return {"members": db.folder_members(folder_id)}

@app.post("/projects/{project}/folders/{folder_id}/members")
async def folder_member_add(project: str, folder_id: int, request: Request):
    user = _require_manage(request, project)
    body = await request.json()
    uid = (body or {}).get("user_id")
    if not uid:
        raise HTTPException(400, "user_id required")
    db.assign_folder_member(folder_id, int(uid), by=user)
    return {"status": "ok"}

@app.delete("/projects/{project}/folders/{folder_id}/members/{user_id}")
async def folder_member_del(project: str, folder_id: int, user_id: int, request: Request):
    user = _require_manage(request, project)
    db.remove_folder_member(folder_id, user_id, by=user)
    return {"status": "ok"}

@app.get("/projects/{project}/assignable-users")
async def assignable_users(project: str, request: Request):
    _require_manage(request, project)
    return {"users": [u for u in db.list_users() if u.get("username") != "system"]}

@app.post("/projects/{project}/documents/move")
async def move_document(project: str, request: Request):
    user = _require_manage(request, project)
    body = await request.json()
    filename = (body or {}).get("filename")
    folder_id = (body or {}).get("folder_id")
    if not filename or folder_id is None:
        raise HTTPException(400, "filename and folder_id required")
    folders = {f["id"] for f in db.list_folders(project)}
    if int(folder_id) not in folders:
        raise HTTPException(400, "unknown folder")
    db.set_document_folder(project, filename, int(folder_id), by=user)
    return {"status": "ok"}


@app.post("/projects/{project}/rebuild")
async def rebuild_index(project: str, request: Request):
    """Wipe and rebuild this project's whole vector index from each document's
    SAVED structured extraction (.index.json) -- page-aware, no re-upload and no
    re-extraction. Use this once to upgrade documents that were indexed before
    page tagging existed."""
    user = auth.require_project(request, project)
    if not auth.can_manage_project(user, project):
        return {"status": "error", "detail": "not allowed"}
    if project in vectorstores:
        del vectorstores[project]
    proj_idx = os.path.join(INDEX_DIR, project)
    if os.path.exists(proj_idx):
        shutil.rmtree(proj_idx)
    total, ok_docs, failed = 0, 0, []
    for d in db.list_documents(project):
        fn = d.get("filename"); path = d.get("path"); fid = d.get("folder_id")
        if not path:
            continue
        jp = path + ".index.json"; tp = path + ".extracted.txt"
        n = 0
        try:
            if os.path.isfile(jp):
                with open(jp, "r", encoding="utf-8") as jf:
                    meta = json.load(jf)
                n = index_structured(project, meta, fn, fid)
            if n == 0 and os.path.isfile(tp):
                with open(tp, "r", encoding="utf-8") as tf:
                    combined = tf.read()
                if combined.strip():
                    n = index_text(project, combined, fn, fid)
            db.update_document_status(project, fn, n, "ready" if n > 0 else "extracted")
            total += n
            if n > 0:
                ok_docs += 1
            else:
                failed.append(fn)
        except Exception:
            logger.exception("rebuild failed for " + str(fn))
            db.update_document_status(project, fn, 0, "extracted")
            failed.append(fn)
    db.audit("index.rebuild", project=project, detail={"chunks": total, "docs": ok_docs},
             user=user, ip=_client_ip(request))
    logger.info("Rebuilt index for {}: {} docs, {} chunks", project, ok_docs, total)
    return {"status": "ok", "chunks": total, "docs": ok_docs, "failed": failed}


@app.post("/projects/{project}/reindex")
async def reindex_document(project: str, request: Request):
    """Re-embed a document from its already-saved extracted text, without redoing
    the heavy render/vision extraction. Recovers files whose indexing failed
    (status 'extracted' or 'error') once the local model server is back."""
    user = auth.require_project(request, project)
    if not auth.can_manage_project(user, project):
        return {"status": "error", "detail": "not allowed"}
    try:
        body = await request.json()
    except Exception:
        body = {}
    filename = (body or {}).get("filename")
    if not filename:
        return {"status": "error", "detail": "filename required"}
    doc = next((d for d in db.list_documents(project) if d["filename"] == filename), None)
    if not doc or not doc.get("path"):
        return {"status": "error", "detail": "document not found"}
    json_path = doc["path"] + ".index.json"
    txt_path = doc["path"] + ".extracted.txt"
    if not (os.path.isfile(json_path) or os.path.isfile(txt_path)):
        return {"status": "error", "detail": "no saved extraction - please re-upload this file"}
    try:
        chunks_n = 0
        # Prefer the structured JSON so re-indexing keeps per-page metadata.
        if os.path.isfile(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as jf:
                    meta = json.load(jf)
                chunks_n = index_structured(project, meta, filename, doc.get("folder_id"))
            except Exception:
                logger.exception("structured reindex failed, will try flat text")
                chunks_n = 0
        if chunks_n == 0 and os.path.isfile(txt_path):
            with open(txt_path, "r", encoding="utf-8") as f:
                combined = f.read()
            if combined.strip():
                chunks_n = index_text(project, combined, filename, doc.get("folder_id"))
        if chunks_n == 0:
            return {"status": "error", "detail": "saved extraction is empty - please re-upload"}
        db.update_document_status(project, filename, chunks_n, "ready")
        db.audit("document.reindex", project=project,
                 detail={"filename": filename, "chunks": chunks_n},
                 user=user, ip=_client_ip(request))
        return {"status": "ready", "chunks": chunks_n}
    except Exception as e:
        logger.exception("reindex failed for " + str(filename))
        db.update_document_status(project, filename, 0, "extracted")
        return {"status": "error", "detail": "indexing failed - is the local model server running? (%s)" % e}

@app.post("/projects/{project}/reextract")
async def reextract_document(project: str, request: Request):
    """Force a VISION re-read of a PDF even when it has a text layer, so complex
    multi-table data sheets are transcribed with their row/column structure intact
    (plain text extraction flattens such tables and loses which value belongs to
    which row). Overwrites the saved extraction, then rebuilds the project index so
    the improved text replaces the old jumbled chunks. Needs Ollama + the vision
    model running; heavy, so trigger it per-document."""
    user = auth.require_project(request, project)
    if not auth.can_manage_project(user, project):
        return {"status": "error", "detail": "not allowed"}
    try:
        body = await request.json()
    except Exception:
        body = {}
    filename = (body or {}).get("filename")
    if not filename:
        return {"status": "error", "detail": "filename required"}
    try:
        max_pages = int((body or {}).get("max_pages") or 60)
    except Exception:
        max_pages = 60
    doc = next((d for d in db.list_documents(project) if d["filename"] == filename), None)
    if not doc or not doc.get("path"):
        return {"status": "error", "detail": "document not found"}
    path = doc["path"]
    if os.path.splitext(path)[-1].lower() != ".pdf":
        return {"status": "error", "detail": "vision re-read is for PDF documents only"}
    if not os.path.isfile(path):
        return {"status": "error", "detail": "original file missing - please re-upload"}
    try:
        def _work():
            combined, meta = extract.extract_pdf(
                path, vision_fn=vision.describe_image,
                render_dir=path + "_pages", deep=True, smart=False, max_pages=max_pages)
            meta["filename"] = filename
            meta["category"] = doc.get("category") or meta.get("category") or ""
            extract.save_json(path + ".index.json", meta)
            try:
                with open(path + ".extracted.txt", "w", encoding="utf-8") as tf:
                    tf.write(combined or "")
            except Exception:
                pass
            return meta
        meta = await run_in_threadpool(_work)
        # Rebuild the whole project index so the old jumbled chunks are replaced.
        if project in vectorstores:
            del vectorstores[project]
        proj_idx = os.path.join(INDEX_DIR, project)
        if os.path.exists(proj_idx):
            shutil.rmtree(proj_idx)
        total = 0
        for d in db.list_documents(project):
            fn = d.get("filename"); dp = d.get("path"); fid = d.get("folder_id")
            if not dp:
                continue
            jp = dp + ".index.json"; tp = dp + ".extracted.txt"; n = 0
            try:
                if os.path.isfile(jp):
                    with open(jp, "r", encoding="utf-8") as jf:
                        m = json.load(jf)
                    n = await run_in_threadpool(index_structured, project, m, fn, fid)
                if n == 0 and os.path.isfile(tp):
                    with open(tp, "r", encoding="utf-8") as tf:
                        c = tf.read()
                    if c.strip():
                        n = await run_in_threadpool(index_text, project, c, fn, fid)
                db.update_document_status(project, fn, n, "ready" if n > 0 else "extracted")
                total += n
            except Exception:
                logger.exception("reextract rebuild failed for " + str(fn))
        db.audit("document.reextract", project=project,
                 detail={"filename": filename, "vision_pages": meta.get("vision_pages"),
                         "chunks": total}, user=user, ip=_client_ip(request))
        return {"status": "ready", "vision_pages": meta.get("vision_pages"),
                "vision_errors": meta.get("vision_errors"),
                "pages": meta.get("page_count"), "chunks": total}
    except Exception as e:
        logger.exception("reextract failed for " + str(filename))
        return {"status": "error",
                "detail": "vision re-read failed - is Ollama running with the vision model? (%s)" % e}

@app.get("/projects/{project}/file")
async def project_file(project: str, rel: str, request: Request):
    user = auth.require_project(request, project)
    base = os.path.abspath(os.path.join(DOCS_DIR, project))
    target = os.path.abspath(os.path.join(base, rel))
    if target != base and not target.startswith(base + os.sep):
        raise HTTPException(400, "Invalid path")
    if not os.path.isfile(target):
        raise HTTPException(404, "File not found")
    # Folder-level RBAC: require_project only confirms PROJECT membership.
    # A restricted "user" (or a lead who isn't assigned every folder) must
    # also be assigned the specific folder this file lives in -- the same
    # rule list_documents() already applies to listings. Without this check,
    # knowing/guessing a relative path would bypass folder isolation entirely.
    allow_all, allowed_ids = db.folder_access(user, project)
    if not allow_all:
        folder_id = db.document_folder_id_for_path(project, target)
        if folder_id is None or folder_id not in (allowed_ids or set()):
            raise HTTPException(403, "You do not have access to this document")
    import mimetypes
    mt, _ = mimetypes.guess_type(target)
    return FileResponse(target, media_type=(mt or "application/octet-stream"),
                        headers={"Content-Disposition": 'inline; filename="%s"' % os.path.basename(target)})

@app.get("/projects/{project}/document")
async def project_document_json(project: str, rel: str, request: Request):
    user = auth.require_project(request, project)
    base = os.path.abspath(os.path.join(DOCS_DIR, project))
    target = os.path.abspath(os.path.join(base, rel + ".index.json"))
    if target != base and not target.startswith(base + os.sep):
        raise HTTPException(400, "Invalid path")
    if not os.path.isfile(target):
        raise HTTPException(404, "No structured data yet")
    # Folder-level RBAC -- see /projects/{project}/file above for why this is
    # needed in addition to require_project's project-membership check.
    allow_all, allowed_ids = db.folder_access(user, project)
    if not allow_all:
        source_path = os.path.abspath(os.path.join(base, rel))
        folder_id = db.document_folder_id_for_path(project, source_path)
        if folder_id is None or folder_id not in (allowed_ids or set()):
            raise HTTPException(403, "You do not have access to this document")
    import json as _json
    with open(target, encoding="utf-8") as f:
        return _json.load(f)

@app.get("/audit")
async def get_audit(request: Request, limit: int = 200, project: str = None):
    auth.require_roles(request, "admin")
    return {"entries": db.recent_audit(limit=limit, project=project)}

@app.get("/vision")
async def vision_status():
    ok, detail = await run_in_threadpool(vision.health)
    return {"ok": ok, **detail}

# ============================================================
# Admin: user permissions view + permission self-test
# ============================================================
@app.get("/admin/users/{uid}/permissions")
async def user_permissions(uid: int, request: Request):
    auth.require_roles(request, "admin")
    u = db.get_user(uid)
    if not u:
        raise HTTPException(404, "user not found")
    role = u["role"]
    if role == "admin":
        return {"user": u, "role": role, "full_access": True, "projects": []}
    out = []
    for pj in db.user_projects(uid):
        allow_all, ids = db.folder_access(u, pj)
        folders = db.list_folders(pj)
        vis = folders if allow_all else [f for f in folders if f["id"] in (ids or set())]
        out.append({"project": pj, "all_access": bool(allow_all),
                    "total_folders": len(folders),
                    "folders": [{"id": f["id"], "name": f["name"]} for f in vis]})
    return {"user": u, "role": role, "full_access": False, "projects": out}

@app.get("/admin/users/{uid}/projects/{project}/folders")
async def user_project_folders(uid: int, project: str, request: Request):
    auth.require_roles(request, "admin")
    u = db.get_user(uid)
    if not u:
        raise HTTPException(404, "user not found")
    allow_all, ids = db.folder_access(u, project)
    is_member = db.user_can_access(u, project)
    folders = db.list_folders(project)
    aset = ids or set()
    return {"project": project, "is_member": bool(is_member), "all_access": bool(allow_all),
            "folders": [{"id": f["id"], "name": f["name"],
                         "assigned": bool(allow_all or f["id"] in aset),
                         "doc_count": f.get("doc_count", 0)} for f in folders]}

@app.post("/admin/permission-test")
async def permission_test(request: Request):
    """Prove folder isolation: run the SAME retrieval the chat uses, as the target
    user, and confirm no document from an unauthorized folder is returned."""
    admin_user = auth.require_roles(request, "admin")
    body = await request.json()
    username = (body or {}).get("username")
    project = (body or {}).get("project")
    folder_id = (body or {}).get("folder_id")
    query = ((body or {}).get("query") or "").strip()
    if not username or not project:
        raise HTTPException(400, "username and project required")
    tgt = db.get_user_by_username(username)
    if not tgt:
        raise HTTPException(404, "user not found")
    target = {k: v for k, v in tgt.items() if k != "password_hash"}

    allow_all, ids = db.folder_access(target, project)
    allowed_ids = None if allow_all else set(ids or set())
    folders = db.list_folders(project)
    fmap = {f["id"]: f["name"] for f in folders}
    access = [{"id": f["id"], "name": f["name"],
               "allowed": bool(allow_all or f["id"] in (allowed_ids or set()))}
              for f in folders]

    result = {"status": "ok",
              "user": {"username": target["username"], "role": target["role"]},
              "project": project, "all_access": bool(allow_all), "folders": access}

    if folder_id is not None:
        result["folder_check"] = {
            "folder_id": folder_id, "folder": fmap.get(folder_id),
            "allowed": bool(allow_all or folder_id in (allowed_ids or set()))}

    if query:
        docfolder = db.doc_folder_map(project)
        # Retrieval AS THE TARGET USER (the real, enforced path):
        srcs, ctx = retrieve_context(project, query, 12, target)
        returned, leaked = [], []
        for sc in srcs:
            fn = sc.get("source")
            if fn in docfolder:  # a project document (folder-scoped)
                fid = docfolder.get(fn)
                ok = allow_all or (fid in (allowed_ids or set()))
                returned.append({"source": fn, "page": sc.get("page"),
                                 "folder": fmap.get(fid), "allowed": ok})
                if not ok:
                    leaked.append(fn)
            else:  # DBC/IBC code reference, not folder-restricted
                returned.append({"source": fn, "page": sc.get("page"),
                                 "folder": "(code reference)", "allowed": True})
        # For comparison: what a FULL-ACCESS admin would retrieve for the same query.
        admin_srcs, _ = retrieve_context(project, query, 12, None)
        admin_files = sorted({s.get("source") for s in admin_srcs if s.get("source") in docfolder})
        user_files = sorted({r["source"] for r in returned if r["folder"] != "(code reference)"})
        withheld = [f for f in admin_files if f not in user_files]
        result["probe"] = {
            "query": query,
            "returned": returned,
            "leaked": leaked,
            "context_empty": not bool(ctx.strip()),
            "admin_would_see": admin_files,
            "withheld_from_user": withheld,
            "pass": len(leaked) == 0,
        }
    db.audit("permission.test", project=project, target=username,
             detail={"query": bool(query), "folder_id": folder_id}, user=admin_user)
    return result


@app.post("/auth/login")
async def login(body: LoginReq, request: Request = None):
    # Phase 0: Rate limiting
    client_ip = _client_ip(request)
    if not _check_rate_limit(client_ip):
        raise HTTPException(429, "Too many login attempts. Please try again later.")
    try:
        u = auth.authenticate(body.username, body.password)
        if not u:
            db.audit("auth.fail", target=body.username, ip=_client_ip(request))
            raise HTTPException(401, "Invalid username or password")
        token = auth.make_token(u)
        db.audit("auth.login", target=u["username"], user=u, ip=_client_ip(request))
        projects = None if u["role"] == "admin" else db.user_projects(u["id"])
        must_change = auth.must_change_password(u)
        return {"token": str(token), "user": u, "projects": projects,
                "must_change_password": bool(must_change)}
    except HTTPException:
        raise
    except Exception as _le:
        import traceback as _tb
        try:
            with open(os.path.join(DATA_DIR, "login_error.log"), "w", encoding="utf-8") as _f:
                _f.write(_tb.format_exc())
        except Exception:
            pass
        logger.exception("login failed")
        raise

@app.get("/auth/me")
async def me(request: Request):
    u = auth.require_user(request)
    projects = None if u["role"] == "admin" else db.user_projects(u["id"])
    # Security fix: a session restored from a stored token (page reload) used
    # to never learn must_change_password -- only a fresh /auth/login response
    # carried it, and nothing in either UI read it anyway, so an admin left on
    # the seeded default password forever. Now both the UI fix (below) and
    # this field exist, and /auth/me carries it too so a reloaded session
    # still enforces it, not just the first login.
    must_change = auth.must_change_password(u)
    return {"user": u, "projects": projects, "must_change_password": bool(must_change)}

@app.post("/auth/change-password")
async def change_password(body: ChangePwReq, request: Request):
    u = auth.require_user(request)
    full = db.get_user_by_username(u["username"])
    if not full or not auth.verify_password(body.old_password, full.get("password_hash")):
        raise HTTPException(400, "Current password is incorrect")
    db.set_user_password(u["id"], auth.hash_password(body.new_password), by=u)
    return {"status": "ok"}

@app.get("/admin/users")
async def admin_list_users(request: Request):
    auth.require_roles(request, "admin")
    return {"users": db.list_users()}

@app.post("/admin/users")
async def admin_create_user(body: CreateUserReq, request: Request):
    u = auth.require_roles(request, "admin")
    try:
        created = db.create_user(body.username, auth.hash_password(body.password),
                                 role=body.role, full_name=body.full_name,
                                 email=body.email, by=u)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"user": created}

@app.post("/admin/users/{uid}/password")
async def admin_reset_password(uid: int, body: PasswordReq, request: Request):
    u = auth.require_roles(request, "admin")
    if not db.set_user_password(uid, auth.hash_password(body.password), by=u):
        raise HTTPException(404, "User not found")
    return {"status": "ok"}

@app.post("/admin/users/{uid}/role")
async def admin_set_role(uid: int, body: RoleReq, request: Request):
    u = auth.require_roles(request, "admin")
    try:
        if not db.set_user_role(uid, body.role, by=u):
            raise HTTPException(404, "User not found")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok"}

@app.post("/admin/users/{uid}/active")
async def admin_set_active(uid: int, body: ActiveReq, request: Request):
    u = auth.require_roles(request, "admin")
    if not db.set_user_active(uid, body.active, by=u):
        raise HTTPException(404, "User not found")
    return {"status": "ok"}

#: Standard upload-destination folders created automatically for every new
#: project, mirroring the V2 Design Workspace sidebar (Models / Drawings /
#: Documents / Schedules / Specifications / QA & Issues / Reports) so there is
#: always a matching folder to upload into right after project creation,
#: instead of the admin having to hand-create one (previously only "Architecture"
#: existed, and only if someone made it manually). "Codes & Standards" is
#: intentionally excluded -- that's the shared cross-project code KB (/kb/upload),
#: not a per-project folder; "Overview"/"Settings" aren't upload destinations.
DEFAULT_PROJECT_FOLDERS = ["Models", "Drawings", "Documents", "Schedules", "Specifications", "QA & Issues", "Reports"]

@app.post("/projects")
async def create_project(body: CreateProjectReq, request: Request):
    u = auth.require_roles(request, "admin", "lead")
    disc = disciplines.normalize(body.discipline) if body.discipline else None
    try:
        db.create_project(body.name, u, discipline=disc)
    except ValueError as e:
        raise HTTPException(400, str(e))
    for _fname in DEFAULT_PROJECT_FOLDERS:
        try:
            db.create_folder(body.name, _fname, by=u)
        except Exception as _fe:
            logger.warning("Could not auto-create default folder '{}' for {}: {}", _fname, body.name, _fe)
    return {"status": "ok", "project": body.name}

@app.get("/projects/{project}/members")
async def get_members(project: str, request: Request):
    u = auth.require_user(request)
    if not auth.can_manage_project(u, project):
        raise HTTPException(403, "Not permitted")
    return {"project": project, "members": db.project_members(project)}

@app.post("/projects/{project}/members")
async def add_member(project: str, body: MemberReq, request: Request):
    u = auth.require_user(request)
    if not auth.can_manage_project(u, project):
        raise HTTPException(403, "Not permitted")
    target = db.get_user_by_username(body.username)
    if not target:
        raise HTTPException(404, "User not found")
    db.assign_member(project, target["id"], by=u)
    return {"status": "ok"}

@app.delete("/projects/{project}/members/{uid}")
async def del_member(project: str, uid: int, request: Request):
    u = auth.require_user(request)
    if not auth.can_manage_project(u, project):
        raise HTTPException(403, "Not permitted")
    db.remove_member(project, uid, by=u)
    return {"status": "ok"}

@app.get("/projects/{project}/{chat_id}")
async def load_project(project: str, chat_id: str, request: Request = None):
    auth.require_project(request, project)
    data = db.load_chat(project, chat_id)
    if data is None: raise HTTPException(404, "Not found")
    return data

@app.get("/api/forensics/start/{project_id}/{document_id}")
async def start_forensics(project_id: str, document_id: str):
    import intelligence.forensic_engine as fe
    if project_id == "C3103": project_id = 3
    elif project_id == "C3085": project_id = 1
    elif project_id == "C3045": project_id = 2
    return fe.start_forensic_test(project_id, document_id)

@app.get("/api/forensics/status")
async def get_forensics_status():
    import intelligence.forensic_engine as fe
    return fe.get_forensic_status()

@app.get("/health")
async def health(project: str = "default"):
    has_docs = get_vectorstore(project) is not None
    return {"status":"ok","documents_indexed":has_docs,"model":"qwen2.5vl:32b","streaming":True,"db":True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
