import io
import os
import shutil
import tempfile
import unittest
import uuid
from unittest.mock import AsyncMock, patch
from PIL import Image

from fastapi.testclient import TestClient

import auth
import db
from main import app
from services.image_engine.api import get_job_service, set_job_service
from services.image_engine.comfyui_client import ComfyUIClient
from services.image_engine.image_storage import ImageStorage
from services.image_engine.job_service import JobService
from services.image_engine.schemas import EngineStatus
from services.image_engine.workflow_registry import WorkflowRegistry


class TestImageEngineAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

        # Create test users
        cls.admin_username = f"admin_{uuid.uuid4().hex[:6]}"
        cls.user_a_username = f"usera_{uuid.uuid4().hex[:6]}"
        cls.user_b_username = f"userb_{uuid.uuid4().hex[:6]}"

        cls.admin_user = db.create_user(cls.admin_username, "pass123", role="admin")
        cls.user_a = db.create_user(cls.user_a_username, "pass123", role="user")
        cls.user_b = db.create_user(cls.user_b_username, "pass123", role="user")

        cls.admin_token = auth.make_token(cls.admin_user)
        cls.user_a_token = auth.make_token(cls.user_a)
        cls.user_b_token = auth.make_token(cls.user_b)

        cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}"}
        cls.user_a_headers = {"Authorization": f"Bearer {cls.user_a_token}"}
        cls.user_b_headers = {"Authorization": f"Bearer {cls.user_b_token}"}

    @classmethod
    def tearDownClass(cls):
        with db.SessionLocal() as s:
            s.query(db.User).filter(
                db.User.id.in_([cls.admin_user["id"], cls.user_a["id"], cls.user_b["id"]])
            ).delete(synchronize_session=False)
            s.commit()

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.client = TestClient(app)

        # Create isolated projects
        self.project_a = f"proj_a_{uuid.uuid4().hex[:6]}"
        self.project_b = f"proj_b_{uuid.uuid4().hex[:6]}"

        with db.SessionLocal() as s:
            p_a = db.Project(name=self.project_a)
            p_b = db.Project(name=self.project_b)
            s.add_all([p_a, p_b])
            s.flush()
            self.pid_a = p_a.id
            self.pid_b = p_b.id

            # user_a is member of project_a only
            s.add(db.ProjectMember(project_id=self.pid_a, user_id=self.user_a["id"]))
            s.commit()

        # Set up isolated storage and mock ComfyUIClient
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
            active_model="sdxl_base.safetensors",
        )
        self.mock_comfy.submit_prompt.return_value = {
            "prompt_id": "prompt-mock-123",
            "number": 1,
        }
        self.mock_comfy.interrupt.return_value = True
        mock_info = {}
        for graph in self.registry._raw_workflows.values():
            for node in graph.values():
                spec = mock_info.setdefault(node.get("class_type"), {"input": {"required": {}}})
                for k, v in node.get("inputs", {}).items():
                    if isinstance(k, str) and k.endswith("_name"):
                        spec["input"]["required"][k] = [[v]]
        self.mock_comfy.get_object_info.return_value = mock_info

        self.test_job_service = JobService(
            comfy_client=self.mock_comfy,
            workflow_registry=self.registry,
            storage=self.storage,
        )
        set_job_service(self.test_job_service)

    def tearDown(self):
        set_job_service(None)

        with db.SessionLocal() as s:
            s.query(db.ProjectMember).filter(
                db.ProjectMember.project_id.in_([self.pid_a, self.pid_b])
            ).delete(synchronize_session=False)

            jobs = s.query(db.ImageJob).filter(
                db.ImageJob.project_id.in_([self.pid_a, self.pid_b])
            ).all()
            for j in jobs:
                s.query(db.ImageOutput).filter_by(job_id=j.id).delete()
            s.query(db.ImageJob).filter(
                db.ImageJob.project_id.in_([self.pid_a, self.pid_b])
            ).delete(synchronize_session=False)

            s.query(db.Project).filter(
                db.Project.id.in_([self.pid_a, self.pid_b])
            ).delete(synchronize_session=False)
            s.commit()

        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_sample_png(self, width: int = 128, height: int = 128) -> bytes:
        img = Image.new("RGB", (width, height), color=(60, 90, 120))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    # ── Authentication & RBAC Tests ──

    def test_unauthenticated_requests_return_401(self):
        res = self.client.get("/api/image-engine/status")
        self.assertEqual(res.status_code, 401)

        res = self.client.get("/api/image-engine/workflows")
        self.assertEqual(res.status_code, 401)

        res = self.client.post("/api/image-engine/jobs", json={})
        self.assertEqual(res.status_code, 401)

    def test_get_status_authenticated_returns_200(self):
        res = self.client.get("/api/image-engine/status", headers=self.user_a_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["available"])
        self.assertEqual(data["base_url"], "http://127.0.0.1:8188")
        self.assertEqual(data["vram_total_mb"], 16384)

    def test_get_workflows_authenticated_returns_200(self):
        res = self.client.get("/api/image-engine/workflows", headers=self.user_a_headers)
        self.assertEqual(res.status_code, 200)
        workflows = res.json()
        self.assertGreaterEqual(len(workflows), 3)
        wf_ids = [w["id"] for w in workflows]
        self.assertIn("architecture_concept", wf_ids)
        self.assertIn("sketch_to_render", wf_ids)
        self.assertIn("render_enhancement", wf_ids)

    # ── Job Submission Tests ──

    def test_submit_job_json_success(self):
        payload = {
            "project": self.project_a,
            "workflow_id": "architecture_concept",
            "prompt": "brutalist concrete library with atrium",
            "width": 1024,
            "height": 768,
            "steps": 30,
            "seed": 12345,
        }
        res = self.client.post("/api/image-engine/jobs", json=payload, headers=self.user_a_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["job_id"].startswith("imgjob-"))
        self.assertEqual(data["status"], "queued")
        self.assertEqual(data["project"], self.project_a)

    def test_submit_job_unauthorized_project_returns_403(self):
        payload = {
            "project": self.project_b,  # user_a is not a member of project_b
            "workflow_id": "architecture_concept",
            "prompt": "modern residence",
        }
        res = self.client.post("/api/image-engine/jobs", json=payload, headers=self.user_a_headers)
        self.assertEqual(res.status_code, 403)

    def test_submit_job_nonexistent_project_returns_404(self):
        payload = {
            "project": "nonexistent_project_12345",
            "workflow_id": "architecture_concept",
            "prompt": "modern residence",
        }
        res = self.client.post("/api/image-engine/jobs", json=payload, headers=self.admin_headers)
        self.assertEqual(res.status_code, 404)

    def test_submit_job_invalid_workflow_returns_404(self):
        payload = {
            "project": self.project_a,
            "workflow_id": "unknown_workflow_id",
            "prompt": "modern residence",
        }
        res = self.client.post("/api/image-engine/jobs", json=payload, headers=self.user_a_headers)
        self.assertEqual(res.status_code, 404)

    def test_submit_job_invalid_resolution_returns_422(self):
        payload = {
            "project": self.project_a,
            "workflow_id": "architecture_concept",
            "prompt": "modern residence",
            "width": 300,  # Below minimum (512) and not a multiple of 64
        }
        res = self.client.post("/api/image-engine/jobs", json=payload, headers=self.user_a_headers)
        self.assertEqual(res.status_code, 422)

    def test_submit_job_multipart_form_with_sketch_upload(self):
        png_bytes = self._create_sample_png(256, 256)
        files = {"input_image": ("sketch.png", png_bytes, "image/png")}
        data = {
            "project": self.project_a,
            "workflow_id": "sketch_to_render",
            "prompt": "convert architectural sketch into modern villa",
            "width": "1024",
            "height": "1024",
        }
        res = self.client.post(
            "/api/image-engine/jobs",
            data=data,
            files=files,
            headers=self.user_a_headers,
        )
        self.assertEqual(res.status_code, 200)
        resp_data = res.json()
        self.assertEqual(resp_data["status"], "queued")
        self.assertEqual(resp_data["workflow_id"], "sketch_to_render")

    # ── Job Status & Output Retrieval Tests ──

    def test_list_and_get_job_status(self):
        # Create job
        payload = {
            "project": self.project_a,
            "workflow_id": "architecture_concept",
            "prompt": "modern residence",
        }
        submit_res = self.client.post("/api/image-engine/jobs", json=payload, headers=self.user_a_headers)
        job_id = submit_res.json()["job_id"]

        # List jobs
        list_res = self.client.get(f"/api/image-engine/jobs?project={self.project_a}", headers=self.user_a_headers)
        self.assertEqual(list_res.status_code, 200)
        jobs = list_res.json()
        self.assertGreaterEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["job_id"], job_id)

        # Get job by ID
        get_res = self.client.get(f"/api/image-engine/jobs/{job_id}", headers=self.user_a_headers)
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()["job_id"], job_id)

        # User B cannot access Job in Project A
        unauth_res = self.client.get(f"/api/image-engine/jobs/{job_id}", headers=self.user_b_headers)
        self.assertEqual(unauth_res.status_code, 403)

    def test_download_output_file_and_thumbnail(self):
        # Seed an output directly in storage and db
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        db.create_image_job(
            job_id=job_id,
            project_id=self.pid_a,
            user_id=self.user_a["id"],
            workflow_id="architecture_concept",
            input_params={"prompt": "test"},
        )
        png_bytes = self._create_sample_png(512, 512)
        job_out = self.storage.save_output_image(
            project=self.project_a,
            job_id=job_id,
            image_bytes=png_bytes,
            filename="render_final.png",
        )

        # Download full file
        file_res = self.client.get(
            f"/api/image-engine/outputs/{job_out.output_id}/file",
            headers=self.user_a_headers,
        )
        self.assertEqual(file_res.status_code, 200)
        self.assertEqual(file_res.headers.get("content-type"), "image/png")
        self.assertEqual(file_res.content, png_bytes)

        # Download thumbnail
        thumb_res = self.client.get(
            f"/api/image-engine/outputs/{job_out.output_id}/thumb",
            headers=self.user_a_headers,
        )
        self.assertEqual(thumb_res.status_code, 200)
        self.assertEqual(thumb_res.headers.get("content-type"), "image/png")

        # User B denied access to Project A's output
        forbidden_res = self.client.get(
            f"/api/image-engine/outputs/{job_out.output_id}/file",
            headers=self.user_b_headers,
        )
        self.assertEqual(forbidden_res.status_code, 403)

    # ── Job Cancellation Tests ──

    def test_cancel_job_permissions(self):
        payload = {
            "project": self.project_a,
            "workflow_id": "architecture_concept",
            "prompt": "test cancel",
        }
        submit_res = self.client.post("/api/image-engine/jobs", json=payload, headers=self.user_a_headers)
        job_id = submit_res.json()["job_id"]

        # User B cannot cancel User A's job
        cancel_unauth = self.client.post(
            f"/api/image-engine/jobs/{job_id}/cancel",
            headers=self.user_b_headers,
        )
        self.assertEqual(cancel_unauth.status_code, 403)

        # User A can cancel own job
        cancel_res = self.client.post(
            f"/api/image-engine/jobs/{job_id}/cancel",
            headers=self.user_a_headers,
        )
        self.assertEqual(cancel_res.status_code, 200)
        self.assertEqual(cancel_res.json()["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
