"""
Validation Engine for Expo Design AI (Phase 4).

Manages finding lifecycle:
OPEN → REVIEW_REQUIRED → VERIFIED → RESOLDED
                                   → REJECTED
                                   → SUPERSEDED

Every finding has structured fields and human verification support.
"""
import datetime
import uuid
from typing import List, Optional, Dict, Any
from enum import Enum

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()

from intelligence.compliance import ComplianceFinding, ComplianceStatus, Severity


class FindingState(str, Enum):
    OPEN = "open"
    REVIEW_REQUIRED = "review_required"
    VERIFIED = "verified"
    REJECTED = "rejected"
    RESOLVED = "resolved"
    SUPERSEDED = "superseded"


class ValidationEngine:
    """
    Manages the finding lifecycle and human verification.
    """

    def __init__(self):
        self._findings: Dict[str, ComplianceFinding] = {}

    def create_finding(self, project_id: str, rule_id: str, title: str,
                       status: ComplianceStatus, severity: Severity = Severity.MEDIUM,
                       description: str = "", requirement: str = "",
                       actual_value: str = "", expected_value: str = "",
                       difference: str = "", calculation: str = "",
                       evidence: str = "", source_doc: str = "",
                       source_page: int = None, confidence: float = 0.0,
                       recommendation: str = "", discipline: str = "",
                       created_by: str = "system") -> ComplianceFinding:
        """Create a new finding."""
        finding = ComplianceFinding(
            finding_id=f"CF-{uuid.uuid4().hex[:8].upper()}",
            project_id=project_id,
            discipline=discipline,
            severity=severity,
            status=status,
            check_id=rule_id,
            title=title,
            description=description,
            requirement=requirement,
            actual_value=actual_value,
            expected_value=expected_value,
            difference=difference,
            calculation=calculation,
            rule_id=rule_id,
            evidence=evidence,
            source_doc=source_doc,
            source_page=source_page,
            confidence=confidence,
            recommendation=recommendation,
            created_by=created_by,
            created_at=datetime.datetime.utcnow().isoformat(),
            updated_at=datetime.datetime.utcnow().isoformat(),
            lifecycle_state=FindingState.OPEN,
            ai_generated=True,
            human_reviewed=False,
        )
        self._findings[finding.finding_id] = finding
        logger.info("Created finding: {} {} ({})",
                    finding.finding_id, status.value, title)
        return finding

    def get_finding(self, finding_id: str) -> Optional[ComplianceFinding]:
        """Get a finding by ID."""
        return self._findings.get(finding_id)

    def list_findings(self, project_id: str = "",
                      status: str = "",
                      severity: str = "",
                      discipline: str = "") -> List[ComplianceFinding]:
        """List findings with optional filters."""
        results = []
        for f in self._findings.values():
            if project_id and f.project_id != project_id:
                continue
            if status and f.status.value != status:
                continue
            if severity and f.severity.value != severity:
                continue
            if discipline and f.discipline != discipline:
                continue
            results.append(f)
        return results

    def verify_finding(self, finding_id: str, verified_by: str,
                       comment: str = "") -> bool:
        """Mark a finding as verified by a human."""
        finding = self._findings.get(finding_id)
        if not finding:
            return False
        finding.lifecycle_state = FindingState.VERIFIED
        finding.human_reviewed = True
        finding.verified_by = verified_by
        finding.updated_at = datetime.datetime.utcnow().isoformat()
        if comment:
            finding.comments.append({
                "author": verified_by,
                "text": comment,
                "timestamp": datetime.datetime.utcnow().isoformat(),
            })
        logger.info("Finding {} verified by {}", finding_id, verified_by)
        return True

    def reject_finding(self, finding_id: str, rejected_by: str,
                       comment: str = "") -> bool:
        """Reject a finding."""
        finding = self._findings.get(finding_id)
        if not finding:
            return False
        finding.lifecycle_state = FindingState.REJECTED
        finding.human_reviewed = True
        finding.verified_by = rejected_by
        finding.updated_at = datetime.datetime.utcnow().isoformat()
        if comment:
            finding.comments.append({
                "author": rejected_by,
                "text": comment,
                "timestamp": datetime.datetime.utcnow().isoformat(),
            })
        logger.info("Finding {} rejected by {}", finding_id, rejected_by)
        return True

    def resolve_finding(self, finding_id: str, resolved_by: str,
                        comment: str = "") -> bool:
        """Mark a finding as resolved."""
        finding = self._findings.get(finding_id)
        if not finding:
            return False
        finding.lifecycle_state = FindingState.RESOLVED
        finding.updated_at = datetime.datetime.utcnow().isoformat()
        if comment:
            finding.comments.append({
                "author": resolved_by,
                "text": comment,
                "timestamp": datetime.datetime.utcnow().isoformat(),
            })
        logger.info("Finding {} resolved by {}", finding_id, resolved_by)
        return True

    def add_comment(self, finding_id: str, author: str, comment: str) -> bool:
        """Add a comment to a finding."""
        finding = self._findings.get(finding_id)
        if not finding:
            return False
        finding.comments.append({
            "author": author,
            "text": comment,
            "timestamp": datetime.datetime.utcnow().isoformat(),
        })
        finding.updated_at = datetime.datetime.utcnow().isoformat()
        return True

    def get_stats(self, project_id: str = "") -> Dict[str, Any]:
        """Get finding statistics."""
        findings = self.list_findings(project_id=project_id)
        stats = {
            "total": len(findings),
            "by_status": {},
            "by_severity": {},
            "by_state": {},
            "ai_generated": 0,
            "human_verified": 0,
        }
        for f in findings:
            status = f.status.value
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
            severity = f.severity.value
            stats["by_severity"][severity] = stats["by_severity"].get(severity, 0) + 1
            state = f.lifecycle_state
            stats["by_state"][state] = stats["by_state"].get(state, 0) + 1
            if f.ai_generated:
                stats["ai_generated"] += 1
            if f.human_reviewed:
                stats["human_verified"] += 1
        return stats


# Singleton instance
_validation_engine = ValidationEngine()


def get_validation_engine() -> ValidationEngine:
    """Get the global validation engine instance."""
    return _validation_engine
