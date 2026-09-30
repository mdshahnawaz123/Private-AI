"""
Provenance tracking for the Engineering Knowledge Hub.

Every engineering fact must maintain provenance — the ability to answer:
"Where did this information come from?"
"""
import datetime
from typing import Optional, Dict, Any

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


class ProvenanceTracker:
    """Tracks and manages provenance for all extracted information."""

    def __init__(self):
        self._provenance_store = {}

    def create(self, source_doc: str, source_page: Optional[int] = None,
               source_clause: str = "", source_type: str = "",
               extraction_method: str = "", confidence: str = "medium",
               confidence_score: float = 0.0, extracted_by: str = "",
               version: str = "") -> Dict[str, Any]:
        """Create a provenance record."""
        now = datetime.datetime.utcnow().isoformat()
        return {
            "source_doc": source_doc,
            "source_page": source_page,
            "source_clause": source_clause,
            "source_type": source_type,
            "extraction_method": extraction_method,
            "confidence": confidence,
            "confidence_score": confidence_score,
            "extracted_by": extracted_by,
            "extracted_at": now,
            "verified_by": None,
            "verified_at": None,
            "version": version,
        }

    def verify(self, provenance: Dict[str, Any], verified_by: str) -> Dict[str, Any]:
        """Mark a provenance record as verified by a human."""
        provenance["verified_by"] = verified_by
        provenance["verified_at"] = datetime.datetime.utcnow().isoformat()
        return provenance

    def is_verified(self, provenance: Dict[str, Any]) -> bool:
        """Check if a provenance record has been verified."""
        return provenance.get("verified_by") is not None

    def get_confidence_level(self, provenance: Dict[str, Any]) -> str:
        """Get the confidence level of a provenance record."""
        if self.is_verified(provenance):
            return "high"
        return provenance.get("confidence", "unknown")

    def format_for_display(self, provenance: Dict[str, Any]) -> str:
        """Format provenance for display in UI."""
        parts = []
        if provenance.get("source_doc"):
            parts.append(f"Source: {provenance['source_doc']}")
        if provenance.get("source_page"):
            parts.append(f"Page: {provenance['source_page']}")
        if provenance.get("source_clause"):
            parts.append(f"Clause: {provenance['source_clause']}")
        if provenance.get("confidence"):
            parts.append(f"Confidence: {provenance['confidence']}")
        if provenance.get("verified_by"):
            parts.append(f"Verified by: {provenance['verified_by']}")
        return " | ".join(parts)

    def format_for_citation(self, provenance: Dict[str, Any]) -> str:
        """Format provenance as a citation string."""
        parts = []
        if provenance.get("source_doc"):
            parts.append(provenance["source_doc"])
        if provenance.get("source_page"):
            parts.append(f"p. {provenance['source_page']}")
        if provenance.get("source_clause"):
            parts.append(f"§ {provenance['source_clause']}")
        return ", ".join(parts) if parts else "Unknown source"


# Singleton instance
_tracker = ProvenanceTracker()


def get_tracker() -> ProvenanceTracker:
    """Get the global provenance tracker instance."""
    return _tracker
