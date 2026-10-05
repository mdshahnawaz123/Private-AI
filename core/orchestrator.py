"""
AI Orchestrator for Expo Design AI (Phase 0 skeleton).

Core architectural component that:
1. Understands the user's request
2. Classifies the task
3. Determines required evidence
4. Selects appropriate data sources
5. Selects the appropriate local AI model
6. Executes deterministic calculations where appropriate
7. Retrieves relevant evidence
8. Sends only relevant evidence to the LLM
9. Verifies citations
10. Produces a structured response

This is a SKELETON — it provides the interface and basic structure.
Full implementation happens in Phase 3.
"""
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


# ── Query classification ────────────────────────────────────
class QueryType:
    GENERAL_QA = "general_qa"
    COMPLIANCE_CHECK = "compliance_check"
    DRAWING_REVIEW = "drawing_review"
    SCHEDULE_REVIEW = "schedule_review"
    BIM_QA = "bom_qa"
    COMPARISON = "comparison"
    CALCULATION = "calculation"
    REPORT_REQUEST = "report_request"


@dataclass
class ClassifiedQuery:
    query_type: str
    confidence: float
    discipline: Optional[str] = None
    requires_vision: bool = False
    requires_bim: bool = False
    requires_code: bool = False
    requires_drawings: bool = False
    requires_schedules: bool = False
    complexity: str = "medium"  # low, medium, high
    keywords: List[str] = field(default_factory=list)


@dataclass
class Evidence:
    """Typed evidence object."""
    source_type: str  # code, drawing, schedule, bim, document
    content: str
    source_doc: str
    page: Optional[int] = None
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StructuredAnswer:
    """Structured response from the orchestrator."""
    answer: str
    query_type: str
    evidence: List[Evidence]
    calculation: Optional[str] = None
    status: Optional[str] = None  # PASS, FAIL, REVIEW
    confidence: float = 0.0
    sources: List[Dict[str, Any]] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)


# ── Orchestrator interface ──────────────────────────────────
class OrchestratorInterface(ABC):
    """Abstract interface for the AI Orchestrator."""

    @abstractmethod
    def classify(self, query: str, discipline: str = "") -> ClassifiedQuery:
        ...

    @abstractmethod
    def gather_evidence(self, classified: ClassifiedQuery, project: str,
                        user: Optional[dict] = None) -> List[Evidence]:
        ...

    @abstractmethod
    def select_model(self, classified: ClassifiedQuery) -> str:
        ...

    @abstractmethod
    def verify_citations(self, answer: str, evidence: List[Evidence]) -> bool:
        ...

    @abstractmethod
    def process(self, query: str, project: str, user: Optional[dict] = None,
                discipline: str = "", messages: List[dict] = None) -> StructuredAnswer:
        ...


