"""
Deterministic Compliance Engine for Expo Design AI (Phase 4).

CRITICAL: DO NOT allow an LLM alone to determine engineering compliance.

Pipeline:
CODE REQUIREMENT + DRAWING/MODEL EVIDENCE + DETERMINISTIC RULE = PASS / FAIL / REVIEW

The AI explains the finding — it does not determine it.
"""
import re
import json
import datetime
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


class ComplianceStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    REVIEW = "REVIEW"
    NOT_APPLICABLE = "N/A"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class ComplianceFinding:
    """A structured compliance finding."""
    finding_id: str = ""
    project_id: str = ""
    discipline: str = ""
    severity: Severity = Severity.MEDIUM
    status: ComplianceStatus = ComplianceStatus.REVIEW
    check_id: str = ""
    title: str = ""
    description: str = ""
    requirement: str = ""
    actual_value: str = ""
    expected_value: str = ""
    difference: str = ""
    calculation: str = ""
    rule_id: str = ""
    evidence: str = ""
    source_doc: str = ""
    source_page: Optional[int] = None
    confidence: float = 0.0
    recommendation: str = ""
    created_by: str = "system"
    verified_by: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    revision: str = ""
    # Lifecycle
    lifecycle_state: str = "open"  # open, review_required, verified, rejected, resolved, superseded
    ai_generated: bool = True
    human_reviewed: bool = False
    comments: List[Dict[str, str]] = field(default_factory=list)


