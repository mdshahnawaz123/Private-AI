"""
Unit tests for Architectural Prompt Reasoning Integration.

Validates:
- services.image_engine.prompt_reasoner: enhance_architectural_prompt
- POST /api/image-engine/enhance-prompt endpoint
- JobService execution when enhance_prompt=True
- Fallback resilience when Ollama is offline or returns unexpected data
"""
import asyncio
import io
import json
import tempfile
import unittest
import uuid
from unittest.mock import AsyncMock, patch, MagicMock
from PIL import Image

from fastapi.testclient import TestClient
import auth
import db
from main import app
from services.image_engine.api import get_job_service, set_job_service
from services.image_engine.comfyui_client import ComfyUIClient
from services.image_engine.image_storage import ImageStorage
from services.image_engine.job_service import JobService
from services.image_engine.prompt_reasoner import (
    enhance_architectural_prompt,
    REASONING_MODEL,
)
from services.image_engine.schemas import (
    EngineStatus,
    JobSubmissionRequest,
    PromptEnhanceRequest,
    PromptEnhanceResponse,
)
from services.image_engine.workflow_registry import WorkflowRegistry


class TestPromptReasoner(unittest.IsolatedAsyncioTestCase):
    async def test_enhance_prompt_success(self):
        mock_response = {
            "model": "qwen3.5:9b",
            "message": {
                "content": json.dumps({
                    "reasoning": "The design uses limestone to blend with desert dunes.",
                    "enhanced_prompt": "Modern luxury villa with limestone cladding, floor-to-ceiling glass, serene pool.",
                })
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_resp_obj = MagicMock()
            mock_resp_obj.json.return_value = mock_response
            mock_resp_obj.raise_for_status = MagicMock()
            mock_post.return_value = mock_resp_obj

            res = await enhance_architectural_prompt(
                prompt="Modern desert villa",
                building_type="Villa",
                architectural_style="Contemporary",
                unload_vram=True,
            )

            self.assertTrue(res["success"])
            self.assertEqual(res["original_prompt"], "Modern desert villa")
            self.assertEqual(
                res["enhanced_prompt"],
                "Modern luxury villa with limestone cladding, floor-to-ceiling glass, serene pool.",
            )
            self.assertEqual(
                res["reasoning"],
                "The design uses limestone to blend with desert dunes.",
            )

            # Verify keep_alive: 0 was sent to unload GPU VRAM immediately
            sent_payload = mock_post.call_args[1]["json"]
            self.assertEqual(sent_payload["keep_alive"], 0)
            self.assertEqual(sent_payload["format"], "json")
            self.assertFalse(sent_payload["think"])

    async def test_enhance_prompt_with_g_plus_10_invariant_preservation(self):
        mock_response = {
            "model": "qwen3.5:9b",
            "message": {
                "content": json.dumps({
                    "preserved_constraints": ["G+10 residential tower", "podium base"],
                    "architectural_reasoning": "Massing articulated with ground podium and 10 upper stories with continuous slab edges.",
                    "enhanced_prompt": "Eye-level 2-point perspective architectural render of a G+10 residential tower in Dubai. Double-height podium transitions to 10 distinct upper floors.",
                    "design_options": [
                        {
                            "id": "option_a",
                            "title": "Biophilic & Terraced",
                            "style": "Biophilic Modernism",
                            "prompt": "G+10 residential tower with biophilic balconies and lush planters.",
                            "rationale": "Terraced green buffers.",
                        },
                        {
                            "id": "option_b",
                            "title": "High-Tech Glass & Metallic",
                            "style": "Contemporary High-Tech",
                            "prompt": "G+10 residential tower with bronze curtain wall.",
                            "rationale": "High-performance facade.",
                        },
                    ]
                })
            }
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_resp_obj = MagicMock()
            mock_resp_obj.json.return_value = mock_response
            mock_resp_obj.raise_for_status = MagicMock()
            mock_post.return_value = mock_resp_obj

            res = await enhance_architectural_prompt(
                prompt="G+10 residential tower in Dubai",
                building_type="Residential",
                architectural_style="Contemporary",
                unload_vram=True,
            )

            self.assertTrue(res["success"])
            self.assertIn("G+10", res["enhanced_prompt"])
            self.assertIn("G+10", " ".join(res["preserved_constraints"]))
            self.assertEqual(len(res["design_options"]), 2)
            self.assertEqual(res["design_options"][0]["id"], "option_a")
            self.assertIn("G+10", res["design_options"][0]["prompt"])

    async def test_enhance_prompt_offline_fallback(self):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = Exception("Connection refused to Ollama")

            res = await enhance_architectural_prompt(
                prompt="G+10 futuristic residential tower",
                building_type="Residential",
                architectural_style="Parametric",
            )

            self.assertFalse(res["success"])
            # Fallback must preserve G+10
            self.assertIn("G+10", res["enhanced_prompt"])
            self.assertIn("G+10", " ".join(res["preserved_constraints"]))
            self.assertGreaterEqual(len(res["design_options"]), 1)
            self.assertIn("G+10", res["design_options"][0]["prompt"])
            self.assertIn("fallback", res["reasoning"].lower())

    async def test_enhance_prompt_empty_input(self):
        res = await enhance_architectural_prompt("")
        self.assertFalse(res["success"])
        self.assertEqual(res["enhanced_prompt"], "")


class TestReasoningAPIAndJobExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.username = f"user_{uuid.uuid4().hex[:6]}"
        cls.user = db.create_user(cls.username, "pass123", role="user")
        cls.token = auth.make_token(cls.user)
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    @classmethod
    def tearDownClass(cls):
        with db.SessionLocal() as s:
            job_ids = [j.id for j in s.query(db.ImageJob).filter_by(user_id=cls.user["id"]).all()]
            if job_ids:
                s.query(db.ImageOutput).filter(db.ImageOutput.job_id.in_(job_ids)).delete(synchronize_session=False)
                s.query(db.ImageJob).filter_by(user_id=cls.user["id"]).delete(synchronize_session=False)
            s.query(db.ProjectMember).filter_by(user_id=cls.user["id"]).delete(synchronize_session=False)
            s.query(db.User).filter_by(id=cls.user["id"]).delete(synchronize_session=False)
            s.commit()

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.client = TestClient(app)
        self.project_name = f"reason_proj_{uuid.uuid4().hex[:6]}"

        with db.SessionLocal() as s:
            proj = db.Project(name=self.project_name)
            s.add(proj)
            s.flush()
            self.project_id = proj.id
            s.add(db.ProjectMember(project_id=self.project_id, user_id=self.user["id"]))
            s.commit()

        self.storage = ImageStorage(data_dir=self.temp_dir)
        self.registry = WorkflowRegistry(workflows_dir="workflows")
        self.registry.discover_and_load()

        self.mock_comfy = AsyncMock(spec=ComfyUIClient)
        self.mock_comfy.base_url = "http://127.0.0.1:8188"
        self.mock_comfy.check_health.return_value = EngineStatus(
            available=True,
            base_url="http://127.0.0.1:8188",
            vram_total_mb=16384,
            vram_free_mb=12288,
        )
        self.mock_comfy.submit_prompt.return_value = {"prompt_id": "prompt-mock-123", "number": 1}
        self.mock_comfy.interrupt.return_value = True

        mock_info = {}
        for graph in self.registry._raw_workflows.values():
            for node in graph.values():
                spec = mock_info.setdefault(node.get("class_type"), {"input": {"required": {}}})
                for k, v in node.get("inputs", {}).items():
                    if isinstance(k, str) and k.endswith("_name"):
                        choices = spec["input"]["required"].setdefault(k, [[]])[0]
                        if v not in choices: choices.append(v)
        self.mock_comfy.get_object_info.return_value = mock_info

        self.job_service = JobService(
            comfy_client=self.mock_comfy,
            workflow_registry=self.registry,
            storage=self.storage,
        )
        set_job_service(self.job_service)

    def test_enhance_prompt_endpoint_success(self):
        mock_result = {
            "success": True,
            "original_prompt": "Minimalist pavilion",
            "enhanced_prompt": "Minimalist glass and timber pavilion on reflective pool.",
            "reasoning": "Emphasizes clarity of structural grid and natural daylighting.",
            "preserved_constraints": ["Pavilion typology", "Reflective pool"],
            "design_options": [
                {
                    "id": "option_a",
                    "title": "Biophilic & Terraced",
                    "style": "Biophilic Modernism",
                    "prompt": "Minimalist glass and timber pavilion with biophilic roof garden.",
                    "rationale": "Harmonizes with surrounding water.",
                }
            ],
            "model": "qwen3.5:9b",
        }

        with patch(
            "services.image_engine.design_brief.generate_design_brief",
            new_callable=AsyncMock,
        ) as mock_enhance:
            mock_enhance.return_value = mock_result

            res = self.client.post(
                "/api/image-engine/enhance-prompt",
                headers=self.headers,
                json={
                    "prompt": "Minimalist pavilion",
                    "building_type": "Pavilion",
                    "architectural_style": "Minimalist",
                },
            )

            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data["success"])
            self.assertEqual(
                data["enhanced_prompt"],
                "Minimalist glass and timber pavilion on reflective pool.",
            )
            self.assertEqual(
                data["reasoning"],
                "Emphasizes clarity of structural grid and natural daylighting.",
            )
            self.assertEqual(data["preserved_constraints"], ["Pavilion typology", "Reflective pool"])
            self.assertEqual(len(data["design_options"]), 1)
            self.assertEqual(data["design_options"][0]["id"], "option_a")

    def test_job_submission_with_enhance_prompt_flag(self):
        payload = {
            "project": self.project_name,
            "workflow_id": "architecture_concept",
            "prompt": "Civic museum facade",
            "enhance_prompt": True,
            "width": 1024,
            "height": 1024,
            "steps": 4,
            "cfg": 1.0,
        }
        res = self.client.post("/api/image-engine/jobs", headers=self.headers, json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "queued")
        self.assertIn("job_id", data)


if __name__ == "__main__":
    unittest.main()
