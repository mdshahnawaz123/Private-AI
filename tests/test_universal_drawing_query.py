import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from engines.universal_drawing_engine import get_universal_drawing_engine
from intelligence.exact_answers import exact_answer


class UniversalDrawingQueryTests(unittest.TestCase):
    def test_civil_stormwater_infrastructure_extraction_and_query(self):
        text = (
            "New-SW-MH-11 GL: 25.42 IL:23.71 D:1.71 E:482640.98 N:2762122.45\n"
            "New-SW-MH-34 GL: 24.77 IL:19.60 D:5.17 E:482416.08 N:2762018.10\n"
            "CB-13 CL: 24.451m IL:20.774m H: 3.677m\n"
            "Ø250 UPVC L: 44.860m S: 0.370%\n"
            "1. THIS DRAWING IS NOT TO BE SCALED.\n"
            "2. ALL DIMENSIONS SHOWN ARE IN METERS UNLESS SPECIFICALLY INDICATED OTHERWISE.\n"
            "7. CONCRETE ENCASEMENT SHALL BE PROVIDED WHERE PIPE COVER IS LESS THAN 1.2 M.\n"
            "C3085-DWG-3EH6105-SW-2005001\n"
            "SITEWIDE OVERALL PROPOSED STORMWATER NETWORK AND TIE-IN CONNECTIONS\n"
        )
        engine = get_universal_drawing_engine()
        infra = engine._extract_infrastructure(text)

        self.assertIn("SW-MH-11", infra["manholes"])
        mh11 = infra["manholes"]["SW-MH-11"]
        self.assertEqual(mh11["ground_level"], "25.42")
        self.assertEqual(mh11["invert_level"], "23.71")
        self.assertEqual(mh11["depth"], "1.71")
        self.assertEqual(mh11["easting"], "482640.98")
        self.assertEqual(mh11["northing"], "2762122.45")

        self.assertIn("CB-13", infra["catch_basins"])
        cb13 = infra["catch_basins"]["CB-13"]
        self.assertEqual(cb13["cover_level"], "24.451m")
        self.assertEqual(cb13["invert_level"], "20.774m")
        self.assertEqual(cb13["height"], "3.677m")

        self.assertTrue(len(infra["pipes"]) >= 1)
        self.assertEqual(infra["pipes"][0]["length"], "44.860m")
        self.assertEqual(infra["pipes"][0]["slope"], "0.370%")

        # Test querying via exact_answer pipeline
        with tempfile.TemporaryDirectory() as root:
            doc_path = Path(root) / "stormwater.pdf"
            doc_path.write_bytes(b"%PDF-1.4 synthetic drawing")
            meta = {
                "source_sha256": hashlib.sha256(doc_path.read_bytes()).hexdigest(),
                "pages": [{
                    "page": 1,
                    "text": text,
                    "drawing_schema": {
                        "is_drawing": True,
                        "drawing_number": "C3085-DWG-3EH6105-SW-2005001",
                        "drawing_title": "SITEWIDE OVERALL PROPOSED STORMWATER NETWORK",
                        "infrastructure": infra,
                        "general_notes": [
                            "1. THIS DRAWING IS NOT TO BE SCALED.",
                            "2. ALL DIMENSIONS SHOWN ARE IN METERS UNLESS SPECIFICALLY INDICATED OTHERWISE.",
                            "7. CONCRETE ENCASEMENT SHALL BE PROVIDED WHERE PIPE COVER IS LESS THAN 1.2 M."
                        ]
                    }
                }]
            }
            sidecar = Path(str(doc_path) + ".index.json")
            sidecar.write_text(json.dumps(meta), encoding="utf-8")
            docs = [{"path": str(doc_path), "filename": doc_path.name, "status": "ready"}]

            # 1. Query Manhole
            ans_mh = exact_answer("What is the invert level and coordinates of New-SW-MH-11?", docs)
            self.assertIsNotNone(ans_mh)
            self.assertEqual(ans_mh["status"], "SUCCESS")
            self.assertIn("IL = 23.71 m", ans_mh["answer"])
            self.assertIn("482640.98", ans_mh["answer"])
            self.assertIn("2762122.45", ans_mh["answer"])

            # 2. Query Catch Basin
            ans_cb = exact_answer("What is the level and height for CB-13?", docs)
            self.assertIsNotNone(ans_cb)
            self.assertEqual(ans_cb["status"], "SUCCESS")
            self.assertIn("Cover Level = 24.451m", ans_cb["answer"])
            self.assertIn("Invert Level = 20.774m", ans_cb["answer"])

            # 3. Query General Note
            ans_note = exact_answer("What do the general notes state about pipe cover?", docs)
            self.assertIsNotNone(ans_note)
            self.assertEqual(ans_note["status"], "SUCCESS")
            self.assertIn("CONCRETE ENCASEMENT SHALL BE PROVIDED WHERE PIPE COVER IS LESS THAN 1.2 M", ans_note["answer"])