class ComplianceRule:
    """
    A deterministic compliance rule.
    Rules are version-controlled and independent from LLMs.
    """

    def __init__(self, rule_id: str, name: str, description: str,
                 rule_type: str, parameters: Dict[str, Any]):
        self.rule_id = rule_id
        self.name = name
        self.description = description
        self.rule_type = rule_type
        self.parameters = parameters

    def evaluate(self, actual_value: Any, context: Dict[str, Any] = None) -> ComplianceFinding:
        """
        Evaluate the rule against an actual value.
        Returns a ComplianceFinding with PASS/FAIL/REVIEW.
        """
        context = context or {}

        if self.rule_type == "minimum":
            return self._evaluate_minimum(actual_value, context)
        elif self.rule_type == "maximum":
            return self._evaluate_maximum(actual_value, context)
        elif self.rule_type == "equals":
            return self._evaluate_equals(actual_value, context)
        elif self.rule_type == "range":
            return self._evaluate_range(actual_value, context)
        elif self.rule_type == "contains":
            return self._evaluate_contains(actual_value, context)
        elif self.rule_type == "custom":
            return self._evaluate_custom(actual_value, context)
        else:
            return ComplianceFinding(
                status=ComplianceStatus.REVIEW,
                rule_id=self.rule_id,
                title=self.name,
                description=f"Unknown rule type: {self.rule_type}",
            )

    def _evaluate_minimum(self, actual_value: Any, context: Dict[str, Any]) -> ComplianceFinding:
        """Evaluate minimum value rule."""
        threshold = self.parameters.get("threshold")
        unit = self.parameters.get("unit", "")

        if actual_value is None:
            return ComplianceFinding(
                status=ComplianceStatus.REVIEW,
                rule_id=self.rule_id,
                title=self.name,
                description=self.description,
                expected_value=f">= {threshold} {unit}",
                actual_value="Not provided",
                recommendation="Provide the required value for verification",
            )

        try:
            actual = float(actual_value)
            threshold_val = float(threshold)
        except (ValueError, TypeError):
            return ComplianceFinding(
                status=ComplianceStatus.REVIEW,
                rule_id=self.rule_id,
                title=self.name,
                description=self.description,
                expected_value=f">= {threshold} {unit}",
                actual_value=str(actual_value),
                recommendation="Value could not be parsed as a number",
            )

        if actual >= threshold_val:
            return ComplianceFinding(
                status=ComplianceStatus.PASS,
                rule_id=self.rule_id,
                title=self.name,
                description=self.description,
                expected_value=f">= {threshold} {unit}",
                actual_value=f"{actual} {unit}",
                calculation=f"{actual} >= {threshold_val} → PASS",
                confidence=1.0,
            )
        else:
            diff = threshold_val - actual
            return ComplianceFinding(
                status=ComplianceStatus.FAIL,
                rule_id=self.rule_id,
                title=self.name,
                description=self.description,
                severity=Severity.HIGH,
                expected_value=f">= {threshold} {unit}",
                actual_value=f"{actual} {unit}",
                difference=f"{diff} {unit}",
                calculation=f"{actual} < {threshold_val} → FAIL (shortfall: {diff} {unit})",
                confidence=1.0,
                recommendation=f"Increase value by at least {diff} {unit} to meet requirement",
            )

    def _evaluate_maximum(self, actual_value: Any, context: Dict[str, Any]) -> ComplianceFinding:
        """Evaluate maximum value rule."""
        threshold = self.parameters.get("threshold")
        unit = self.parameters.get("unit", "")

        if actual_value is None:
            return ComplianceFinding(
                status=ComplianceStatus.REVIEW,
                rule_id=self.rule_id,
                title=self.name,
                description=self.description,
                expected_value=f"<= {threshold} {unit}",
                actual_value="Not provided",
                recommendation="Provide the required value for verification",
            )

        try:
            actual = float(actual_value)
            threshold_val = float(threshold)
        except (ValueError, TypeError):
            return ComplianceFinding(
                status=ComplianceStatus.REVIEW,
                rule_id=self.rule_id,
                title=self.name,
                description=self.description,
                expected_value=f"<= {threshold} {unit}",
                actual_value=str(actual_value),
                recommendation="Value could not be parsed as a number",
            )

        if actual <= threshold_val:
            return ComplianceFinding(
                status=ComplianceStatus.PASS,
                rule_id=self.rule_id,
                title=self.name,
                description=self.description,
                expected_value=f"<= {threshold} {unit}",
                actual_value=f"{actual} {unit}",
                calculation=f"{actual} <= {threshold_val} → PASS",
                confidence=1.0,
            )
        else:
            diff = actual - threshold_val
            return ComplianceFinding(
                status=ComplianceStatus.FAIL,
                rule_id=self.rule_id,
                title=self.name,
                description=self.description,
                severity=Severity.HIGH,
                expected_value=f"<= {threshold} {unit}",
                actual_value=f"{actual} {unit}",
                difference=f"{diff} {unit}",
                calculation=f"{actual} > {threshold_val} → FAIL (excess: {diff} {unit})",
                confidence=1.0,
                recommendation=f"Reduce value by at least {diff} {unit} to meet requirement",
            )

    def _evaluate_equals(self, actual_value: Any, context: Dict[str, Any]) -> ComplianceFinding:
        """Evaluate equals rule."""
        expected = self.parameters.get("expected")
        unit = self.parameters.get("unit", "")

        if actual_value is None:
            return ComplianceFinding(
                status=ComplianceStatus.REVIEW,
                rule_id=self.rule_id,
                title=self.name,
                description=self.description,
                expected_value=f"= {expected} {unit}",
                actual_value="Not provided",
            )

        try:
            actual = float(actual_value)
            expected_val = float(expected)
        except (ValueError, TypeError):
            return ComplianceFinding(
                status=ComplianceStatus.REVIEW,
                rule_id=self.rule_id,
                title=self.name,
                description=self.description,
                expected_value=f"= {expected} {unit}",
                actual_value=str(actual_value),
            )

        if actual == expected_val:
            return ComplianceFinding(
                status=ComplianceStatus.PASS,
                rule_id=self.rule_id,
                title=self.name,
                description=self.description,
                expected_value=f"= {expected} {unit}",
                actual_value=f"{actual} {unit}",
                calculation=f"{actual} == {expected_val} → PASS",
                confidence=1.0,
            )
        else:
            return ComplianceFinding(
                status=ComplianceStatus.FAIL,
                rule_id=self.rule_id,
                title=self.name,
                description=self.description,
                severity=Severity.HIGH,
                expected_value=f"= {expected} {unit}",
                actual_value=f"{actual} {unit}",
                difference=f"{abs(actual - expected_val)} {unit}",
                calculation=f"{actual} != {expected_val} → FAIL",
                confidence=1.0,
            )

    def _evaluate_range(self, actual_value: Any, context: Dict[str, Any]) -> ComplianceFinding:
        """Evaluate range rule."""
        min_val = self.parameters.get("min")
        max_val = self.parameters.get("max")
        unit = self.parameters.get("unit", "")

        if actual_value is None:
            return ComplianceFinding(
                status=ComplianceStatus.REVIEW,
                rule_id=self.rule_id,
                title=self.name,
                description=self.description,
                expected_value=f"{min_val} - {max_val} {unit}",
                actual_value="Not provided",
            )

        try:
            actual = float(actual_value)
            min_v = float(min_val)
            max_v = float(max_val)
        except (ValueError, TypeError):
            return ComplianceFinding(
                status=ComplianceStatus.REVIEW,
                rule_id=self.rule_id,
                title=self.name,
                description=self.description,
                expected_value=f"{min_val} - {max_val} {unit}",
                actual_value=str(actual_value),
            )

        if min_v <= actual <= max_v:
            return ComplianceFinding(
                status=ComplianceStatus.PASS,
                rule_id=self.rule_id,
                title=self.name,
                description=self.description,
                expected_value=f"{min_val} - {max_val} {unit}",
                actual_value=f"{actual} {unit}",
                calculation=f"{min_v} <= {actual} <= {max_v} → PASS",
                confidence=1.0,
            )
        else:
            if actual < min_v:
                diff = min_v - actual
                return ComplianceFinding(
                    status=ComplianceStatus.FAIL,
                    rule_id=self.rule_id,
                    title=self.name,
                    description=self.description,
                    severity=Severity.HIGH,
                    expected_value=f"{min_val} - {max_val} {unit}",
                    actual_value=f"{actual} {unit}",
                    difference=f"{diff} {unit} below minimum",
                    calculation=f"{actual} < {min_v} → FAIL",
                    confidence=1.0,
                )
            else:
                diff = actual - max_v
                return ComplianceFinding(
                    status=ComplianceStatus.FAIL,
                    rule_id=self.rule_id,
                    title=self.name,
                    description=self.description,
                    severity=Severity.HIGH,
                    expected_value=f"{min_val} - {max_val} {unit}",
                    actual_value=f"{actual} {unit}",
                    difference=f"{diff} {unit} above maximum",
                    calculation=f"{actual} > {max_v} → FAIL",
                    confidence=1.0,
                )

    def _evaluate_contains(self, actual_value: Any, context: Dict[str, Any]) -> ComplianceFinding:
        """Evaluate contains rule."""
        required = self.parameters.get("required", "")

        if actual_value is None:
            return ComplianceFinding(
                status=ComplianceStatus.REVIEW,
                rule_id=self.rule_id,
                title=self.name,
                description=self.description,
                expected_value=f"Contains: {required}",
                actual_value="Not provided",
            )

        actual_str = str(actual_value)
        if required.lower() in actual_str.lower():
            return ComplianceFinding(
                status=ComplianceStatus.PASS,
                rule_id=self.rule_id,
                title=self.name,
                description=self.description,
                expected_value=f"Contains: {required}",
                actual_value=actual_str[:100],
                calculation=f"'{required}' found in value → PASS",
                confidence=1.0,
            )
        else:
            return ComplianceFinding(
                status=ComplianceStatus.FAIL,
                rule_id=self.rule_id,
                title=self.name,
                description=self.description,
                severity=Severity.MEDIUM,
                expected_value=f"Contains: {required}",
                actual_value=actual_str[:100],
                calculation=f"'{required}' not found in value → FAIL",
                confidence=1.0,
            )

    def _evaluate_custom(self, actual_value: Any, context: Dict[str, Any]) -> ComplianceFinding:
        """Evaluate custom rule (Python expression)."""
        expression = self.parameters.get("expression", "")
        unit = self.parameters.get("unit", "")

        if not expression:
            return ComplianceFinding(
                status=ComplianceStatus.REVIEW,
                rule_id=self.rule_id,
                title=self.name,
                description="Custom rule has no expression",
            )

        try:
            # Safe evaluation with limited context
            result = eval(expression, {"__builtins__": {}}, {
                "value": actual_value,
                "context": context,
                "float": float,
                "int": int,
                "str": str,
            })

            if isinstance(result, bool):
                status = ComplianceStatus.PASS if result else ComplianceStatus.FAIL
                return ComplianceFinding(
                    status=status,
                    rule_id=self.rule_id,
                    title=self.name,
                    description=self.description,
                    actual_value=str(actual_value),
                    calculation=f"Custom rule evaluated to {result}",
                    confidence=0.9,
                )
            else:
                return ComplianceFinding(
                    status=ComplianceStatus.REVIEW,
                    rule_id=self.rule_id,
                    title=self.name,
                    description="Custom rule returned non-boolean",
                    actual_value=str(actual_value),
                )
        except Exception as e:
            return ComplianceFinding(
                status=ComplianceStatus.REVIEW,
                rule_id=self.rule_id,
                title=self.name,
                description=f"Custom rule evaluation failed: {e}",
                actual_value=str(actual_value),
            )


