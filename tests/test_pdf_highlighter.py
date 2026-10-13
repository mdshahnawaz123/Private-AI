"""
Unit tests for services/pdf_highlighter.py.
Verifies:
- Exact PDF text matching and bounding box coordinates
- Multi-line passage highlighting across line breaks
- Page rotation handling and coordinate space transformations
- Page accuracy (evidence on cited page vs non-cited page)
- Scanned-PDF fallback to OCR / inspection metadata
- Missing evidence safeguards (no hallucinated highlights)
- Protection against ambiguous lone keywords
- Rejection of wrong or unrelated citations
- Non-destructive PDF annotation copy creation
"""
import os
import tempfile
import unittest
import fitz

from services.pdf_highlighter import (
    locate_evidence,
    locate_evidence_in_page,
    create_annotated_copy,
    render_highlighted_page_pixmap,
    normalize_text,
)


class TestPdfHighlighter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.pdf_path = os.path.join(cls.temp_dir.name, "sample_spec.pdf")
        cls.rotated_pdf_path = os.path.join(cls.temp_dir.name, "sample_rotated.pdf")

        # Create standard multi-page test PDF
        doc = fitz.open()

        # Page 1: General Project Information
        p1 = doc.new_page(width=612, height=792)  # Standard Letter
        p1.insert_text(
            fitz.Point(72, 100),
            "PROJECT SPECIFICATION SHEET\n"
            "Document Number: C3103-SPEC-001 Rev B\n"
            "Total Gross Floor Area is 14,250 sqm across Levels 1 to 5.\n"
            "Foundation Type: Reinforced Cast-in-Place Concrete Raft.",
            fontsize=12,
        )
        # Multi-line wrapped passage
        p1.insert_text(
            fitz.Point(72, 250),
            "The seismic resisting system consists of special reinforced concrete\n"
            "shear walls located symmetrically around the central building core.",
            fontsize=11,
        )

        # Page 2: Structural Materials
        p2 = doc.new_page(width=612, height=792)
        p2.insert_text(
            fitz.Point(72, 100),
            "STRUCTURAL MATERIAL PROPERTIES\n"
            "Concrete Compressive Strength f'c = 40 MPa for all columns.\n"
            "Reinforcing Steel: Grade 60 (Yield strength Fy = 420 MPa).",
            fontsize=12,
        )

        doc.save(cls.pdf_path)
        doc.close()

        # Create rotated page PDF (Page 1 rotated 90 degrees)
        doc_rot = fitz.open()
        p_rot = doc_rot.new_page(width=612, height=792)
        p_rot.insert_text(
            fitz.Point(100, 150),
            "Rotated Drawing Notes: Maximum allowable soil bearing pressure is 250 kPa.",
            fontsize=12,
        )
        p_rot.set_rotation(90)
        doc_rot.save(cls.rotated_pdf_path)
        doc_rot.close()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_exact_pdf_text_matching(self):
        snippet = "Total Gross Floor Area is 14,250 sqm across Levels 1 to 5."
        res = locate_evidence(self.pdf_path, 1, snippet)
        self.assertTrue(res["found"])
        self.assertEqual(res["match_type"], "exact")
        self.assertEqual(len(res["rects"]), 1)
        r = res["rects"][0]
        # Bounding box coordinates [x0, y0, x1, y1]
        self.assertGreater(r[2], r[0])
        self.assertGreater(r[3], r[1])
        # Normalized coordinates within 0.0 - 1.0
        nr = res["normalized_rects"][0]
        self.assertTrue(0.0 <= nr[0] < nr[2] <= 1.0)
        self.assertTrue(0.0 <= nr[1] < nr[3] <= 1.0)

    def test_multi_line_passage_highlighting(self):
        # Snippet crosses line break in source document
        snippet = "The seismic resisting system consists of special reinforced concrete shear walls located symmetrically"
        res = locate_evidence(self.pdf_path, 1, snippet)
        self.assertTrue(res["found"])
        self.assertIn(res["match_type"], ("exact", "multiline"))
        self.assertGreater(len(res["rects"]), 0)
        # Bounding box covers both lines
        r = res["rects"][0]
        self.assertGreater(r[3] - r[1], 15)  # Height covers multiple lines

    def test_page_accuracy(self):
        # Text exists on page 2, searching page 1 must NOT find it
        snippet = "Concrete Compressive Strength f'c = 40 MPa"
        res_p1 = locate_evidence(self.pdf_path, 1, snippet)
        self.assertFalse(res_p1["found"])
        self.assertEqual(res_p1["rects"], [])

        # Searching the correct page (page 2) finds it
        res_p2 = locate_evidence(self.pdf_path, 2, snippet)
        self.assertTrue(res_p2["found"])
        self.assertEqual(res_p2["page"], 2)

    def test_page_rotation_handling(self):
        snippet = "Maximum allowable soil bearing pressure is 250 kPa"
        res = locate_evidence(self.rotated_pdf_path, 1, snippet)
        self.assertTrue(res["found"])
        self.assertEqual(res["rotation"], 90)
        self.assertGreater(len(res["display_rects"]), 0)
        disp_r = res["display_rects"][0]
        # Transformed coordinates must be valid
        self.assertGreater(disp_r[2], disp_r[0])
        self.assertGreater(disp_r[3], disp_r[1])

    def test_missing_evidence_fail_closed(self):
        # Asking for a passage not present in the document
        fake_snippet = "Post-tensioned unbonded tendon layout with 50 strands"
        res = locate_evidence(self.pdf_path, 1, fake_snippet)
        self.assertFalse(res["found"])
        self.assertEqual(res["rects"], [])
        self.assertEqual(res["display_rects"], [])
        self.assertIn("could not be established", res["reason"])

    def test_ambiguous_lone_keyword_rejection(self):
        # Single stopword or ambiguous generic term must be rejected to prevent false positive highlights
        for ambiguous in ["the", "note", "plan", "elevation", "rev"]:
            res = locate_evidence(self.pdf_path, 1, ambiguous)
            self.assertFalse(res["found"], f"Should reject ambiguous keyword: {ambiguous}")
            self.assertEqual(res["rects"], [])

    def test_scanned_pdf_fallback_via_metadata(self):
        # Emulate a scanned document page with no native text but OCR metadata
        mock_meta = {
            "pages": [
                {
                    "ocr": {
                        "boxes": [
                            {"text": "Contractor", "box": [100, 200, 160, 215]},
                            {"text": "Shall", "box": [165, 200, 195, 215]},
                            {"text": "Verify", "box": [200, 200, 240, 215]},
                            {"text": "All", "box": [245, 200, 265, 215]},
                            {"text": "Dimensions", "box": [270, 200, 340, 215]},
                        ]
                    }
                }
            ]
        }
        res = locate_evidence(self.pdf_path, 1, "Contractor Shall Verify All Dimensions", meta=mock_meta)
        self.assertTrue(res["found"])
        self.assertEqual(res["match_type"], "ocr_fallback")
        self.assertEqual(len(res["rects"]), 1)
        r = res["rects"][0]
        self.assertEqual(r[0], 100)
        self.assertEqual(r[2], 340)

    def test_non_destructive_annotated_copy(self):
        with open(self.pdf_path, "rb") as f:
            orig_bytes = f.read()
        annotated_out = os.path.join(self.temp_dir.name, "annotated_copy.pdf")

        highlights = [
            {"page": 1, "rects": [[72, 100, 400, 120]]}
        ]
        created_path = create_annotated_copy(self.pdf_path, highlights, annotated_out)
        self.assertTrue(os.path.isfile(created_path))

        # Check original PDF is untouched byte-for-byte
        with open(self.pdf_path, "rb") as f:
            after_bytes = f.read()
        self.assertEqual(orig_bytes, after_bytes)

        # Check annotated copy has the annotation
        doc_annot = fitz.open(created_path)
        page1 = doc_annot[0]
        annots = list(page1.annots())
        self.assertEqual(len(annots), 1)
        self.assertEqual(annots[0].type[1], "Highlight")
        doc_annot.close()

    def test_render_highlighted_page_pixmap(self):
        pix_bytes = render_highlighted_page_pixmap(
            self.pdf_path, 1, [[72, 100, 400, 120]], scale=1.5
        )
        self.assertIsInstance(pix_bytes, bytes)
        self.assertGreater(len(pix_bytes), 1000)
        # Check PNG header: \x89PNG\r\n\x1a\n
        self.assertTrue(pix_bytes.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
