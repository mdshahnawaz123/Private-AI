"""
Golden-Set Evaluation Runner for Expo Design AI (Wave 1, Task 1.3).

Runs evaluation against real project data and produces:
- Per-question results (PASS/FAIL)
- Retrieval hit@k
- Answer match (with numeric tolerance)
- Source correctness
- Honesty (for not-found questions)
- Latency

Output: Terminal summary + CSV + Markdown report.

NO CLOUD EVALUATION — all checks are deterministic and local.
"""
import os
import sys
import json
import time
import csv
import re
import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from loguru import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


class EvaluationRunner:
    """
    Golden-set evaluation runner.
    All checks are deterministic — no LLM judge required.
    """

    def __init__(self, golden_set_path: str = None):
        self.golden_set_path = golden_set_path or str(
            Path(__file__).parent / "golden_set.jsonl"
        )
        self.results: List[Dict[str, Any]] = []
        self.project = "C3085 - 3EH -Expo Hills"

    def load_golden_set(self) -> List[Dict[str, Any]]:
        """Load golden set from JSONL file."""
        questions = []
        with open(self.golden_set_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    questions.append(json.loads(line))
        logger.info(f"Loaded {len(questions)} questions from golden set")
        return questions

    def check_answer_match(self, answer: str, expected_contains: List[str],
                           numeric_tolerance: float = 0.01) -> Tuple[bool, str]:
        """
        Check if answer contains expected values.
        Supports numeric tolerance for measurements.
        """
        answer_lower = answer.lower()
        matched = []
        missing = []

        for expected in expected_contains:
            expected_lower = expected.lower()
            if expected_lower in answer_lower:
                matched.append(expected)
            else:
                # Try numeric tolerance for numbers
                try:
                    expected_num = float(expected.replace(",", ""))
                    # Find all numbers in answer
                    answer_nums = re.findall(r'[\d,]+\.?\d*', answer.replace(",", ""))
                    found = False
                    for ans_num_str in answer_nums:
                        try:
                            ans_num = float(ans_num_str)
                            if abs(ans_num - expected_num) / max(abs(expected_num), 1) <= numeric_tolerance:
                                found = True
                                break
                        except ValueError:
                            continue
                    if found:
                        matched.append(expected)
                    else:
                        missing.append(expected)
                except ValueError:
                    missing.append(expected)

        success = len(missing) == 0
        detail = f"matched={matched}, missing={missing}"
        return success, detail

    def check_source_correctness(self, answer: str, expected_sources: List[str]) -> Tuple[bool, str]:
        """Check if answer cites expected sources."""
        answer_lower = answer.lower()
        found_sources = []
        missing_sources = []

        for source in expected_sources:
            source_lower = source.lower()
            # Check for filename or key parts
            source_parts = source_lower.replace(".pdf", "").replace("-", " ").split()
            # Check if key parts of source are in answer
            key_part = source_lower.split("-")[0] if "-" in source_lower else source_lower
            if key_part in answer_lower or source_lower in answer_lower:
                found_sources.append(source)
            else:
                missing_sources.append(source)

        success = len(missing_sources) == 0
        detail = f"found={found_sources}, missing={missing_sources}"
        return success, detail

    def check_honesty(self, answer: str, question_type: str) -> Tuple[bool, str]:
        """
        Check if system correctly says information is not found.
        For 'not-found' type questions, system should say it cannot find the info.
        """
        if question_type != "not-found":
            return True, "N/A (not a not-found question)"

        answer_lower = answer.lower()
        not_found_phrases = [
            "not found", "could not find", "cannot find", "no information",
            "not available", "not present", "does not exist", "unable to find",
            "i could not find", "not in the", "no data", "not documented"
        ]

        found_phrase = any(phrase in answer_lower for phrase in not_found_phrases)
        if found_phrase:
            return True, "Correctly indicated information not found"
        else:
            return False, "Should have indicated information not found"

    def run_evaluation(self, use_llm: bool = False) -> Dict[str, Any]:
        """
        Run full evaluation against golden set.

        Args:
            use_llm: If True, use LLM for answer generation (slower).
                     If False, use retrieval-only evaluation (faster, deterministic).
        """
        questions = self.load_golden_set()
        self.results = []

        print(f"\n{'='*70}")
        print(f"  Expo Design AI — Golden Set Evaluation")
        print(f"  Project: {self.project}")
        print(f"  Questions: {len(questions)}")
        print(f"  Mode: {'LLM' if use_llm else 'Retrieval-only'}")
        print(f"{'='*70}\n")

        for i, q in enumerate(questions, 1):
            qid = q.get("id", f"q{i:03d}")
            question = q.get("question", "")
            expected_answer = q.get("expected_answer_contains", [])
            expected_sources = q.get("expected_sources", [])
            qtype = q.get("type", "general")

            print(f"[{i}/{len(questions)}] {qid}: {question[:60]}...")

            start_time = time.time()

            # Get answer from system
            if use_llm:
                answer, retrieved_sources = self._get_llm_answer(question)
            else:
                answer, retrieved_sources = self._get_retrieval_answer(question)

            elapsed = time.time() - start_time

            # Evaluate
            answer_match, answer_detail = self.check_answer_match(answer, expected_answer)
            source_match, source_detail = self.check_source_correctness(answer, expected_sources)
            honesty, honesty_detail = self.check_honesty(answer, qtype)

            # Retrieval hit@k
            retrieval_hit = self._check_retrieval_hit(retrieved_sources, expected_sources)

            # Overall pass
            passed = answer_match and source_match and honesty

            result = {
                "id": qid,
                "question": question,
                "type": qtype,
                "passed": passed,
                "answer_match": answer_match,
                "source_match": source_match,
                "retrieval_hit": retrieval_hit,
                "honesty": honesty,
                "latency_ms": round(elapsed * 1000, 1),
                "answer_preview": answer[:200] if answer else "",
                "expected_answer": expected_answer,
                "expected_sources": expected_sources,
            }
            self.results.append(result)

            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] answer={answer_match} source={source_match} "
                  f"retrieval={retrieval_hit} honesty={honesty} | {elapsed:.2f}s")

        return self._compute_summary()

    def _get_retrieval_answer(self, question: str) -> Tuple[str, List[str]]:
        """
        Get answer using retrieval only (deterministic, fast).
        Returns concatenated retrieved text as answer.
        """
        try:
            import main as app_main
            # Use the existing retrieve_context function
            srcs, ctx = app_main.retrieve_context(self.project, question, k=8)
            # Build answer from context
            answer = ctx if ctx else "No relevant information found."
            retrieved_sources = [s.get("source", "") for s in srcs] if srcs else []
            return answer, retrieved_sources
        except Exception as e:
            logger.error(f"Retrieval failed: {e}")
            return f"Error: {str(e)}", []

    def _get_llm_answer(self, question: str) -> Tuple[str, List[str]]:
        """Get answer using LLM (slower, for full evaluation)."""
        try:
            import main as app_main
            srcs, ctx = app_main.retrieve_context(self.project, question, k=8)
            retrieved_sources = [s.get("source", "") for s in srcs] if srcs else []

            if not ctx:
                return "No relevant information found.", retrieved_sources

            # Build messages and get LLM answer
            from langchain_core.messages import SystemMessage, HumanMessage
            msgs = [
                SystemMessage(content="Answer the question using only the provided context."),
                HumanMessage(content=f"Context:\n{ctx}\n\nQuestion: {question}")
            ]
            llm = app_main.get_llm(type("Req", (), {"model": "qwen2.5vl:32b"})())
            answer = ""
            for chunk in llm.stream(msgs):
                answer += chunk.content

            return answer, retrieved_sources
        except Exception as e:
            logger.error(f"LLM answer failed: {e}")
            return f"Error: {str(e)}", []

    def _check_retrieval_hit(self, retrieved_sources: List[str],
                             expected_sources: List[str]) -> bool:
        """Check if expected source is in retrieved sources."""
        if not expected_sources:
            return True
        for expected in expected_sources:
            for retrieved in retrieved_sources:
                if expected.lower() in retrieved.lower() or retrieved.lower() in expected.lower():
                    return True
        return False

    def _compute_summary(self) -> Dict[str, Any]:
        """Compute aggregate metrics."""
        total = len(self.results)
        if total == 0:
            return {"error": "No results"}

        passed = sum(1 for r in self.results if r["passed"])
        answer_matches = sum(1 for r in self.results if r["answer_match"])
        source_matches = sum(1 for r in self.results if r["source_match"])
        retrieval_hits = sum(1 for r in self.results if r["retrieval_hit"])
        honest = sum(1 for r in self.results if r["honesty"])
        avg_latency = sum(r["latency_ms"] for r in self.results) / total

        # By type
        by_type = {}
        for r in self.results:
            t = r["type"]
            if t not in by_type:
                by_type[t] = {"total": 0, "passed": 0}
            by_type[t]["total"] += 1
            if r["passed"]:
                by_type[t]["passed"] += 1

        summary = {
            "total_questions": total,
            "overall_pass_rate": round(passed / total * 100, 1),
            "answer_accuracy": round(answer_matches / total * 100, 1),
            "source_accuracy": round(source_matches / total * 100, 1),
            "retrieval_hit_rate": round(retrieval_hits / total * 100, 1),
            "honesty_score": round(honest / total * 100, 1),
            "average_latency_ms": round(avg_latency, 1),
            "by_type": by_type,
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }
        return summary

    def print_summary(self, summary: Dict[str, Any]):
        """Print evaluation summary to terminal."""
        print(f"\n{'='*70}")
        print(f"  EVALUATION SUMMARY")
        print(f"{'='*70}")
        print(f"  Total questions:     {summary['total_questions']}")
        print(f"  Overall pass rate:   {summary['overall_pass_rate']}%")
        print(f"  Answer accuracy:     {summary['answer_accuracy']}%")
        print(f"  Source accuracy:     {summary['source_accuracy']}%")
        print(f"  Retrieval hit rate:  {summary['retrieval_hit_rate']}%")
        print(f"  Honesty score:       {summary['honesty_score']}%")
        print(f"  Average latency:     {summary['average_latency_ms']} ms")
        print(f"{'='*70}")
        print(f"\n  By type:")
        for t, counts in summary.get("by_type", {}).items():
            rate = round(counts["passed"] / counts["total"] * 100, 1)
            print(f"    {t:12} {counts['passed']}/{counts['total']} ({rate}%)")
        print()

    def export_csv(self, output_path: str = None):
        """Export results to CSV."""
        if not output_path:
            output_path = str(Path(__file__).parent / "eval_results.csv")

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "question", "type", "passed", "answer_match",
                "source_match", "retrieval_hit", "honesty", "latency_ms"
            ])
            writer.writeheader()
            for r in self.results:
                writer.writerow({k: r[k] for k in writer.fieldnames})
        print(f"CSV exported to: {output_path}")

    def export_markdown(self, output_path: str = None):
        """Export results to Markdown report."""
        if not output_path:
            output_path = str(Path(__file__).parent / "eval_report.md")

        summary = self._compute_summary()
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("# Expo Design AI — Evaluation Report\n\n")
            f.write(f"**Date:** {summary['timestamp']}\n\n")
            f.write(f"**Project:** C3085 - 3EH -Expo Hills\n\n")
            f.write("## Summary\n\n")
            f.write(f"| Metric | Value |\n|---|---|\n")
            f.write(f"| Total questions | {summary['total_questions']} |\n")
            f.write(f"| Overall pass rate | {summary['overall_pass_rate']}% |\n")
            f.write(f"| Answer accuracy | {summary['answer_accuracy']}% |\n")
            f.write(f"| Source accuracy | {summary['source_accuracy']}% |\n")
            f.write(f"| Retrieval hit rate | {summary['retrieval_hit_rate']}% |\n")
            f.write(f"| Honesty score | {summary['honesty_score']}% |\n")
            f.write(f"| Average latency | {summary['average_latency_ms']} ms |\n\n")
            f.write("## By Type\n\n")
            f.write("| Type | Passed | Total | Rate |\n|---|---|---|---|\n")
            for t, counts in summary.get("by_type", {}).items():
                rate = round(counts["passed"] / counts["total"] * 100, 1)
                f.write(f"| {t} | {counts['passed']} | {counts['total']} | {rate}% |\n")
            f.write("\n## Per-Question Results\n\n")
            f.write("| ID | Question | Type | Passed | Answer | Source | Retrieval | Honesty | Latency |\n")
            f.write("|---|---|---|---|---|---|---|---|---|\n")
            for r in self.results:
                q = r["question"][:50].replace("|", "\\|")
                p = "Y" if r["passed"] else "N"
                a = "Y" if r["answer_match"] else "N"
                s = "Y" if r["source_match"] else "N"
                r_hit = "Y" if r["retrieval_hit"] else "N"
                h = "Y" if r["honesty"] else "N"
                f.write(f"| {r['id']} | {q} | {r['type']} | {p} | {a} | {s} | {r_hit} | {h} | "
                        f"{r['latency_ms']}ms |\n")
        print(f"Markdown report exported to: {output_path}")


def main():
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Expo Design AI Evaluation Runner")
    parser.add_argument("--llm", action="store_true", help="Use LLM for answer generation")
    parser.add_argument("--golden-set", type=str, help="Path to golden set JSONL file")
    args = parser.parse_args()

    runner = EvaluationRunner(golden_set_path=args.golden_set)
    summary = runner.run_evaluation(use_llm=args.llm)
    runner.print_summary(summary)
    runner.export_csv()
    runner.export_markdown()

    print(f"\n{'='*70}")
    print("  Evaluation complete!")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
