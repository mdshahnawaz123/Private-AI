"""
End-to-end tests for Visualization and PDF Evidence Highlighting.
Verifies:
1. Question -> Answer with citation -> PDF evidence bounding box resolution.
2. Fail-closed safeguard: wrong or unrelated citation cannot produce a highlight.
3. Chart JSON validation and inclusion in structured response.
4. Chart rejection safeguard: invalid or unverified charts are not accepted.
"""
import os
import tempfile
import unittest
import fitz

from response_schema import build_structured_response
from services.pdf_highlighter import locate_evidence
from intelligence.visualization_schema import validate_chart_spec


class TestE2EVisualizationAndEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.doc_filename = "C3103-STR-SPEC.pdf"
        cls.doc_path = os.path.join(cls.temp_dir.name, cls.doc_filename)

        # Build real test PDF with structural engineering data
        doc = fitz.open()

        # Page 1: General Notes & Overview
        p1 = doc.new_page(width=612, height=792)
        p1.insert_text(
            fitz.Point(72, 100),
            "GENERAL STRUCTURAL SPECIFICATIONS\n"
            "Project: Expo Exhibition Pavilion 2026\n"
            "Seismic Importance Factor Ie = 1.25\n"
            "Occupancy Category: III",
            fontsize=12,
        )

        # Page 2: Foundation & Columns
        p2 = doc.new_page(width=612, height=792)
        p2.insert_text(
            fitz.Point(72, 120),
            "SECTION 03 30 00 - CAST-IN-PLACE CONCRETE\n"
            "Part 2 - Products\n"
            "2.1 Concrete Mixes:\n"
            "All perimeter columns shall have Concrete Compressive Strength f'c = 45 MPa at 28 days.\n"
            "Interior gravity columns shall have f'c = 35 MPa.\n"
            "Raft foundation thickness is 1200 mm with Grade 60 rebar.",
            fontsize=11,
        )

        doc.save(cls.doc_path)
        doc.close()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_e2e_cited_answer_to_pdf_highlight(self):
        query = "What is the concrete compressive strength for the perimeter columns?"
        model_answer = (
            "Per the project specifications, all perimeter columns shall have "
            "Concrete Compressive Strength f'c = 45 MPa at 28 days. "
            f"[SOURCE: {self.doc_filename} | PAGE 2]"
        )
        sources = [
            {"filename": self.doc_filename, "source": self.doc_path, "page": 2, "rel": self.doc_filename}
        ]

        # 1. Build structured response
        structured = build_structured_response(query, model_answer, sources)
        self.assertIn("sources", structured)
        self.assertEqual(len(structured["sources"]), 1)
        src = structured["sources"][0]
        self.assertEqual(src["document"], self.doc_filename)
        self.assertEqual(src["page"], 2)

        # 2. Extract passage evidence coordinates
        passage = "Concrete Compressive Strength f'c = 45 MPa at 28 days"
        evidence_res = locate_evidence(self.doc_path, 2, passage)

        self.assertTrue(evidence_res["found"])
        self.assertEqual(evidence_res["match_type"], "exact")
        self.assertGreater(len(evidence_res["rects"]), 0)
        self.assertEqual(evidence_res["page"], 2)

        # Validate bounding box coordinates
        rect = evidence_res["rects"][0]
        self.assertGreater(rect[2], rect[0])
        self.assertGreater(rect[3], rect[1])

    def test_wrong_or_unrelated_citation_fails_closed(self):
        # Citation claims evidence is on Page 1, but the text is on Page 2
        passage = "Concrete Compressive Strength f'c = 45 MPa at 28 days"
        evidence_res_wrong_page = locate_evidence(self.doc_path, 1, passage)
        self.assertFalse(evidence_res_wrong_page["found"])
        self.assertEqual(evidence_res_wrong_page["rects"], [])

        # Citation claims a fabricated engineering fact
        fabricated_passage = "All columns shall have f'c = 120 MPa ultra-high performance concrete"
        evidence_res_fake = locate_evidence(self.doc_path, 2, fabricated_passage)
        self.assertFalse(evidence_res_fake["found"])
        self.assertEqual(evidence_res_fake["rects"], [])

    def test_e2e_chart_generation_and_validation(self):
        query = "Show me the distribution of column concrete strengths."
        model_answer_with_chart = """
Based on Section 03 30 00, here is the column mix distribution:

```chart
{
  "chart_type": "bar",
  "title": "Column Concrete Strength by Location",
  "categories": ["Perimeter Columns", "Interior Columns"],
  "series": [
    {
      "name": "Compressive Strength (MPa)",
      "data": [45, 35]
    }
  ],
  "units": "MPa"
}
```
"""
        sources = [{"filename": self.doc_filename, "source": self.doc_path, "page": 2}]
        structured = build_structured_response(query, model_answer_with_chart, sources)

        # Verify chart was extracted and validated
        self.assertIn("charts", structured)
        self.assertEqual(len(structured["charts"]), 1)
        chart = structured["charts"][0]
        self.assertEqual(chart["chart_type"], "bar")
        self.assertEqual(chart["title"], "Column Concrete Strength by Location")
        self.assertEqual(chart["series"][0]["data"], [45.0, 35.0])
        self.assertEqual(chart["units"], "MPa")

    def test_e2e_invalid_chart_is_not_rendered(self):
        # Model produced an invalid chart spec (missing categories, non-numeric values)
        invalid_chart_answer = """
```chart
{
  "chart_type": "bar",
  "title": "Invalid Chart",
  "categories": ["A", "B"],
  "series": [
    {
      "name": "S1",
      "data": ["not_a_number", null]
    }
  ]
}
```
"""
        structured = build_structured_response("Query", invalid_chart_answer, [])
        self.assertEqual(structured.get("charts"), [])


if __name__ == "__main__":
    unittest.main()
