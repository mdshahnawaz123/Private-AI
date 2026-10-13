from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf as fitz

from engines.pdf_knowledge_engine import PDFKnowledgeEngine
from engines.pdf_knowledge_chat import ask, evidence_context, local_generate, _unique_row_excerpt


class PDFKnowledgeChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / "synthetic.pdf"
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((40, 50), "AHU-813 design pressure is 275 Pa, subject to vendor confirmation.")
            doc.save(source)
        self.package = PDFKnowledgeEngine(self.root / "packages").build(source, project="A")
        self.question = "What design pressure is specified for AHU-813?"
        self.good = "AHU-813 design pressure is 275 Pa, subject to vendor confirmation. [SOURCE: EVIDENCE_1 | PAGE 1]"

    def test_supported_model_answer_is_published_with_real_source_identity(self):
        result = ask(self.package, self.question, project="A", generate=lambda messages: self.good)
        self.assertEqual(result["status"], "PUBLISHED")
        self.assertIn("synthetic.pdf | PAGE 1", result["answer"])
        self.assertIn("subject to vendor confirmation", result["answer"])

    def test_invalid_repair_uses_only_revalidated_source_fallback(self):
        result = ask(self.package, self.question, project="A", generate=lambda messages: self.good.replace("275", "400"))
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(result["status"], "SOURCE_EXCERPT")
        self.assertIn("275 Pa", result["answer"])
        self.assertNotIn("400 Pa", result["answer"])

    def test_invalid_fallback_is_withheld(self):
        bad = self.good.replace("275", "400")
        with patch("intelligence.source_excerpt.source_excerpt", return_value=bad):
            result = ask(self.package, self.question, project="A", generate=lambda messages: bad)
        self.assertEqual(result["status"], "WITHHELD")
        self.assertNotIn("400 Pa", result["answer"])

    def test_verifier_error_is_closed(self):
        with patch("intelligence.answer_guard.guarded_answer", side_effect=RuntimeError("verifier failed")):
            result = ask(self.package, self.question, project="A", generate=lambda messages: self.good)
        self.assertEqual(result["status"], "WITHHELD")
        self.assertNotIn("275 Pa", result["answer"])

    def test_model_failure_is_closed(self):
        def fail(messages):
            raise RuntimeError("offline")
        self.assertEqual(ask(self.package, self.question, project="A", generate=fail)["status"], "WITHHELD")

    def test_wrong_project_fails_before_model(self):
        with self.assertRaises(ValueError):
            ask(self.package, self.question, project="B", generate=lambda messages: self.fail("Model must not run"))

    def test_no_source_match_does_not_invoke_model(self):
        result = ask(self.package, "XYZ999 electrical switchboard", project="A", generate=lambda messages: self.fail("Model must not run"))
        self.assertEqual(result["attempts"], [])
        self.assertNotEqual(result["status"], "PUBLISHED")

    def test_cloud_server_is_rejected_before_call(self):
        with patch("config.resolve_role", return_value={"model": "local", "base_url": "https://example.com"}):
            with self.assertRaisesRegex(ValueError, "loopback"):
                local_generate([])

    def test_table_title_header_entity_and_value_are_one_supported_row_span(self):
        source = self.root / "pressure-table.pdf"
        with fitz.open() as doc:
            page = doc.new_page()
            for y in (60, 90, 120, 150):
                page.draw_line((40, y), (400, y))
            for x in (40, 400):
                page.draw_line((x, 60), (x, 150))
            page.draw_line((220, 90), (220, 150))
            page.insert_text((45, 80), "DESIGN PRESSURE")
            for y, row in [(110, ("ITEM", "(Pa)")), (140, ("AHU-813", "275"))]:
                for x, value in zip((45, 225), row):
                    page.insert_text((x, y), value)
            doc.save(source)
        package = PDFKnowledgeEngine(self.root / "packages").build(source, project="A")
        evidence, _, _ = evidence_context(package, self.question, "A")
        self.assertEqual(evidence.count("[SOURCE:"), 1)
        self.assertTrue(any("Table: DESIGN PRESSURE" in line and "AHU-813" in line and "275" in line for line in evidence.splitlines()))
        answer = "AHU-813 design pressure is 275 Pa. [SOURCE: EVIDENCE_1 | PAGE 1]"
        result = ask(package, self.question, project="A", generate=lambda messages: answer)
        self.assertEqual(result["status"], "PUBLISHED", result)

    def test_unique_row_fallback_preserves_scope_and_rejects_conflict_or_authority(self):
        sources = [{"source": "synthetic.pdf", "page": 1}]
        row = "[TABLE ROW]; Table: BUILT-UP AREA BREAKDOWN (Per Level); ITEM: Basement 1; (SQ.M): 12.00"
        evidence = "[SOURCE: synthetic.pdf | PAGE 1]\n" + row
        question = "Built-up area of Basement 1 per-level breakdown"
        self.assertIn(row, _unique_row_excerpt(question, evidence, sources))
        self.assertIsNone(_unique_row_excerpt(question.replace("Basement 1", "Basement 2"), evidence, sources))
        self.assertIsNone(_unique_row_excerpt("Approved " + question, evidence, sources))
        self.assertIsNone(_unique_row_excerpt(question, evidence + "\n" + row.replace("12.00", "99.00"), sources))


if __name__ == "__main__":
    unittest.main()
