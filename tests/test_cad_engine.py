"""
Unit tests for CADCraft CAD service and API router in Expo Design AI.
Validates:
- DXF generation and parsing round-trip
- Architectural sample drawings generation (apartment plan, structural grid, mechanical bracket)
- API endpoints: /api/v1/cad/samples, /api/v1/cad/sample/{id}, /api/v1/cad/parse, /api/v1/cad/export-dxf, /api/v1/cad/save
"""
import io
import json
import os
import tempfile
import unittest
import uuid
from fastapi.testclient import TestClient

import auth
import db
from main import app
from services.cad_service import CadService


class TestCadService(unittest.TestCase):
    def test_apartment_sample_generation(self):
        sample = CadService.load_sample_drawing("sample_apartment_plan")
        self.assertTrue(sample["success"])
        self.assertGreater(sample["entity_count"], 15)
        self.assertGreater(len(sample["layers"]), 3)
        self.assertIn("extents", sample)
        self.assertEqual(sample["extents"]["width"], 14000)

    def test_structural_grid_sample(self):
        sample = CadService.load_sample_drawing("sample_structural_core")
        self.assertTrue(sample["success"])
        self.assertGreater(sample["entity_count"], 10)
        layer_names = [l["name"] for l in sample["layers"]]
        self.assertIn("GRID", layer_names)
        self.assertIn("COLUMNS", layer_names)

    def test_mechanical_bracket_sample(self):
        sample = CadService.load_sample_drawing("sample_mechanical_bracket")
        self.assertTrue(sample["success"])
        types = [e["type"] for e in sample["entities"]]
        self.assertIn("CIRCLE", types)
        self.assertIn("DIMENSION", types)

    def test_dxf_round_trip(self):
        # Generate sample entities
        sample = CadService.load_sample_drawing("sample_apartment_plan")
        dxf_str = CadService.generate_dxf(sample["entities"], sample["layers"], title="Test Plan")
        self.assertIn("SECTION", dxf_str)
        self.assertIn("ENTITIES", dxf_str)

        # Parse generated DXF back
        parsed = CadService.parse_dxf_stream(io.StringIO(dxf_str))
        self.assertTrue(parsed["success"])
        self.assertGreater(parsed["entity_count"], 10)
        self.assertIn("extents", parsed)

    def test_dwg_converter_detection_and_fallback(self):
        from engines.cad_engine import CadIntelligenceEngine
        eng = CadIntelligenceEngine()
        converter = eng.find_oda_converter()
        self.assertIsNotNone(converter)
        self.assertTrue(os.path.exists(converter))


class TestCadAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.username = f"cad_user_{uuid.uuid4().hex[:6]}"
        cls.user = db.create_user(cls.username, "pass123", role="admin")
        cls.token = auth.make_token(cls.user)
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    def setUp(self):
        self.client = TestClient(app)
        self.project_name = f"cad_proj_{uuid.uuid4().hex[:6]}"
        with db.SessionLocal() as s:
            proj = db.Project(name=self.project_name)
            s.add(proj)
            s.flush()
            self.project_id = proj.id
            s.add(db.ProjectMember(project_id=self.project_id, user_id=self.user["id"]))
            s.commit()

    def test_list_samples_endpoint(self):
        res = self.client.get("/api/v1/cad/samples", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("samples", data)
        self.assertGreaterEqual(len(data["samples"]), 3)

    def test_get_sample_detail_endpoint(self):
        res = self.client.get("/api/v1/cad/sample/sample_apartment_plan", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertIn("entities", data)

    def test_export_dxf_endpoint(self):
        sample = CadService.load_sample_drawing("sample_apartment_plan")
        payload = {
            "filename": "apartment.dxf",
            "entities": sample["entities"],
            "layers": sample["layers"],
        }
        res = self.client.post("/api/v1/cad/export-dxf", headers=self.headers, json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("content-type"), "application/dxf")
        self.assertIn("attachment; filename=\"apartment.dxf\"", res.headers.get("content-disposition", ""))
        self.assertIn("SECTION", res.text)

    def test_save_cad_to_project_endpoint(self):
        sample = CadService.load_sample_drawing("sample_mechanical_bracket")
        payload = {
            "project": self.project_name,
            "filename": "bracket.dxf",
            "entities": sample["entities"],
            "layers": sample["layers"],
            "folder": "Drawings",
        }
        res = self.client.post("/api/v1/cad/save", headers=self.headers, json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["filename"], "bracket.dxf")

    def test_parse_uploaded_dxf_endpoint(self):
        sample = CadService.load_sample_drawing("sample_apartment_plan")
        dxf_content = CadService.generate_dxf(sample["entities"], sample["layers"])
        files = {"file": ("test_apartment.dxf", io.BytesIO(dxf_content.encode("utf-8")), "application/dxf")}
        res = self.client.post("/api/v1/cad/parse", headers=self.headers, files=files)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["filename"], "test_apartment.dxf")
        self.assertGreater(data["entity_count"], 10)

    def test_parse_project_drawing_endpoint(self):
        # Save a drawing first
        sample = CadService.load_sample_drawing("sample_structural_core")
        save_payload = {
            "project": self.project_name,
            "filename": "core_plan.dxf",
            "entities": sample["entities"],
            "layers": sample["layers"],
            "folder": "Drawings",
        }
        save_res = self.client.post("/api/v1/cad/save", headers=self.headers, json=save_payload)
        self.assertEqual(save_res.status_code, 200)

        # Parse from project
        form_data = {
            "project": self.project_name,
            "filename": "core_plan.dxf",
        }
        res = self.client.post("/api/v1/cad/parse", headers=self.headers, data=form_data)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["filename"], "core_plan.dxf")
        self.assertGreater(data["entity_count"], 5)

    def test_render_cad_for_ai_endpoint(self):
        sample = CadService.load_sample_drawing("sample_apartment_plan")
        payload = {
            "project": self.project_name,
            "entities": sample["entities"],
            "width": 512,
            "height": 512,
            "invert_colors": True,
        }
        res = self.client.post("/api/v1/cad/render-for-ai", headers=self.headers, json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertIn("input_image_path", data)
        self.assertIn("input_image_url", data)

    def test_agent_cad_inspect(self):
        from intelligence.agent_loop import Agent
        agent = Agent(self.project_name, self.user, "inspect apartment", [], lambda q: ([], ""), "http://127.0.0.1:11434", "qwen3.5:9b")
        res = agent.t_cad_inspect("sample_apartment_plan")
        self.assertIn("Apartment Floor Plan", res)
        self.assertIn("LIVING & DINING ROOM", res)
        self.assertIn("[Open in CADCraft Studio](cadcraft:sample_apartment_plan)", res)

    def test_agent_cad_draft(self):
        from intelligence.agent_loop import Agent
        agent = Agent(self.project_name, self.user, "draft floor plan", [], lambda q: ([], ""), "http://127.0.0.1:11434", "qwen3.5:9b")
        res = agent.t_cad_draft("apartment", "agent_plan.dxf", "Agent Floor Plan")
        self.assertIn("TEMPLATE drawing", res)
        self.assertIn("[Open in CADCraft Studio](cadcraft:agent_plan.dxf)", res)


if __name__ == "__main__":
    unittest.main()

