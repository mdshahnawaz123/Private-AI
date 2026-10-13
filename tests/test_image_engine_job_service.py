import asyncio
import io
import os
import shutil
import tempfile
import unittest
import uuid
from unittest.mock import AsyncMock, patch
from PIL import Image

import db
from services.image_engine.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUIOutOfMemoryError,
)
from services.image_engine.image_storage import ImageStorage
from services.image_engine.job_service import JobService
from services.image_engine.schemas import (
    EngineStatus,
    JobSubmissionRequest,
)
from services.image_engine.workflow_registry import WorkflowRegistry


class TestJobService(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Create isolated temp data directory
        self.temp_dir = tempfile.mkdtemp()
        self.storage = ImageStorage(data_dir=self.temp_dir)

        # Create a test project in SQLite
        self.project_name = f"test_proj_{uuid.uuid4().hex[:8]}"
        with db.SessionLocal() as s:
            proj = db.Project(name=self.project_name)
            s.add(proj)
            s.commit()
            self.project_id = proj.id

        # Real registry with starter workflows
        self.registry = WorkflowRegistry(workflows_dir="workflows")
        self.registry.discover_and_load()

        # Mock ComfyUIClient
        self.mock_client = AsyncMock(spec=ComfyUIClient)
        self.mock_client.base_url = "http://127.0.0.1:8188"
        self.mock_client.check_health.return_value = EngineStatus(
            available=True,
            base_url="http://127.0.0.1:8188",
            vram_total_mb=16384,
            vram_free_mb=12288,
        )
        self.mock_client.submit_prompt.return_value = {
            "prompt_id": "comfy-prompt-001",
            "number": 1,
        }
        mock_info = {}
        for graph in self.registry._raw_workflows.values():
            for node in graph.values():
                spec = mock_info.setdefault(node.get("class_type"), {"input": {"required": {}}})
                for k, v in node.get("inputs", {}).items():
                    if isinstance(k, str) and k.endswith("_name"):
                        spec["input"]["required"][k] = [[v]]
        self.mock_client.get_object_info.return_value = mock_info

        # Create 128x128 sample image bytes
        sample_img = Image.new("RGB", (128, 128), color=(100, 150, 200))
        buf = io.BytesIO()
        sample_img.save(buf, format="PNG")
        self.sample_png_bytes = buf.getvalue()

        self.mock_client.get_image_bytes.return_value = self.sample_png_bytes
        self.mock_client.interrupt.return_value = True

        async def fake_track_execution(prompt_id, client_id, progress_cb=None):
            if progress_cb:
                progress_cb(10, 20)
                progress_cb(20, 20)
            return {
                "9": {
                    "images": [
                        {"filename": "concept_001.png", "subfolder": "", "type": "output"}
                    ]
                }
            }

        self.mock_client.track_execution.side_effect = fake_track_execution

        # Initialize JobService
        self.job_service = JobService(
            comfy_client=self.mock_client,
            workflow_registry=self.registry,
            storage=self.storage,
        )

    async def asyncTearDown(self):
        await self.job_service.stop()

        # Clean up database records
        with db.SessionLocal() as s:
            jobs = s.query(db.ImageJob).filter_by(project_id=self.project_id).all()
            for j in jobs:
                s.query(db.ImageOutput).filter_by(job_id=j.id).delete()
            s.query(db.ImageJob).filter_by(project_id=self.project_id).delete()
            s.query(db.Project).filter_by(id=self.project_id).delete()
            s.commit()

        # Clean up filesystem
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_submit_job_success(self):
        req = JobSubmissionRequest(
            project=self.project_name,
            workflow_id="architecture_concept",
            prompt="modernist steel and glass pavilion in forest",
        )
        status = await self.job_service.submit_job(req, user_id=1)
        self.assertIsNotNone(status.job_id)
        self.assertEqual(status.status, "queued")
        self.assertEqual(status.project, self.project_name)

        # Check DB record
        db_job = db.get_image_job(status.job_id)
        self.assertIsNotNone(db_job)
        self.assertEqual(db_job["workflow_id"], "architecture_concept")
        self.assertEqual(db_job["status"], "queued")

    async def test_submit_job_unknown_project_raises_error(self):
        req = JobSubmissionRequest(
            project="nonexistent_project_xyz",
            workflow_id="architecture_concept",
            prompt="modern pavilion",
        )
        with self.assertRaises(ValueError):
            await self.job_service.submit_job(req, user_id=1)

    async def test_submit_job_unknown_workflow_raises_error(self):
        req = JobSubmissionRequest(
            project=self.project_name,
            workflow_id="invalid_workflow_xyz",
            prompt="modern pavilion",
        )
        with self.assertRaises(KeyError):
            await self.job_service.submit_job(req, user_id=1)

    async def test_job_execution_lifecycle_completes(self):
        await self.job_service.start()

        req = JobSubmissionRequest(
            project=self.project_name,
            workflow_id="architecture_concept",
            prompt="futuristic timber library atrium",
            seed=42,
        )
        status = await self.job_service.submit_job(req, user_id=1)

        # Wait for worker queue to empty
        await self.job_service._queue.join()

        # Check final status
        final_status = self.job_service.get_job_status(status.job_id)
        self.assertIsNotNone(final_status)
        self.assertEqual(final_status.status, "completed")
        self.assertEqual(final_status.progress_percent, 100)
        self.assertEqual(len(final_status.outputs), 1)
        self.assertEqual(final_status.outputs[0].filename, "concept_001.png")
        self.assertIsNotNone(final_status.execution_duration_sec)

        # Verify output exists on disk
        file_path, thumb_path = self.storage.get_output_paths(
            self.project_name, final_status.outputs[0].output_id
        )
        self.assertTrue(file_path.exists())
        self.assertTrue(thumb_path.exists())

    async def test_job_execution_handles_cuda_oom(self):
        self.mock_client.track_execution.side_effect = ComfyUIOutOfMemoryError(
            "CUDA out of memory. Tried to allocate 4.50 GiB on RTX 5080."
        )

        await self.job_service.start()

        req = JobSubmissionRequest(
            project=self.project_name,
            workflow_id="architecture_concept",
            prompt="high resolution architectural render",
        )
        status = await self.job_service.submit_job(req, user_id=1)
        await self.job_service._queue.join()

        final_status = self.job_service.get_job_status(status.job_id)
        self.assertEqual(final_status.status, "failed")
        self.assertIn("CUDA out of memory", final_status.error)

    async def test_job_execution_handles_comfy_offline(self):
        self.mock_client.check_health.side_effect = [
            EngineStatus(available=True, base_url="http://127.0.0.1:8188"),
            EngineStatus(available=False, base_url="http://127.0.0.1:8188"),
        ]

        await self.job_service.start()

        req = JobSubmissionRequest(
            project=self.project_name,
            workflow_id="architecture_concept",
            prompt="high resolution architectural render",
        )
        status = await self.job_service.submit_job(req, user_id=1)
        await self.job_service._queue.join()

        final_status = self.job_service.get_job_status(status.job_id)
        self.assertEqual(final_status.status, "failed")
        self.assertIn("ComfyUI is currently offline", final_status.error)

    async def test_cancel_job(self):
        req = JobSubmissionRequest(
            project=self.project_name,
            workflow_id="architecture_concept",
            prompt="modernist villa",
        )
        status = await self.job_service.submit_job(req, user_id=1)

        # Cancel while queued
        cancelled = await self.job_service.cancel_job(status.job_id, user_id=1)
        self.assertTrue(cancelled)

        final_status = self.job_service.get_job_status(status.job_id)
        self.assertEqual(final_status.status, "cancelled")

    async def test_cancel_job_permission_denied(self):
        req = JobSubmissionRequest(
            project=self.project_name,
            workflow_id="architecture_concept",
            prompt="modernist villa",
        )
        status = await self.job_service.submit_job(req, user_id=1)

        # Another non-admin user cannot cancel
        with self.assertRaises(PermissionError):
            await self.job_service.cancel_job(status.job_id, user_id=2, is_admin=False)

        # Admin user CAN cancel
        admin_cancelled = await self.job_service.cancel_job(status.job_id, user_id=2, is_admin=True)
        self.assertTrue(admin_cancelled)

    async def test_reconcile_interrupted_jobs(self):
        # Create an orphaned 'running' job in DB simulating prior process crash
        stale_id = f"stale-{uuid.uuid4().hex[:8]}"
        db.create_image_job(
            job_id=stale_id,
            project_id=self.project_id,
            user_id=1,
            workflow_id="architecture_concept",
            input_params={},
        )
        db.update_image_job(stale_id, status="running")

        # Run reconciliation
        self.job_service._reconcile_interrupted_jobs()

        stale_record = db.get_image_job(stale_id)
        self.assertEqual(stale_record["status"], "failed")
        self.assertIn("Server restarted", stale_record["error_message"])

    async def test_list_jobs(self):
        req1 = JobSubmissionRequest(
            project=self.project_name,
            workflow_id="architecture_concept",
            prompt="villa 1",
        )
        req2 = JobSubmissionRequest(
            project=self.project_name,
            workflow_id="architecture_concept",
            prompt="villa 2",
        )
        await self.job_service.submit_job(req1, user_id=1)
        await self.job_service.submit_job(req2, user_id=1)

        jobs = self.job_service.list_jobs(self.project_name)
        self.assertEqual(len(jobs), 2)


if __name__ == "__main__":
    unittest.main()