# ── Basic orchestrator implementation (Phase 0 skeleton) ────
class BasicOrchestrator(OrchestratorInterface):
    """
    Basic orchestrator implementation.
    Phase 0: Classification + model routing only.
    Phase 3: Full evidence assembly + deterministic checks + verification.
    """

    # Keywords for query classification
    COMPLIANCE_KEYWORDS = [
        "comply", "compliant", "compliance", "code", "requirement",
        "required", "minimum", "maximum", "allowed", "permitted",
        "violation", "violates", "pass", "fail", "review",
    ]
    DRAWING_KEYWORDS = [
        "drawing", "plan", "elevation", "section", "detail",
        "dimension", "level", "grid", "sheet",
    ]
    SCHEDULE_KEYWORDS = [
        "schedule", "door schedule", "window schedule", "room schedule",
        "finish schedule", "quantity", "count",
    ]
    BIM_KEYWORDS = [
        "bim", "model", "ifc", "revit", "element", "column", "beam",
        "wall", "slab", "floor", "storey", "level",
    ]
    COMPARISON_KEYWORDS = [
        "compare", "comparison", "difference", "diff", "versus", "vs",
        "revision", "change", "changed",
    ]
    CALCULATION_KEYWORDS = [
        "calculate", "calculation", "compute", "area", "volume",
        "quantity", "how much", "how many",
    ]
    REPORT_KEYWORDS = [
        "report", "generate", "export", "pdf", "document",
    ]

    def __init__(self):
        self._model_registry = None

    @property
    def model_registry(self):
        if self._model_registry is None:
            from core.model_registry import get_registry
            self._model_registry = get_registry()
        return self._model_registry

    def classify(self, query: str, discipline: str = "") -> ClassifiedQuery:
        """Classify the user's query type."""
        q = (query or "").lower()
        scores = {
            QueryType.COMPLIANCE_CHECK: 0,
            QueryType.DRAWING_REVIEW: 0,
            QueryType.SCHEDULE_REVIEW: 0,
            QueryType.BIM_QA: 0,
            QueryType.COMPARISON: 0,
            QueryType.CALCULATION: 0,
            QueryType.REPORT_REQUEST: 0,
            QueryType.GENERAL_QA: 0,
        }

        for kw in self.COMPLIANCE_KEYWORDS:
            if kw in q:
                scores[QueryType.COMPLIANCE_CHECK] += 1
        for kw in self.DRAWING_KEYWORDS:
            if kw in q:
                scores[QueryType.DRAWING_REVIEW] += 1
        for kw in self.SCHEDULE_KEYWORDS:
            if kw in q:
                scores[QueryType.SCHEDULE_REVIEW] += 1
        for kw in self.BIM_KEYWORDS:
            if kw in q:
                scores[QueryType.BIM_QA] += 1
        for kw in self.COMPARISON_KEYWORDS:
            if kw in q:
                scores[QueryType.COMPARISON] += 1
        for kw in self.CALCULATION_KEYWORDS:
            if kw in q:
                scores[QueryType.CALCULATION] += 1
        for kw in self.REPORT_KEYWORDS:
            if kw in q:
                scores[QueryType.REPORT_REQUEST] += 1

        # Pick highest score
        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]

        # If no keywords match, default to general QA
        if best_score == 0:
            best_type = QueryType.GENERAL_QA
            confidence = 0.5
        else:
            total = sum(scores.values())
            confidence = best_score / total if total > 0 else 0.5

        # Determine requirements
        requires_vision = best_type in (QueryType.DRAWING_REVIEW, QueryType.COMPLIANCE_CHECK)
        requires_bim = best_type == QueryType.BIM_QA
        requires_code = best_type in (QueryType.COMPLIANCE_CHECK, QueryType.CALCULATION)
        requires_drawings = best_type in (QueryType.DRAWING_REVIEW, QueryType.COMPLIANCE_CHECK)
        requires_schedules = best_type == QueryType.SCHEDULE_REVIEW

        # Complexity estimation
        complexity = "low"
        if best_score > 5 or len(q) > 200:
            complexity = "high"
        elif best_score > 2:
            complexity = "medium"

        return ClassifiedQuery(
            query_type=best_type,
            confidence=confidence,
            discipline=discipline or None,
            requires_vision=requires_vision,
            requires_bim=requires_bim,
            requires_code=requires_code,
            requires_drawings=requires_drawings,
            requires_schedules=requires_schedules,
            complexity=complexity,
            keywords=[kw for kw in self.COMPLIANCE_KEYWORDS + self.DRAWING_KEYWORDS
                      + self.SCHEDULE_KEYWORDS + self.BIM_KEYWORDS if kw in q],
        )

    def gather_evidence(self, classified: ClassifiedQuery, project: str,
                        user: Optional[dict] = None) -> List[Evidence]:
        """
        Gather relevant evidence for the query.
        Phase 0: Returns empty list — full implementation in Phase 3.
        """
        # Phase 3 will implement:
        # - Code requirement retrieval
        # - Drawing evidence retrieval
        # - Schedule data retrieval
        # - BIM element retrieval
        # - Document text retrieval
        logger.info("gather_evidence called for type={} project={} (Phase 0 skeleton)",
                    classified.query_type, project)
        return []

    def select_model(self, classified: ClassifiedQuery) -> str:
        """Select the appropriate AI model for the task."""
        requires_vision = classified.requires_vision
        complexity = classified.complexity

        config = self.model_registry.route(
            task_type="chat",
            complexity=complexity,
            requires_vision=requires_vision,
            latency_requirement="normal",
        )

        if config:
            logger.info("Selected model: role={} name={}", config.role, config.name)
            return config.name

        # Fallback to default
        return "qwen2.5vl:7b"

    def verify_citations(self, answer: str, evidence: List[Evidence]) -> bool:
        """
        Verify that citations in the answer match the evidence.
        Phase 0: Always returns True — full implementation in Phase 3.
        """
        return True

    def process(self, query: str, project: str, user: Optional[dict] = None,
                discipline: str = "", messages: List[dict] = None) -> StructuredAnswer:
        """
        Process a user query through the orchestration pipeline.
        Phase 0: Classification + model selection only.
        Phase 3: Full pipeline with evidence, calculation, verification.
        """
        # Step 1: Classify
        classified = self.classify(query, discipline)
        logger.info("Query classified as: {} (confidence={:.2f})",
                    classified.query_type, classified.confidence)

        # Step 2: Select model
        model_name = self.select_model(classified)

        # Step 3: Gather evidence (Phase 3)
        evidence = self.gather_evidence(classified, project, user)

        # Phase 3 will add:
        # - Deterministic calculations
        # - LLM reasoning with evidence
        # - Citation verification
        # - Structured response assembly

        return StructuredAnswer(
            answer="",  # Phase 3 will generate
            query_type=classified.query_type,
            evidence=evidence,
            confidence=classified.confidence,
        )


# ── Singleton instance ──────────────────────────────────────
_orchestrator = BasicOrchestrator()


def get_orchestrator() -> BasicOrchestrator:
    """Get the global orchestrator instance."""
    return _orchestrator
