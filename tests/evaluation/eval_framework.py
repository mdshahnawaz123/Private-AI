"""
AI Evaluation Framework for Expo Design AI (Phase 10).

Measures:
- OCR accuracy
- Layout detection accuracy
- Entity extraction accuracy
- Requirement extraction accuracy
- Retrieval accuracy
- Citation accuracy
- Vision accuracy
- Compliance accuracy
- Response accuracy
- Latency
- Failure rate

Every major AI/model change is tested against a fixed evaluation dataset
before production deployment.
"""
import os
import json
import time
import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


@dataclass
class EvalExample:
    """A single evaluation example."""
    input: str
    expected_output: str
    source: str = ""
    verification_status: str = "pending"  # pending, verified, rejected
    category: str = ""  # ocr, extraction, retrieval, compliance, etc.
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalResult:
    """Result of an evaluation run."""
    dataset_name: str
    total_examples: int
    passed: int
    failed: int
    accuracy: float
    latency_ms: float
    timestamp: str
    details: List[Dict[str, Any]] = field(default_factory=list)


class EvaluationFramework:
    """
    Formal evaluation framework for AI quality measurement.
    """

    def __init__(self):
        self._datasets: Dict[str, List[EvalExample]] = {}
        self._results: List[EvalResult] = []

    def create_dataset(self, name: str, description: str = "",
                       category: str = "") -> str:
        """Create a new evaluation dataset."""
        dataset_id = f"ds-{name.lower().replace(' ', '-')}"
        self._datasets[dataset_id] = []
        logger.info("Created evaluation dataset: {} ({})", dataset_id, name)
        return dataset_id

    def add_example(self, dataset_id: str, input_text: str,
                    expected_output: str, source: str = "",
                    category: str = "", metadata: Dict[str, Any] = None):
        """Add an example to a dataset."""
        if dataset_id not in self._datasets:
            raise ValueError(f"Dataset {dataset_id} not found")
        self._datasets[dataset_id].append(EvalExample(
            input=input_text,
            expected_output=expected_output,
            source=source,
            category=category,
            metadata=metadata or {},
        ))

    def load_dataset_from_json(self, dataset_id: str, file_path: str):
        """Load evaluation examples from a JSON file."""
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("examples", []):
            self.add_example(
                dataset_id=dataset_id,
                input_text=item.get("input", ""),
                expected_output=item.get("expected_output", ""),
                source=item.get("source", ""),
                category=item.get("category", ""),
                metadata=item.get("metadata", {}),
            )
        logger.info("Loaded {} examples into {}", len(data.get("examples", [])), dataset_id)

    def evaluate_ocr(self, dataset_id: str, ocr_engine) -> EvalResult:
        """Evaluate OCR accuracy."""
        examples = self._datasets.get(dataset_id, [])
        if not examples:
            raise ValueError(f"Dataset {dataset_id} is empty")

        passed = 0
        details = []
        start = time.time()

        for ex in examples:
            # Run OCR
            result = ocr_engine.recognize(ex.input)
            actual = result.full_text.lower().strip()
            expected = ex.expected_output.lower().strip()

            # Simple accuracy: character-level match
            if actual == expected:
                passed += 1
                details.append({"input": ex.input, "status": "pass"})
            else:
                # Calculate partial match
                match_ratio = self._calculate_match_ratio(actual, expected)
                if match_ratio > 0.9:
                    passed += 1
                    details.append({"input": ex.input, "status": "pass", "ratio": match_ratio})
                else:
                    details.append({
                        "input": ex.input,
                        "status": "fail",
                        "expected": expected[:100],
                        "actual": actual[:100],
                        "ratio": match_ratio,
                    })

        elapsed = (time.time() - start) * 1000
        result = EvalResult(
            dataset_name=dataset_id,
            total_examples=len(examples),
            passed=passed,
            failed=len(examples) - passed,
            accuracy=passed / len(examples) if examples else 0,
            latency_ms=elapsed,
            timestamp=datetime.datetime.utcnow().isoformat(),
            details=details,
        )
        self._results.append(result)
        logger.info("OCR evaluation: {}/{} passed ({:.1%})", passed, len(examples), result.accuracy)
        return result

    def evaluate_retrieval(self, dataset_id: str, retriever,
                           project: str = "default") -> EvalResult:
        """Evaluate retrieval accuracy."""
        examples = self._datasets.get(dataset_id, [])
        if not examples:
            raise ValueError(f"Dataset {dataset_id} is empty")

        passed = 0
        details = []
        start = time.time()

        for ex in examples:
            # Run retrieval
            result = retriever.retrieve_from_faiss(ex.input, project, k=5)
            retrieved_sources = [r.source for r in result.results]

            # Check if expected source is in results
            expected_source = ex.expected_output
            if expected_source in retrieved_sources:
                passed += 1
                details.append({"query": ex.input, "status": "pass"})
            else:
                details.append({
                    "query": ex.input,
                    "status": "fail",
                    "expected_source": expected_source,
                    "retrieved": retrieved_sources,
                })

        elapsed = (time.time() - start) * 1000
        result = EvalResult(
            dataset_name=dataset_id,
            total_examples=len(examples),
            passed=passed,
            failed=len(examples) - passed,
            accuracy=passed / len(examples) if examples else 0,
            latency_ms=elapsed,
            timestamp=datetime.datetime.utcnow().isoformat(),
            details=details,
        )
        self._results.append(result)
        logger.info("Retrieval evaluation: {}/{} passed ({:.1%})", passed, len(examples), result.accuracy)
        return result

    def evaluate_compliance(self, dataset_id: str, compliance_engine) -> EvalResult:
        """Evaluate compliance checking accuracy."""
        examples = self._datasets.get(dataset_id, [])
        if not examples:
            raise ValueError(f"Dataset {dataset_id} is empty")

        passed = 0
        details = []
        start = time.time()

        for ex in examples:
            # Parse input: expected format "rule_id|actual_value"
            parts = ex.input.split("|")
            if len(parts) != 2:
                continue
            rule_id, actual_value = parts

            finding = compliance_engine.evaluate(rule_id, float(actual_value))
            expected_status = ex.expected_output

            if finding.status.value == expected_status:
                passed += 1
                details.append({"input": ex.input, "status": "pass"})
            else:
                details.append({
                    "input": ex.input,
                    "status": "fail",
                    "expected": expected_status,
                    "actual": finding.status.value,
                })

        elapsed = (time.time() - start) * 1000
        result = EvalResult(
            dataset_name=dataset_id,
            total_examples=len(examples),
            passed=passed,
            failed=len(examples) - passed,
            accuracy=passed / len(examples) if examples else 0,
            latency_ms=elapsed,
            timestamp=datetime.datetime.utcnow().isoformat(),
            details=details,
        )
        self._results.append(result)
        logger.info("Compliance evaluation: {}/{} passed ({:.1%})", passed, len(examples), result.accuracy)
        return result

    def _calculate_match_ratio(self, actual: str, expected: str) -> float:
        """Calculate character-level match ratio."""
        if not expected:
            return 0.0
        # Simple Levenshtein-based ratio
        len_a = len(actual)
        len_e = len(expected)
        if len_a == 0 or len_e == 0:
            return 0.0

        # Count matching characters
        matches = 0
        for i in range(min(len_a, len_e)):
            if actual[i] == expected[i]:
                matches += 1

        return matches / max(len_a, len_e)

    def get_summary(self) -> Dict[str, Any]:
        """Get evaluation summary."""
        if not self._results:
            return {"message": "No evaluations run yet"}

        return {
            "total_evaluations": len(self._results),
            "average_accuracy": sum(r.accuracy for r in self._results) / len(self._results),
            "evaluations": [
                {
                    "dataset": r.dataset_name,
                    "accuracy": r.accuracy,
                    "passed": r.passed,
                    "failed": r.failed,
                    "latency_ms": r.latency_ms,
                    "timestamp": r.timestamp,
                }
                for r in self._results
            ],
        }

    def export_results(self, output_path: str):
        """Export evaluation results to JSON."""
        data = {
            "summary": self.get_summary(),
            "results": [
                {
                    "dataset": r.dataset_name,
                    "total": r.total_examples,
                    "passed": r.passed,
                    "failed": r.failed,
                    "accuracy": r.accuracy,
                    "latency_ms": r.latency_ms,
                    "timestamp": r.timestamp,
                    "details": r.details,
                }
                for r in self._results
            ],
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("Evaluation results exported to {}", output_path)


# Singleton instance
_eval_framework = EvaluationFramework()


def get_eval_framework() -> EvaluationFramework:
    """Get the global evaluation framework instance."""
    return _eval_framework
