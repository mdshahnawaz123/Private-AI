"""Frozen Phase 2 regressions for deterministic claim-to-source validation."""
import hashlib
import ast
import json
from pathlib import Path
import unittest

from intelligence.answer_guard import guarded_answer, publication_issues, guarded_answer_with_repair


ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "output" / "claim-source-eval"
DATASET = EVAL / "benchmark_v1.json"
EXPECTED_SHA256 = "551c89d28d4e6af733ce769fc220bf5ad9257386b90ffe3771ad819f1fb9429b"
CASES = {c["id"]: c for c in json.loads(DATASET.read_text(encoding="utf-8"))["cases"]}


def evaluate(case):
    return publication_issues(case["candidate_answer"], case["evidence"], case["sources"],
                              question=case["question"])


class ClaimSupportRegressionTests(unittest.TestCase):
    def test_v1_ground_truth_is_unchanged_and_hash_pinned(self):
        self.assertEqual(hashlib.sha256(DATASET.read_bytes()).hexdigest(), EXPECTED_SHA256)

    def test_all_frozen_cases_meet_expected_publish_or_withhold_decision(self):
        for case in CASES.values():
            with self.subTest(case=case["id"]):
                issues = evaluate(case)
                should_publish = case["expected_action"] == "ANSWER"
                self.assertEqual(not issues, should_publish, (case["id"], issues))
                if case["expected_action"] == "AMBIGUOUS":
                    self.assertTrue(any(issue.startswith("AMBIGUOUS:") for issue in issues),
                                    (case["id"], issues))

    def test_cs007_missing_source_unit_is_withheld(self):
        self.assertIn("Answer omits a unit specified for the cited property/value", evaluate(CASES["CS007"]))

    def test_cs012_cs013_status_mismatch_is_withheld(self):
        for case_id in ("CS012", "CS013"):
            with self.subTest(case=case_id):
                self.assertTrue(any("status" in issue.lower() for issue in evaluate(CASES[case_id])))

    def test_cs014_source_qualification_cannot_be_dropped(self):
        self.assertIn("Answer omits or changes a source qualification", evaluate(CASES["CS014"]))

    def test_cs015_negation_cannot_be_reversed(self):
        self.assertIn("Answer reverses or drops source negation/polarity", evaluate(CASES["CS015"]))

    def test_cs016_revision_claim_must_match_cited_page(self):
        self.assertIn("Claimed revision does not match the cited native revision", evaluate(CASES["CS016"]))

    def test_cs017_conflicting_revision_values_return_ambiguity(self):
        answer, issues = guarded_answer(CASES["CS017"]["candidate_answer"], CASES["CS017"]["evidence"],
                                        CASES["CS017"]["sources"], question=CASES["CS017"]["question"])
        self.assertTrue(any(issue.startswith("AMBIGUOUS:") for issue in issues))
        self.assertIn("ambiguous or conflicting", answer.lower())

    def test_cs021_cross_page_entity_relationship_is_ambiguous(self):
        issues = evaluate(CASES["CS021"])
        self.assertTrue(any(issue.startswith("AMBIGUOUS:") for issue in issues), issues)

    def test_cs023_material_qualitative_claim_requires_citation(self):
        self.assertIn("Material claim lacks a valid source/page citation", evaluate(CASES["CS023"]))

    def test_cs025_supported_drawing_status_label_variant_remains_publishable(self):
        self.assertEqual(evaluate(CASES["CS025"]), [])

    def test_wrong_table_row_and_column_relationship_is_rejected(self):
        for case_id in ("CS003", "CS022"):
            with self.subTest(case=case_id):
                issues = evaluate(CASES[case_id])
                self.assertTrue(any("relationship" in issue.lower() or "value/unit" in issue.lower()
                                    for issue in issues), issues)

    def test_review_required_vision_value_stays_ineligible(self):
        issues = evaluate(CASES["CS018"])
        self.assertTrue(issues)
        self.assertTrue(any("Numeric values absent" in issue for issue in issues))

    def test_supported_positive_answers_remain_publishable(self):
        for case_id in ("CS001", "CS009", "CS024", "CS025", "CS026"):
            with self.subTest(case=case_id):
                self.assertEqual(evaluate(CASES[case_id]), [])

    def test_repair_candidate_is_checked_by_the_same_new_gate(self):
        case = CASES["CS014"]
        answer, issues = guarded_answer_with_repair(
            case["candidate_answer"], case["evidence"], case["sources"],
            lambda _issues: case["candidate_answer"], question=case["question"])
        self.assertTrue(issues)
        self.assertNotIn("275 Pa, subject to vendor confirmation", answer)

    def test_stream_rechecks_after_excerpt_fallback_and_server_qualifications(self):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        stream = next(node for node in tree.body
                      if isinstance(node, ast.AsyncFunctionDef) and node.name == "ask_stream")
        calls = sorted(((node.lineno, node) for node in ast.walk(stream) if isinstance(node, ast.Call)),
                       key=lambda item: item[0])
        names = [(line, node.func.id if isinstance(node.func, ast.Name) else "")
                 for line, node in calls]
        append_line = next(line for line, name in names if name == "append_source_qualifications")
        fallback_line = next(line for line, name in names if name == "source_excerpt")
        final_calls = [(line, node) for line, node in calls
                       if isinstance(node.func, ast.Name) and node.func.id == "guarded_answer"
                       and line > append_line]
        self.assertTrue(final_calls)
        final_line, final_call = final_calls[0]
        self.assertGreater(final_line, fallback_line)
        self.assertTrue(any(keyword.arg == "question" and isinstance(keyword.value, ast.Attribute)
                            and keyword.value.attr == "query" for keyword in final_call.keywords))


if __name__ == "__main__":
    unittest.main()
