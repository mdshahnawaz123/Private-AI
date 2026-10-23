"""
FastAPI Router for /api/v1 endpoints.
Extracted from main.py for modularity and production maintainability.
"""
import os
import datetime
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from loguru import logger

import db
import auth
from core.model_registry import get_registry
from knowledge.hub import get_hub
from knowledge.graph import get_graph
from knowledge.provenance import get_tracker
from knowledge.precedence import get_precedence
from services.ingestion import get_pipeline, DocumentState
from intelligence.retrieval import get_retriever
from intelligence.compliance import get_engine as get_compliance_engine, ComplianceStatus, Severity
from intelligence.validation import get_validation_engine, FindingState
from engines.ocr_engine import get_ocr_engine
from engines.layout_engine import get_layout_engine
from engines.drawing_engine import get_drawing_engine
from agents.runtime import get_runtime
from agents.tools import get_registry as get_tool_registry, ToolPermission
from engines.ifc_engine import get_ifc_engine
from services.bim_service import get_bim_service
from intelligence.reports import get_report_engine
from core.observability import get_observability

DATA_DIR = db.DATA_DIR

model_registry = get_registry()
knowledge_hub = get_hub()
knowledge_graph = get_graph()
provenance_tracker = get_tracker()
source_precedence = get_precedence()
ingestion_pipeline = get_pipeline()
hybrid_retriever = get_retriever()
compliance_engine = get_compliance_engine()
validation_engine = get_validation_engine()
ocr_engine = get_ocr_engine()
layout_engine = get_layout_engine()
drawing_engine = get_drawing_engine()
agent_runtime = get_runtime()
tool_registry = get_tool_registry()
ifc_engine = get_ifc_engine()
bim_service = get_bim_service()
report_engine = get_report_engine()
observability = get_observability()

def _require_legacy_api_admin(request: Request):
    auth.require_roles(request, "admin")

api_v1 = APIRouter(prefix="/api/v1", dependencies=[Depends(_require_legacy_api_admin)])

@api_v1.get("/models")
async def list_models():
    """List all registered AI models."""
    return {"models": model_registry.list_models()}


@api_v1.get("/models/health")
async def models_health():
    """Check health of all AI models."""
    return model_registry.health_check()


# ── ToolDesk Capability Matrix & Vault (craft-ai-integrations pattern) ──
@api_v1.get("/tooldesk/matrix")
async def tooldesk_matrix():
    """Return the full capability matrix cross-referencing tools against models."""
    from core.tooldesk import get_tooldesk
    return get_tooldesk().audit_matrix()


@api_v1.get("/tooldesk/resolve/{tool_name}")
async def tooldesk_resolve_tool(tool_name: str, preferred_role: str = ""):
    """Resolve the optimal model and verify prerequisites for a specific tool."""
    from core.tooldesk import get_tooldesk
    return get_tooldesk().resolve_model_for_tool(tool_name, preferred_role=preferred_role or None)


@api_v1.get("/tooldesk/vault-status")
async def tooldesk_vault_status():
    """Return DPAPI native credential vault diagnostics (inspired by craft-ai-native)."""
    from core.credential_vault import get_vault
    return get_vault().get_status()


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
    document=next((d for d in db.list_documents(project,user) if d['filename']==filename),None)
    if not document:
        raise HTTPException(404,'Document not found')
    if document.get('status') not in ('ready','ready_with_warnings','review_required','verified','published') or not document.get('chunks'):
        raise HTTPException(409,'Complete extraction and index publication before verifying')
    from services.jobs import source_hash
    db.update_document_status(project, filename, document['chunks'], DocumentState.VERIFIED)
    db.audit("document.verify", project=project, target=filename, user=user,
             detail={'human_review_asserted':True,'source_sha256':source_hash(document['path'])})
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
    document=next((d for d in db.list_documents(project,user) if d['filename']==filename),None)
    if not document:raise HTTPException(404,'Document not found')
    db.update_document_status(project, filename, document['chunks'], DocumentState.ARCHIVED)
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
    from intelligence.reranker import get_reranker
    import sys as _sys
    _main = _sys.modules.get("main") or _sys.modules["__main__"]
    return {
        "bm25_indexed_docs": len(hybrid_retriever._documents),
        "reranker_enabled": get_reranker().is_enabled(),
        "vector_stores_cached": len(_main.vectorstores),
    }


@api_v1.post("/retrieval/search")
async def retrieval_search(request: Request, project: str = "default",
                           query: str = "", k: int = 8):
    """Search using hybrid retrieval (BM25 + Vector + RRF + Reranker)."""
    user = auth.require_project(request, project)
    if not query:
        raise HTTPException(400, "Query required")
    import sys as _sys
    _main = _sys.modules.get("main") or _sys.modules["__main__"]
    vs = _main.get_vectorstore(project)
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
    format = {'excel': 'xlsx', 'word': 'docx'}.get(format, format)
    discipline = body.get("discipline", "")
    if format not in ('pdf', 'xlsx', 'docx'):
        raise HTTPException(400, 'Supported report formats: pdf, xlsx, docx')

    # Gather data based on report type
    if report_type == "compliance":
        from intelligence.reports import project_findings
        findings = project_findings(validation_engine._findings.values(), project)
        findings = [f.__dict__ if hasattr(f, '__dict__') else f for f in findings]
        report = report_engine.generate_compliance_report(
            project_id=project,
            findings=findings,
            discipline=discipline,
            created_by=user["username"],
        )
    elif report_type == "bim_qa":
        bim_stats = bim_service.get_stats(project_id=project)
        from intelligence.reports import project_findings
        findings = project_findings(validation_engine._findings.values(), project)
        findings = [f.__dict__ if hasattr(f, '__dict__') else f for f in findings]
        report = report_engine.generate_bim_qa_report(
            project_id=project,
            bim_stats=bim_stats,
            findings=findings,
            created_by=user["username"],
        )
    elif report_type == "issue_register":
        from intelligence.reports import project_findings
        findings = project_findings(validation_engine._findings.values(), project)
        findings = [f.__dict__ if hasattr(f, '__dict__') else f for f in findings]
        report = report_engine.generate_issue_register(
            project_id=project,
            findings=findings,
            created_by=user["username"],
        )
    else:
        raise HTTPException(400, f"Unknown report type: {report_type}")

    # Export to file
    from intelligence.reports import project_report_directory
    output_dir = project_report_directory(DATA_DIR, project)
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
    from intelligence.reports import project_report_directory
    try:
        reports_dir = project_report_directory(DATA_DIR, project)
    except (ValueError, RuntimeError):
        raise HTTPException(400, 'Invalid report project')
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



api_v1_router = api_v1
