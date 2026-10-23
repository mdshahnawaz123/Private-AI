"""
Unified query routing service for Expo Design AI.
Routes questions across deterministic exact tables, structured records,
DocumentMemory, model BIM tools, and guarded RAG context retrieval.
Shared by both /ask_stream and /api/query_document to guarantee identical,
verified answers across streaming and batch endpoints.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
import os
import re

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()

import db
from intelligence.answer_publication import validate_precomputed_answer
from intelligence.document_query import robust_parse_query, execute_structured_query


@dataclass
class RouteResult:
    route: str  # 'source_table', 'structured', 'document_memory', 'model_qa', 'rag'
    status: str  # 'SUCCESS', 'NOT_FOUND', 'AMBIGUOUS', 'ERROR', 'UNVERIFIED'
    answer: str = ""
    is_deterministic: bool = False
    sources: List[Dict[str, Any]] = field(default_factory=list)
    provenance: List[Dict[str, Any]] = field(default_factory=list)
    query_plan: Optional[Dict[str, Any]] = None
    viewer_action: Optional[Dict[str, Any]] = None
    data: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    context: str = ""
    retrieved_sources: List[Dict[str, Any]] = field(default_factory=list)


class QueryRouter:
    """
    Central query routing engine.
    Ensures both /ask_stream and /api/query_document follow the exact same
    decision tree and verification rules.
    """

    @staticmethod
    def route_query(
        project: str,
        question: str,
        user: Optional[Dict[str, Any]] = None,
        exact_documents: Optional[List[Dict[str, Any]]] = None,
        selected_guid: Optional[str] = None,
        focus_doc: Optional[str] = None,
        retrieve_context_func: Optional[Callable] = None,
        focused_sources: Optional[Dict[str, Any]] = None,
        db_module: Any = None,
    ) -> RouteResult:
        """
        Determine the route and resolve precomputed/deterministic answers if available.
        If a deterministic route succeeds, returns RouteResult with is_deterministic=True.
        Otherwise falls back to RAG, retrieving context and returning RouteResult with route='rag'.
        """
        _db = db_module or db
        pid, name = None, None
        try:
            with _db.SessionLocal() as session:
                query = session.query(_db.Project)
                row = query.filter_by(id=project).first() if isinstance(project, int) else query.filter_by(name=project).first()
                if row:
                    pid, name = row.id, getattr(row, "name", str(project))
        except Exception:
            pass

        if pid is None:
            pid = project if isinstance(project, int) else 1
            name = str(project)

        if exact_documents is not None:
            docs = exact_documents
        elif hasattr(_db, "list_documents"):
            docs = _db.list_documents(name, user)
        else:
            docs = db.list_documents(name, user)

        # 0. Deterministic CAD / Masterplan view commands and plot queries
        try:
            from services.masterplan.view_commands import parse_view_command
            cad_action = parse_view_command(question)
        except Exception:
            cad_action = None

        if cad_action:
            act_type = cad_action.get("type")
            if act_type == "clarification_needed":
                return RouteResult(
                    route="cad_view",
                    status="AMBIGUOUS",
                    answer=cad_action.get("question", "Could you please clarify your request?"),
                    is_deterministic=True,
                )
            if act_type == "get_plot_details":
                try:
                    from services.masterplan import db as mp_db
                    plot = mp_db.get_plot(name or pid, cad_action.get("plot_id"))
                    if not plot and pid != name:
                        plot = mp_db.get_plot(pid, cad_action.get("plot_id"))
                    if not plot:
                        for p in mp_db.get_plots(name or pid):
                            if str(cad_action.get("raw_id")) == p.plot_id.upper().removeprefix("P-"):
                                plot = p
                                break
                    if plot:
                        from services.masterplan.plot_answers import plot_answer
                        ans, sources = plot_answer(plot, mp_db.get_file_records(name or pid))
                        return RouteResult(route="masterplan_plot", status="SUCCESS", answer=ans,
                            is_deterministic=True, sources=sources, provenance=sources,
                            data=plot.model_dump() if hasattr(plot, "model_dump") else {})
                except Exception as e:
                    logger.warning(f"Plot lookup failed in query router: {e}")

            if act_type in ("edit_hatches", "set_text_mode", "return_to_original",
                            "save_working_copy", "isolate_land_use", "set_text_scale", "fit_view", "recolor_active"):
                # This is a proposal. Only the client/engine receipt may say it was applied.
                return RouteResult(route="cad_view", status="SUCCESS",
                    answer="Drawing action requested.", is_deterministic=True,
                    viewer_action=cad_action, data={"action_status": "pending"})

        # 1. Exact deterministic table answers
        try:
            import sys
            _ea = sys.modules.get("intelligence.exact_answers")
            if _ea is None:
                import intelligence.exact_answers as _ea
            exact = _ea.exact_answer(question, docs)
        except Exception:
            exact = None

        if exact and exact.get("status") == "SUCCESS":
            raw_ans = exact.get("answer", "")
            raw_srcs = exact.get("sources", [])
            try:
                ans, issues, src_items = validate_precomputed_answer(raw_ans, docs, raw_srcs, question)
            except Exception:
                logger.exception("Exact-answer publication validation failed; withholding answer")
                ans = "I could not verify the deterministic answer against its source pages. Please review the source document."
                issues = ["Exact-answer publication validation failed"]
                src_items = []

            if issues:
                logger.warning("Exact answer withheld by final evidence checks: {}", issues)
                return RouteResult(
                    route="source_table",
                    status="UNVERIFIED",
                    answer="I could not verify the deterministic answer against its source pages. Please review the source document.",
                    is_deterministic=True,
                    sources=[],
                    provenance=[],
                    warnings=issues,
                )

            return RouteResult(
                route="source_table",
                status="SUCCESS",
                answer=ans,
                is_deterministic=True,
                sources=src_items,
                provenance=src_items,
            )

        # 2. 3D Model / BIM QA tool routing if GUID is selected
        if selected_guid and re.search(r'\b(selected|highlight|isolate|zoom|guid)\b', question, re.I):
            return RouteResult(
                route="model_qa",
                status="SUCCESS",
                is_deterministic=False,  # Needs model execution
            )

        # 3. Structured Record Query (database tables / fields)
        plan = robust_parse_query(question, pid)
        if plan.get("route_target") == "structured":
            struct_res, _ = execute_structured_query(plan, pid, question, user)
            if struct_res.get("status") in ("SUCCESS", "AMBIGUOUS"):
                ans = struct_res.get("answer", "")
                prov = struct_res.get("provenance", [])
                src_items = [{"source": p.get("document"), "page": p.get("page"), "revision": p.get("revision")} for p in prov]
                if struct_res.get("status") == "SUCCESS":
                    try:
                        val_ans, issues, val_srcs = validate_precomputed_answer(ans, docs, src_items, question)
                        if issues:
                            return RouteResult(
                                route="structured",
                                status="UNVERIFIED",
                                answer=val_ans or "I could not verify the retrieved value against verified document sources.",
                                is_deterministic=True,
                                sources=[],
                                provenance=prov,
                                query_plan=plan,
                                warnings=issues,
                            )
                        ans = val_ans
                        src_items = val_srcs
                    except Exception as e:
                        logger.warning("Structured query publication validation error: {}", e)
                        return RouteResult(
                            route="structured",
                            status="UNVERIFIED",
                            answer="I could not verify the retrieved value against verified document sources.",
                            is_deterministic=True,
                            sources=[],
                            provenance=prov,
                            query_plan=plan,
                            warnings=[f"Validation error: {e}"],
                        )
                return RouteResult(
                    route="structured",
                    status=struct_res.get("status"),
                    answer=ans,
                    is_deterministic=True,
                    sources=src_items,
                    provenance=prov,
                    query_plan=plan,
                )

        # 4. AI Document Memory
        try:
            import sys
            _cfg = sys.modules.get("config")
            if _cfg is None:
                import config as _cfg
            if _cfg.get_settings().enable_document_memory:
                _dm = sys.modules.get("intelligence.document_memory")
                if _dm is None:
                    import intelligence.document_memory as _dm
                permitted_fn = {d["filename"] for d in docs if isinstance(d, dict) and d.get("filename")}
                focus_fn = os.path.basename(focus_doc.replace(chr(92), "/")) if focus_doc else None
                mem = _dm.memory_lookup(pid, question, permitted_fn, focus_fn)
                if mem and (mem.get("status", "SUCCESS") == "SUCCESS" or "answer" in mem):
                    raw_ans = mem.get("answer", "")
                    raw_srcs = mem.get("sources", [])
                    try:
                        ans, issues, src_items = validate_precomputed_answer(raw_ans, docs, raw_srcs, question)
                    except Exception:
                        logger.exception("Document-memory publication validation failed; withholding answer")
                        ans = "I could not verify the retrieved answer against its source pages. Please review the source document."
                        issues = ["Document-memory publication validation failed"]
                        src_items = []
                    if issues:
                        logger.warning("Document-memory answer withheld by final evidence checks: {}", issues)
                        return RouteResult(
                            route="document_memory",
                            status="UNVERIFIED",
                            answer="I could not verify the retrieved answer against its source pages. Please review the source document.",
                            is_deterministic=True,
                            sources=[],
                            provenance=[],
                            warnings=issues,
                        )
                    return RouteResult(
                        route="document_memory",
                        status="SUCCESS",
                        answer=ans,
                        is_deterministic=True,
                        sources=src_items,
                        provenance=src_items,
                    )
        except Exception as e:
            logger.warning("Document memory lookup skipped in QueryRouter: {}", e)

        # 5. RAG Retrieval
        if retrieve_context_func:
            try:
                srcs, ctx = retrieve_context_func(name, question, 8, user, focused_sources)
                return RouteResult(
                    route="rag",
                    status="SUCCESS",
                    is_deterministic=False,
                    retrieved_sources=srcs,
                    context=ctx,
                )
            except Exception as e:
                return RouteResult(
                    route="rag",
                    status="ERROR",
                    answer="Retrieval failed.",
                    is_deterministic=True,
                    warnings=[str(e)],
                )

        return RouteResult(
            route="rag",
            status="SUCCESS",
            is_deterministic=False,
        )