class ComplianceEngine:
    """
    Deterministic compliance engine.
    Evaluates rules against evidence to produce PASS/FAIL/REVIEW findings.
    """

    def __init__(self):
        self._rules: Dict[str, ComplianceRule] = {}
        self._load_default_rules()

    def _load_default_rules(self):
        """Load default compliance rules."""
        # Door width rules
        self.add_rule(ComplianceRule(
            rule_id="DOOR-MIN-WIDTH",
            name="Minimum Door Width",
            description="Clear door width must meet minimum requirement",
            rule_type="minimum",
            parameters={"threshold": 800, "unit": "mm"},
        ))

        # Corridor width rules
        self.add_rule(ComplianceRule(
            rule_id="CORRIDOR-MIN-WIDTH",
            name="Minimum Corridor Width",
            description="Corridor width must meet minimum requirement",
            rule_type="minimum",
            parameters={"threshold": 1200, "unit": "mm"},
        ))

        # Ceiling height rules
        self.add_rule(ComplianceRule(
            rule_id="CEILING-MIN-HEIGHT",
            name="Minimum Ceiling Height",
            description="Clear ceiling height must meet minimum requirement",
            rule_type="minimum",
            parameters={"threshold": 2400, "unit": "mm"},
        ))

        # Travel distance rules
        self.add_rule(ComplianceRule(
            rule_id="TRAVEL-MAX-DISTANCE",
            name="Maximum Travel Distance",
            description="Exit access travel distance must not exceed maximum",
            rule_type="maximum",
            parameters={"threshold": 45000, "unit": "mm"},
        ))

        # Room area rules
        self.add_rule(ComplianceRule(
            rule_id="ROOM-MIN-AREA",
            name="Minimum Room Area",
            description="Room area must meet minimum requirement",
            rule_type="minimum",
            parameters={"threshold": 7.0, "unit": "m²"},
        ))

        # Fire rating rules
        self.add_rule(ComplianceRule(
            rule_id="FIRE-RATING-MIN",
            name="Minimum Fire Rating",
            description="Fire resistance rating must meet minimum",
            rule_type="minimum",
            parameters={"threshold": 60, "unit": "min"},
        ))

        # Stair width rules
        self.add_rule(ComplianceRule(
            rule_id="STAIR-MIN-WIDTH",
            name="Minimum Stair Width",
            description="Stair width must meet minimum requirement",
            rule_type="minimum",
            parameters={"threshold": 900, "unit": "mm"},
        ))

        # Riser height rules
        self.add_rule(ComplianceRule(
            rule_id="RISER-MAX-HEIGHT",
            name="Maximum Riser Height",
            description="Stair riser height must not exceed maximum",
            rule_type="maximum",
            parameters={"threshold": 190, "unit": "mm"},
        ))

        # Tread depth rules
        self.add_rule(ComplianceRule(
            rule_id="TREAD-MIN-DEPTH",
            name="Minimum Tread Depth",
            description="Stair tread depth must meet minimum requirement",
            rule_type="minimum",
            parameters={"threshold": 250, "unit": "mm"},
        ))

        # Headroom rules
        self.add_rule(ComplianceRule(
            rule_id="HEADROOM-MIN",
            name="Minimum Headroom",
            description="Clear headroom must meet minimum requirement",
            rule_type="minimum",
            parameters={"threshold": 2100, "unit": "mm"},
        ))

    def add_rule(self, rule: ComplianceRule):
        """Add a compliance rule."""
        self._rules[rule.rule_id] = rule
        logger.info("Added compliance rule: {} ({})", rule.rule_id, rule.name)

    def get_rule(self, rule_id: str) -> Optional[ComplianceRule]:
        """Get a rule by ID."""
        return self._rules.get(rule_id)

    def list_rules(self) -> List[Dict[str, Any]]:
        """List all rules."""
        return [
            {
                "rule_id": r.rule_id,
                "name": r.name,
                "description": r.description,
                "rule_type": r.rule_type,
                "parameters": r.parameters,
            }
            for r in self._rules.values()
        ]

    def evaluate(self, rule_id: str, actual_value: Any,
                 context: Dict[str, Any] = None,
                 project_id: str = "",
                 source_doc: str = "",
                 source_page: int = None) -> ComplianceFinding:
        """
        Evaluate a rule against an actual value.
        Returns a ComplianceFinding with PASS/FAIL/REVIEW.
        """
        rule = self._rules.get(rule_id)
        if not rule:
            return ComplianceFinding(
                status=ComplianceStatus.REVIEW,
                rule_id=rule_id,
                title="Unknown Rule",
                description=f"Rule {rule_id} not found",
                project_id=project_id,
            )

        finding = rule.evaluate(actual_value, context)
        finding.rule_id = rule_id
        finding.project_id = project_id
        finding.source_doc = source_doc
        finding.source_page = source_page
        finding.created_at = datetime.datetime.utcnow().isoformat()
        finding.updated_at = finding.created_at
        finding.finding_id = f"CF-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{rule_id}"

        logger.info("Compliance check: {} = {} (rule: {})",
                    finding.status.value, finding.calculation, rule_id)
        return finding

    def evaluate_batch(self, checks: List[Dict[str, Any]],
                       project_id: str = "") -> List[ComplianceFinding]:
        """
        Evaluate multiple checks in batch.
        Each check: {rule_id, actual_value, context, source_doc, source_page}
        """
        findings = []
        for check in checks:
            finding = self.evaluate(
                rule_id=check.get("rule_id", ""),
                actual_value=check.get("actual_value"),
                context=check.get("context", {}),
                project_id=project_id,
                source_doc=check.get("source_doc", ""),
                source_page=check.get("source_page"),
            )
            findings.append(finding)
        return findings


# Singleton instance
_engine = ComplianceEngine()


def get_engine() -> ComplianceEngine:
    """Get the global compliance engine instance."""
    return _engine
